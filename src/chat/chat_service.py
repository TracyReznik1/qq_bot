import json
import re
from threading import Lock
from typing import Any

from src.chat.prompt import build_system_prompt
from src.chat.search_tool import search_web
from src.config import config
from src.services.deepseek_client import ChatResponse, DeepSeekClient


deepseek = DeepSeekClient(config)
chat_history: dict[str, list[dict[str, str]]] = {}
chat_history_lock = Lock()
MAX_TOOL_CALL_ROUNDS = 2
TOOL_CALL_LIMIT_FALLBACK = "我搜到了信息，但没能整理出可靠回答。可以换个问法再试一次。"

SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "搜索网页。普通聊天里遇到不懂、不确定、新梗、黑话、缩写、圈内 ID、人名、当前事件等必须搜索；搜索结果只能作为参考，最终回答必须由模型加工。",
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
