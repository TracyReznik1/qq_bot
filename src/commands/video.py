"""`/video` command — summarize Bilibili videos using metadata and subtitles."""

from __future__ import annotations

from src.chat.chat_service import _plain_reply
from src.chat.prompt import format_bilibili_video_sandbox
from src.commands import CommandContext
from src.config import config
from src.services.video_service import (
    extract_bilibili_id,
    fetch_bilibili_video,
)


def video_reply(query: str, context: CommandContext) -> str:
    raw = query.strip()
    if not raw:
        return (
            "想让我总结哪个B站视频？\n"
            "用法示例：\n"
            "/video https://www.bilibili.com/video/BV1xx411c7mD\n"
            "/video BV1xx411c7mD 重点讲了哪些内容？"
        )

    bvid, aid = extract_bilibili_id(raw)
    if not bvid and not aid:
        return "没有识别到有效的 B站 BV 号或视频链接，请检查后重试。"

    video_data = fetch_bilibili_video(raw)
    if not video_data.ok:
        return f"视频信息读取失败：{video_data.error_message or '无法获取该视频信息。'}"

    video_payload = format_bilibili_video_sandbox(video_data)

    user_instruction = raw
    # If user provided only the URL/BV without custom query, supply a structured summary prompt
    target_id = bvid or (f"av{aid}" if aid else "")
    remaining = user_instruction
    if target_id and target_id in remaining:
        remaining = remaining.replace(target_id, "")
    # Also strip possible url prefixes
    for prefix in ("https://www.bilibili.com/video/", "http://www.bilibili.com/video/", "https://b23.tv/", "http://b23.tv/"):
        remaining = remaining.replace(prefix, "")
    remaining = remaining.strip(" /?&=_")

    if not remaining:
        user_instruction = "请对该B站视频进行结构化总结，包含核心主题、分段大纲要点与关键结论。"
    else:
        user_instruction = f"针对该B站视频，请重点回答并总结：{remaining}"

    timeout = float(getattr(config, "search_answer_timeout", 20.0))
    return _plain_reply(
        context.memory_context,
        user_instruction,
        list(context.image_data_urls),
        timeout_seconds=timeout,
        video_payload=video_payload,
    )
