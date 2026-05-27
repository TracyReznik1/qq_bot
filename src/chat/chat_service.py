import json
import re
from threading import Lock
from typing import Any

from src.chat.prompt import build_system_prompt
from src.chat.search_tool import search_web
from src.config import config
from src.services.deepseek_client import ChatResponse, DeepSeekClient
from src.services.search_service import requires_reliable_search_result


deepseek = DeepSeekClient(config)
chat_history: dict[str, list[dict[str, str]]] = {}
chat_history_lock = Lock()
MAX_TOOL_CALL_ROUNDS = 2
TOOL_CALL_LIMIT_FALLBACK = "我搜到了信息，但没能整理出可靠回答。可以换个问法再试一次。"

SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "搜索网页。仅用于代码层已经允许的场景：最新信息、实时信息、价格、新版本、冷门知识、专有名词、圈内昵称、梗或明显不确定内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to look up.",
                }
            },
            "required": ["query"],
        },
    },
}


def _contains_any(text: str, markers: list[str]) -> bool:
    return any(marker in text for marker in markers)


def is_weather_chat(text: str) -> bool:
    lowered = text.lower()
    weather_markers = [
        "天气",
        "气温",
        "温度",
        "下雨",
        "降雨",
        "雨吗",
        "雨么",
        "会下雨",
        "冷吗",
        "热吗",
        "好冷",
        "好热",
        "穿什么",
        "空气质量",
        "雾霾",
        "台风",
        "湿度",
    ]
    return _contains_any(lowered, weather_markers)


def is_image_chat(text: str) -> bool:
    lowered = text.lower()
    image_markers = [
        "画图",
        "绘图",
        "生成图片",
        "生成一张",
        "发图",
        "图片",
        "头像",
        "壁纸",
        "画一张",
        "帮我画",
    ]
    return _contains_any(lowered, image_markers)


def should_allow_auto_search(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().lower().split())
    if not normalized:
        return False
    if is_weather_chat(normalized) or is_image_chat(normalized):
        return False

    if requires_reliable_search_result(normalized, ""):
        return True

    personal_questions = ("你是谁", "你是什么", "我是谁", "我是什么")
    if normalized.startswith(personal_questions):
        return False

    knowledge_markers = [
        "是谁",
        "是什么",
        "什么意思",
        "啥意思",
        "什么梗",
        "哪位",
        "哪个",
        "冷门",
        "小众",
        "不确定",
        "查一下",
        "帮我查",
        "搜一下",
        "资料",
        "文档",
        "用法",
        "怎么用",
        "报错",
    ]
    if _contains_any(normalized, knowledge_markers):
        if normalized in {"你是谁", "我是谁", "你是什么", "我是什么"}:
            return False
        return True

    return False


def filter_search_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    search_calls = []
    for tool_call in tool_calls:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if isinstance(function, dict) and function.get("name") == "search_web":
            search_calls.append(tool_call)
    return search_calls


def normalize_chat_response(response: ChatResponse | str) -> ChatResponse:
    if isinstance(response, ChatResponse):
        return response
    return ChatResponse(content=str(response or ""))


def tool_call_query(tool_call: dict[str, Any], fallback: str) -> str:
    function = tool_call.get("function") if isinstance(tool_call, dict) else {}
    arguments = function.get("arguments") if isinstance(function, dict) else "{}"
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    return str(args.get("query") or fallback).strip()


def build_search_tool_messages(tool_calls: list[dict[str, Any]], fallback_query: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": None, "tool_calls": tool_calls}
    ]
    for index, tool_call in enumerate(tool_calls, 1):
        query = tool_call_query(tool_call, fallback_query)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(tool_call.get("id") or f"search_web_{index}"),
                "name": "search_web",
                "content": search_web(query),
            }
        )
    return messages


def append_history(session_key: str, user_text: str, assistant_text: str) -> None:
    with chat_history_lock:
        history = chat_history.setdefault(session_key, [])
        history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        chat_history[session_key] = history[-max(config.history_turns, 1) * 2 :]


def reset_history(session_key: str) -> None:
    with chat_history_lock:
        chat_history.pop(session_key, None)


def generate_reply(session_key: str, text: str, tool_context: str = "") -> str:
    messages: list[dict[str, Any]] = [{"role": "system", "content": build_system_prompt(session_key, tool_context)}]
    with chat_history_lock:
        messages.extend(chat_history.get(session_key, []).copy())
    messages.append({"role": "user", "content": text})

    if tool_context.strip():
        reply = normalize_chat_response(deepseek.chat(messages, temperature=0.75)).content
    elif not should_allow_auto_search(text):
        reply = normalize_chat_response(deepseek.chat(messages, temperature=0.75)).content
    else:
        reply = ""
        needs_final_summary = False
        for _round in range(MAX_TOOL_CALL_ROUNDS):
            response = normalize_chat_response(
                deepseek.chat(
                    messages,
                    temperature=0.75,
                    tools=[SEARCH_WEB_TOOL],
                    tool_choice="auto",
                )
            )
            reply = response.content
            tool_calls = filter_search_tool_calls(response.tool_calls)
            if not tool_calls:
                needs_final_summary = False
                break
            messages.extend(build_search_tool_messages(tool_calls, text))
            needs_final_summary = True

        if needs_final_summary:
            reply = normalize_chat_response(deepseek.chat(messages, temperature=0.75)).content
            if not reply.strip():
                reply = TOOL_CALL_LIMIT_FALLBACK

    reply = re.sub(r"\[(?:SRCH|MEM|CHAT):?.*?\]", "", reply).strip()
    append_history(session_key, text, reply)
    return reply
