"""`/pic` command — search and send images via OneBot.

Requires ``IMAGE_SEARCH_ENABLE=true`` in ``.env`` and a valid Tavily API key.
Only triggered by explicit ``/pic`` command, never from ordinary chat.
"""

import re
from pathlib import Path

from src.config import config
from src.services.image_search_service import search_and_download_images
from src.services.onebot_client import build_cq_image_file


def pic_reply(query: str, context) -> str:
    """Return a plain-text reply for the /pic command.

    The caller (``src/commands/__init__.py``) wraps the result in
    ``CommandResult`` via ``_text_result()``.

    Syntax:
        /pic 关键词           → 返回 1 张图
        /pic 关键词 3         → 最多返回 3 张图
    """
    # 1. Feature not enabled
    if not config.image_search_enable:
        return (
            "图片搜索功能未启用。"
            "请在 .env 中设置 IMAGE_SEARCH_ENABLE=true 并确认 TAVILY_API_KEY 已配置。"
        )

    raw = query.strip()

    # 2. Empty input
    if not raw:
        return (
            "用法：/pic 关键词 [数量]\n"
            "例如：/pic 蓝色雨夜 二次元头像\n"
            "例如：/pic 夏目安安 3"
        )

    # 3. Parse optional trailing count: "/pic 关键词 3"
    limit = 1
    match = re.match(r"^(.+?)\s+(\d+)\s*$", raw)
    if match:
        keywords = match.group(1).strip()
        requested = int(match.group(2))
        send_max = min(config.image_search_send_max, 3)
        limit = max(1, min(requested, send_max))
    else:
        keywords = raw

    if not keywords:
        return "请输入搜索关键词。例如：/pic 蓝色雨夜"

    # 4. Search and download
    results = search_and_download_images(keywords, limit=limit)

    if not results:
        return f"没有找到关于「{keywords}」的图片，请尝试换个关键词。"

    # 5. Build reply with CQ:image and source info
    # Image CQ codes are built via the shared helper so that the
    # base64 fallback in OneBotClient.send_image() takes effect.
    lines: list[str] = []
    for i, result in enumerate(results):
        safe_path = str(Path(result.local_path).resolve())
        lines.append(build_cq_image_file(safe_path))

        # Append source info
        source_parts: list[str] = []
        if result.title:
            source_parts.append(result.title)
        if result.source_url:
            source_parts.append(f"来源: {result.source_url}")
        elif result.image_url:
            source_parts.append(f"图片: {result.image_url}")
        if source_parts:
            lines.append(" | ".join(source_parts))

    return "\n".join(lines)
