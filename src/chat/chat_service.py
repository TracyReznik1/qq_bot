import json
import logging
import re
from pathlib import Path
from threading import Lock
from typing import Any

from src.chat.prompt import build_system_prompt, build_untrusted_context
from src.services.bilibili_search import (
    bilibili_user_search,
    bilibili_video_search,
    has_bilibili_search_signal,
)
from src.services.search_service import web_search as search_web
from src.services.search_service import normalize_search_query
from src.services.search_service import search_query_specificity_score
from src.services.url_fetch_service import extract_first_url, fetch_url, has_url
from src.services.video_service import extract_video_url, has_video_url, understand_video
from src.config import config
from src.services.llm_client import get_llm_client
from src.services.llm_types import ChatResponse
from src.utils.storage import read_json, safe_id, write_json


logger = logging.getLogger("qq-bot")

llm = get_llm_client()
chat_history: dict[str, list[dict[str, str]]] = {}
chat_history_lock = Lock()
HISTORY_DIR = config.data_dir / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
MAX_TOOL_CALL_ROUNDS = 2
TOOL_CALL_LIMIT_FALLBACK = "我搜到了信息，但没能整理出可靠回答。可以换个问法再试一次。"

SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "搜索网页，并按来源优先级自动安全读取部分结果页正文摘录，由模型自行判断是否调用。闲聊、情绪回应、角色语气、记忆已能回答的问题不要搜索；"
            "遇到最新/实时信息、不懂、不确定、新梗、黑话、缩写、圈内 ID、人名、公开项目、产品、版本或当前事件等必须搜索。"
            "用户问最近为什么火、趋势、原因、评价或舆论变化时，即使主题看似熟悉也要搜索。"
            "用户给出明确 URL 时应使用 fetch_url，不要用 search_web 搜索 URL。"
            "搜索结果只能作为参考，最终回答必须由模型加工。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "搜索关键词，从用户最新消息中提取。"
                        "规则：提取核心名词、专有名词、事件名、作品名、人名、梗/黑话，用空格分隔；"
                        "保留限定词，例如平台、作者、版本、时间、作品名、产品名、原因、趋势、评价、舆论；不要只给单个泛词；"
                        "去掉语气词、追问、闲聊成分和已在前文解释过的上下文；"
                        "不要用完整问句，不要带\"怎么\"、\"什么\"、\"为什么\"。"
                    ),
                }
            },
            "required": ["query"],
        },
    },
}

BILIBILI_USER_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "bilibili_user_search",
        "description": "筛词后搜索 B站公开用户、UP主、主播资料。工具内部会先用 DeepSeek 筛选关键词；仅在用户明确提到 B站、bilibili、小破站、阿B、UP主、主播或直播间时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户原始 B站用户搜索请求或关键词，工具内部会筛词后搜索。",
                }
            },
            "required": ["query"],
        },
    },
}

BILIBILI_VIDEO_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "bilibili_video_search",
        "description": "筛词后搜索 B站公开视频、投稿、教程、剪辑、评测或 BV/av 号相关视频。工具内部会先用 DeepSeek 筛选关键词；仅在用户明确提到 B站、bilibili、小破站、阿B、B站视频、投稿或 BV/av 号时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "用户原始 B站视频搜索请求或关键词，工具内部会筛词后搜索。",
                }
            },
            "required": ["query"],
        },
    },
}

FETCH_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": (
            "直接读取用户给出的 http/https 网页 URL，提取标题和正文摘录后供模型总结。"
            "只有用户消息里已经出现明确 URL 时才使用；不要把 URL 交给 search_web 搜索。"
            "视频链接、B站 BV 号或 av 号应优先使用 understand_video_url。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "用户消息中的完整 http/https URL。",
                }
            },
            "required": ["url"],
        },
    },
}

VIDEO_UNDERSTANDING_TOOL = {
    "type": "function",
    "function": {
        "name": "understand_video_url",
        "description": (
            "理解用户给出的视频链接。优先读取 B站视频标题、简介、统计信息和可用字幕；"
            "其他视频页只读取页面文字。当前不做逐帧画面理解或音频 ASR，不要声称完整看过视频。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "用户消息中的视频 URL、B站 BV 号或 av 号。",
                }
            },
            "required": ["url"],
        },
    },
}

SUPPORTED_TOOL_NAMES = {
    "search_web",
    "bilibili_user_search",
    "bilibili_video_search",
    "fetch_url",
    "understand_video_url",
}


def chat_tools_for_text(text: str) -> list[dict[str, Any]]:
    tools = [SEARCH_WEB_TOOL]
    has_video_reference = has_video_url(text)
    if has_video_reference:
        tools.append(VIDEO_UNDERSTANDING_TOOL)
    if has_url(text):
        tools.append(FETCH_URL_TOOL)
    if has_bilibili_search_signal(text) and not has_video_reference:
        tools.append(BILIBILI_USER_SEARCH_TOOL)
        tools.append(BILIBILI_VIDEO_SEARCH_TOOL)
    return tools


def tool_function_name(tool_call: dict[str, Any]) -> str:
    function = tool_call.get("function") if isinstance(tool_call, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def filter_tool_calls(tool_calls: list[dict[str, Any]], allowed_names: set[str]) -> list[dict[str, Any]]:
    supported_calls = []
    for tool_call in tool_calls:
        name = tool_function_name(tool_call)
        if name in allowed_names and name in SUPPORTED_TOOL_NAMES:
            supported_calls.append(tool_call)
    return supported_calls


def run_tool(name: str, query: str) -> str:
    if name == "bilibili_user_search":
        return bilibili_user_search(query)
    if name == "bilibili_video_search":
        return bilibili_video_search(query)
    if name == "understand_video_url":
        result = understand_video(query)
        return result.text if hasattr(result, "text") else str(result or "")
    if name == "fetch_url" and has_video_url(query):
        result = understand_video(query)
        return result.text if hasattr(result, "text") else str(result or "")
    if name == "fetch_url":
        result = fetch_url(query)
        return result.text if hasattr(result, "text") else str(result or "")
    if name == "search_web" and has_video_url(query):
        result = understand_video(query)
        return result.text if hasattr(result, "text") else str(result or "")
    if name == "search_web" and has_url(query):
        result = fetch_url(query)
        return result.text if hasattr(result, "text") else str(result or "")
    return search_web(query)


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
    return str(args.get("query") or args.get("url") or fallback).strip()


SEARCH_QUERY_INTENT_MARKERS = (
    "为什么",
    "原因",
    "趋势",
    "评价",
    "舆论",
    "最近",
    "最新",
    "当前",
    "发布",
    "更新",
    "火",
    "爆火",
    "走红",
)


def _compact_query_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").casefold())


def _fallback_has_more_search_intent(normalized: str, fallback: str, fallback_normalized: str) -> bool:
    normalized_compact = _compact_query_text(normalized)
    fallback_compact = _compact_query_text(fallback_normalized)
    if not normalized_compact or not fallback_compact:
        return False
    if normalized_compact not in fallback_compact:
        return False
    if len(fallback_compact) <= len(normalized_compact) + 1:
        return False
    marker_text = f"{fallback} {fallback_normalized}"
    return any(marker in marker_text for marker in SEARCH_QUERY_INTENT_MARKERS)


def _url_tool_query(query: str, fallback: str) -> str:
    return extract_first_url(query) or extract_first_url(fallback) or str(query or fallback).strip()


def _video_tool_query(query: str, fallback: str) -> str:
    query = str(query or "").strip()
    fallback = str(fallback or "").strip()
    video_url = extract_video_url(query) or extract_video_url(fallback)
    if video_url:
        return video_url
    if query:
        return query
    return fallback


def normalize_tool_query(name: str, query: str, fallback: str) -> str:
    if name == "fetch_url":
        return _url_tool_query(query, fallback)
    if name == "understand_video_url":
        return _video_tool_query(query, fallback)
    if name != "search_web":
        return str(query or fallback).strip()
    normalized = normalize_search_query(query)
    fallback_normalized = normalize_search_query(fallback)
    if normalized:
        if (
            fallback_normalized
            and search_query_specificity_score(fallback_normalized) > search_query_specificity_score(normalized)
        ):
            return fallback_normalized
        if fallback_normalized and _fallback_has_more_search_intent(normalized, fallback, fallback_normalized):
            return fallback_normalized
        return normalized
    return fallback_normalized or str(query or fallback).strip()


def build_tool_messages(tool_calls: list[dict[str, Any]], fallback_query: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "assistant", "content": None, "tool_calls": tool_calls}
    ]
    for index, tool_call in enumerate(tool_calls, 1):
        name = tool_function_name(tool_call)
        query = normalize_tool_query(name, tool_call_query(tool_call, ""), fallback_query)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(tool_call.get("id") or f"{name}_{index}"),
                "name": name,
                "content": run_tool(name, query),
            }
        )
    return messages


def _history_path(session_key: str) -> Path:
    return HISTORY_DIR / f"{safe_id(session_key)}.json"


def _load_history_unlocked(session_key: str) -> list[dict[str, str]]:
    if not config.persist_history:
        return []
    data = read_json(_history_path(session_key), {"messages": []})
    messages = data.get("messages", []) if isinstance(data, dict) else []
    limit = max(config.history_turns, 1) * 2
    return [msg for msg in messages[-limit:] if isinstance(msg, dict) and "role" in msg and "content" in msg]


def _save_history_unlocked(session_key: str, history: list[dict[str, str]]) -> None:
    if not config.persist_history:
        return
    write_json(_history_path(session_key), {"messages": history})


def _remove_history_file(session_key: str) -> None:
    path = _history_path(session_key)
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.debug("Failed to remove history file: %s", path)


def append_history(session_key: str, user_text: str, assistant_text: str) -> None:
    with chat_history_lock:
        history = chat_history.setdefault(session_key, [])
        history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": assistant_text},
            ]
        )
        limit = max(config.history_turns, 1) * 2
        history[:] = history[-limit:]
        _save_history_unlocked(session_key, history)


def reset_history(session_key: str) -> None:
    with chat_history_lock:
        chat_history.pop(session_key, None)
    _remove_history_file(session_key)


def _ensure_history_loaded(session_key: str) -> None:
    with chat_history_lock:
        history = chat_history.setdefault(session_key, [])
        if not history and config.persist_history:
            loaded = _load_history_unlocked(session_key)
            history.extend(loaded)


def generate_reply(session_key: str, text: str, tool_context: str = "") -> str:
    _ensure_history_loaded(session_key)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(session_key, tool_context)},
        {"role": "user", "content": build_untrusted_context(session_key, tool_context)},
    ]
    with chat_history_lock:
        messages.extend(chat_history.get(session_key, []).copy())
    messages.append({"role": "user", "content": text})

    if tool_context.strip():
        reply = normalize_chat_response(llm.chat(messages, temperature=0.75)).content
    else:
        reply = ""
        needs_final_summary = False
        tools = chat_tools_for_text(text)
        allowed_tool_names = {
            str(tool.get("function", {}).get("name") or "")
            for tool in tools
            if isinstance(tool.get("function"), dict)
        }
        for _round in range(MAX_TOOL_CALL_ROUNDS):
            response = normalize_chat_response(
                llm.chat(
                    messages,
                    temperature=0.75,
                    tools=tools,
                    tool_choice="auto",
                )
            )
            reply = response.content
            tool_calls = filter_tool_calls(response.tool_calls, allowed_tool_names)
            if not tool_calls:
                needs_final_summary = False
                break
            messages.extend(build_tool_messages(tool_calls, text))
            needs_final_summary = True

        if needs_final_summary:
            reply = normalize_chat_response(llm.chat(messages, temperature=0.75)).content
            if not reply.strip():
                reply = TOOL_CALL_LIMIT_FALLBACK

    reply = re.sub(r"\[(?:SRCH|MEM|CHAT):?.*?\]", "", reply).strip()
    append_history(session_key, text, reply)
    return reply
