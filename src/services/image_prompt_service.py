"""LLM-based prompt conversion, safety filter, and ImagePromptSpec.

Uses the project's existing LLM client (``get_llm_client()``) to convert
a Chinese user request into a ComfyUI-ready ``ImagePromptSpec``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from src.services.llm_client import get_llm_client

logger = logging.getLogger("qq-bot")

# ── data ────────────────────────────────────────────────────────────────

@dataclass
class ImagePromptSpec:
    positive_prompt: str = ""
    negative_prompt: str = ""
    width: int = 832
    height: int = 1216
    steps: int | None = None
    cfg: float | None = None
    seed: int | None = None
    preset: str = "highres_output"
    blocked: bool = False
    block_reason: str = ""


DEFAULT_NEGATIVE = (
    "worst quality, low quality, score_1, score_2, score_3, "
    "lowres, blurry, jpeg artifacts, bad anatomy, bad hands, "
    "extra fingers, malformed fingers, missing fingers, "
    "watermark, artist name, signature, text"
)

# ── safety filter ───────────────────────────────────────────────────────

# Keywords that trigger a block *before* the LLM prompt extraction.
_BLOCK_PATTERNS = [
    r"\br18\b",
    r"露点",
    r"性器官",
    r"未成年.*色情",
    r"真实人物.*色情",
    r"强奸",
    r"非自愿",
    r"兽交",
    r"现实儿童",
    r"身份证",
    r"隐私证件",
    r"极端血腥",
    r"\bnude\b",
    r"\bnaked\b",
    r"\bporn\b",
    r"\bnsfw\b",
]

BLOCK_REPLY = (
    "这个图片请求不适合生成。可以改成普通头像、立绘、日常服装、风景或氛围图。"
)


def _check_blocked(text: str) -> tuple[bool, str]:
    """Return (True, reason) if *text* should be blocked."""
    lowered = text.lower()
    for pattern in _BLOCK_PATTERNS:
        if re.search(pattern, lowered):
            return True, "内容过滤：请求包含不适合生成的内容。"
    return False, ""


# ── LLM prompt conversion ───────────────────────────────────────────────

_PROMPT_SYSTEM = (
    "你是 ComfyUI / Anima 二次元提示词助手。\n"
    "把用户中文需求转换为英文逗号分隔标签。\n"
    "只输出 JSON，不要解释。\n"
    "positive_prompt 必须是英文 tag list。\n"
    "negative_prompt 必须是英文 tag list。\n"
    "默认面向 Anima 二次元模型。\n"
    "默认预设是 highres_output。\n"
    "不要输出色情露点、未成年色情、真实人物色情、非自愿性内容、极端血腥、隐私证件等内容。\n"
    "如果请求不适合生成，返回 blocked=true 和 reason。\n"
    "\n"
    "格式：\n"
    '{"blocked":false,'
    '"positive_prompt":"masterpiece, best quality, 1girl, ...",'
    '"negative_prompt":"worst quality, low quality, ...",'
    '"width":832,"height":1216,"preset":"highres_output"}'
)


def _try_llm_convert(user_text: str) -> ImagePromptSpec | None:
    """Use the project LLM to convert user_text.  Returns ``None`` on failure."""
    try:
        llm = get_llm_client()
        response = llm.chat(
            [
                {"role": "system", "content": _PROMPT_SYSTEM},
                {"role": "user", "content": user_text},
            ],
            temperature=0.3,
            max_tokens=512,
        )
    except Exception:
        logger.debug("LLM prompt conversion failed", exc_info=True)
        return None

    content = response.content.strip()
    # Strip markdown code fences
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:])
        if content.endswith("```"):
            content = content[:-3]
    content = content.strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.debug("LLM returned non-JSON prompt: %s", content[:200])
        return None

    if not isinstance(data, dict):
        return None

    blocked = bool(data.get("blocked", False))
    block_reason = str(data.get("block_reason") or data.get("reason") or "")

    return ImagePromptSpec(
        positive_prompt=str(data.get("positive_prompt", "") or "").strip(),
        negative_prompt=str(data.get("negative_prompt", "") or "").strip(),
        width=int(data.get("width", 832)),
        height=int(data.get("height", 1216)),
        preset=str(data.get("preset", "highres_output") or "highres_output").strip(),
        blocked=blocked,
        block_reason=block_reason,
    )


# ── public API ──────────────────────────────────────────────────────────

def build_prompt_spec(user_text: str) -> ImagePromptSpec:
    """Security filter → LLM conversion → fallback to local defaults.

    Returns an ``ImagePromptSpec``.  If ``blocked=True``, generation should
    be aborted.
    """
    blocked, reason = _check_blocked(user_text)
    if blocked:
        return ImagePromptSpec(blocked=True, block_reason=reason)

    spec = _try_llm_convert(user_text)

    if spec is None:
        # LLM unavailable — return a blocked spec so we don't pipe raw
        # Chinese directly into ComfyUI.
        return ImagePromptSpec(
            blocked=True,
            block_reason="内部助手暂时不可用，无法转换提示词。请稍后再试。",
        )

    if spec.blocked:
        return spec

    # Enforce defaults
    if not spec.positive_prompt:
        return ImagePromptSpec(
            blocked=True,
            block_reason="提示词助手没有生成有效的 positive prompt。",
        )
    if not spec.negative_prompt:
        spec.negative_prompt = DEFAULT_NEGATIVE
    if spec.width <= 0:
        spec.width = 832
    if spec.height <= 0:
        spec.height = 1216

    return spec
