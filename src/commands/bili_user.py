"""`/up` command — search and inspect Bilibili UP owners / creators."""

from __future__ import annotations

from src.chat.chat_service import _plain_reply
from src.chat.prompt import escape_xml_text
from src.commands import CommandContext
from src.config import config
from src.services.video_service import (
    fetch_bilibili_user,
    format_bilibili_user_card,
)


def bili_user_reply(query: str, context: CommandContext) -> str:
    raw = str(query or "").strip()
    if not raw:
        return (
            "想查询哪位 B站 UP主？\n"
            "用法示例：\n"
            "/up 影视飓风\n"
            "/up 946974\n"
            "/biliup 老师好我叫何同学\n"
            "/up 影视飓风 他的主要视频风格是什么？"
        )

    # Check if there is an additional question after the creator name / UID
    parts = raw.split(maxsplit=1)
    target = parts[0].strip()
    question = parts[1].strip() if len(parts) > 1 else ""

    payload = fetch_bilibili_user(target)
    if not payload.ok:
        return payload.error_message or f"未找到与 “{target}” 相关的 B站 UP主，请检查后重试。"

    card_text = format_bilibili_user_card(payload)
    if not question:
        # Fast path: instant card reply with zero LLM latency and zero tokens
        return card_text

    # LLM path: user asked a targeted question
    safe_uname = escape_xml_text(payload.uname)
    safe_card = escape_xml_text(card_text)
    user_sandbox = (
        f'<bilibili_up_user mid="{payload.mid}" name="{safe_uname}">\n'
        f"{safe_card}\n"
        f"</bilibili_up_user>"
    )
    user_instruction = f"针对B站UP主【{payload.uname}】，请结合其名片与最新投稿信息，回答并总结：{question}"
    timeout = float(getattr(config, "search_answer_timeout", 20.0))
    return _plain_reply(
        context.memory_context,
        user_instruction,
        list(context.image_data_urls),
        timeout_seconds=timeout,
        video_payload=user_sandbox,
    )
