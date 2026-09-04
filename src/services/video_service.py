"""Bilibili video metadata and subtitle extraction service."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from functools import reduce
from hashlib import md5
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from src.config import config
from src.util import try_proxied_get

logger = logging.getLogger("qq-bot")

BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_VIEW_URL = "https://api.bilibili.com/x/web-interface/wbi/view"
BILIBILI_PLAYER_URL = "https://api.bilibili.com/x/player/wbi/v2"

BILIBILI_BV_ID_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])BV[0-9A-Za-z]{10}(?![0-9A-Za-z])")
BILIBILI_AV_ID_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])")
BILIBILI_SHORT_LINK_PATTERN = re.compile(r"(?i)https?://b23\.tv/[^\s<>'\"]+")
MAX_SUBTITLE_CHARS = 20000

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]
WBI_KEY_TTL_SECONDS = 3600.0
_wbi_lock = Lock()
_cached_mixin_key: str = ""
_cached_mixin_key_expire: float = 0.0


def _get_mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]


def get_wbi_mixin_key() -> str:
    global _cached_mixin_key, _cached_mixin_key_expire
    now = time.time()
    with _wbi_lock:
        if _cached_mixin_key and now < _cached_mixin_key_expire:
            return _cached_mixin_key

    try:
        resp = try_proxied_get(
            BILIBILI_NAV_URL,
            proxies=config.proxies,
            timeout=getattr(config, "request_timeout", 8.0),
            headers=_headers(),
        )
        data = resp.json()
        if isinstance(data, dict) and data.get("code") == 0:
            wbi_img = data.get("data", {}).get("wbi_img", {})
            img_url = str(wbi_img.get("img_url") or "")
            sub_url = str(wbi_img.get("sub_url") or "")
            if img_url and sub_url:
                img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
                sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
                new_mixin = _get_mixin_key(img_key + sub_key)
                with _wbi_lock:
                    _cached_mixin_key = new_mixin
                    _cached_mixin_key_expire = now + WBI_KEY_TTL_SECONDS
                return new_mixin
    except Exception as exc:
        logger.debug("Failed to fetch bilibili wbi keys: %s", exc)

    with _wbi_lock:
        if _cached_mixin_key:
            return _cached_mixin_key
    return "ea1db124af3c281b47417b515f460577"


def sign_wbi_params(params: dict[str, Any]) -> dict[str, Any]:
    mixin_key = get_wbi_mixin_key()
    signed = dict(params)
    signed["wts"] = round(time.time())
    signed = dict(sorted(signed.items()))
    filtered = {
        k: "".join(filter(lambda c: c not in "!*'()", str(v)))
        for k, v in signed.items()
    }
    query = urllib.parse.urlencode(filtered)
    signed["w_rid"] = md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed


@dataclass(frozen=True)
class BilibiliVideoPayload:
    ok: bool
    status: str
    bvid: str = ""
    aid: str = ""
    title: str = ""
    owner_name: str = ""
    duration_seconds: int = 0
    pubdate_str: str = ""
    desc: str = ""
    part_title: str = ""
    view_count: int = 0
    like_count: int = 0
    has_subtitles: bool = False
    subtitles_text: str = ""
    error_message: str = ""


def _headers(referer: str = "https://www.bilibili.com/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }


def _resolve_short_link(url: str) -> str:
    try:
        resp = try_proxied_get(
            url,
            proxies=config.proxies,
            timeout=5.0,
            headers=_headers(),
            stream=True,
        )
        final_url = getattr(resp, "url", "") or url
        return str(final_url)
    except Exception:
        logger.debug("b23.tv short link resolution failed: %s", url)
        return url


def extract_bilibili_id(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    # Check for short link first
    short_match = BILIBILI_SHORT_LINK_PATTERN.search(raw)
    if short_match:
        resolved = _resolve_short_link(short_match.group(0))
        raw = f"{raw} {resolved}"

    bv_match = BILIBILI_BV_ID_PATTERN.search(raw)
    if bv_match:
        return bv_match.group(0), ""

    av_match = BILIBILI_AV_ID_PATTERN.search(raw)
    if av_match:
        return "", av_match.group(1)

    return "", ""


def is_bilibili_video_url(url_or_text: str) -> bool:
    raw = str(url_or_text or "").strip()
    if BILIBILI_SHORT_LINK_PATTERN.search(raw):
        return True
    if BILIBILI_BV_ID_PATTERN.search(raw) or BILIBILI_AV_ID_PATTERN.search(raw):
        # Exclude column articles like cv12345
        if "read/cv" in raw:
            return False
        return True
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"} and "/video/" in parsed.path:
            return True
    except Exception:
        pass
    return False


def _format_pubdate(value: object) -> str:
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _best_subtitle(subtitles: list[dict]) -> dict:
    if not subtitles:
        return {}
    for preferred in ("zh-CN", "zh-Hans", "ai-zh", "zh"):
        for item in subtitles:
            if str(item.get("lan") or "").casefold() == preferred.casefold():
                return item
    return subtitles[0]


def _download_subtitles(subtitle_url: str) -> str:
    if not subtitle_url:
        return ""
    if subtitle_url.startswith("//"):
        subtitle_url = f"https:{subtitle_url}"
    try:
        resp = try_proxied_get(
            subtitle_url,
            proxies=config.proxies,
            timeout=getattr(config, "request_timeout", 10.0),
            headers=_headers(),
        )
        data = resp.json()
    except Exception as exc:
        logger.debug("Failed to download bilibili subtitle: %s", exc)
        return ""

    body = data.get("body") if isinstance(data, dict) else []
    if not isinstance(body, list):
        return ""

    lines: list[str] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        content = " ".join(str(item.get("content") or "").split()).strip()
        if content:
            from_sec = int(float(item.get("from") or 0))
            m, s = divmod(from_sec, 60)
            timestamp = f"{m:02d}:{s:02d}"
            lines.append(f"[{timestamp}] {content}")

    full_text = "\n".join(lines)
    if len(full_text) > MAX_SUBTITLE_CHARS:
        # Keep head (70%) and tail (30%)
        head_len = int(MAX_SUBTITLE_CHARS * 0.7)
        tail_len = int(MAX_SUBTITLE_CHARS * 0.3)
        full_text = (
            f"{full_text[:head_len]}\n\n"
            f"... [中间部分字幕已压缩省略，共省略约 {len(full_text) - head_len - tail_len} 字符] ...\n\n"
            f"{full_text[-tail_len:]}"
        )
    return full_text


def fetch_bilibili_video(
    url_or_text: str = "",
    *,
    bvid: str = "",
    aid: str = "",
) -> BilibiliVideoPayload:
    if not bvid and not aid:
        bvid, aid = extract_bilibili_id(url_or_text)
    if not bvid and not aid:
        return BilibiliVideoPayload(
            ok=False,
            status="invalid_url",
            error_message="未识别到有效的 B站 BV 号或 av 号。",
        )

    # 1. Fetch View API (with WBI signing)
    params = {"bvid": bvid} if bvid else {"aid": aid}
    signed_params = sign_wbi_params(params)
    try:
        resp = try_proxied_get(
            BILIBILI_VIEW_URL,
            params=signed_params,
            proxies=config.proxies,
            timeout=getattr(config, "request_timeout", 10.0),
            headers=_headers(),
        )
        payload = resp.json()
    except Exception as exc:
        logger.warning("Bilibili View API request failed: %s", exc)
        return BilibiliVideoPayload(
            ok=False,
            status="network_error",
            bvid=bvid,
            aid=aid,
            error_message="访问 B站 视频信息接口失败。",
        )

    if not isinstance(payload, dict) or payload.get("code") != 0:
        msg = payload.get("message") if isinstance(payload, dict) else "接口返回异常"
        return BilibiliVideoPayload(
            ok=False,
            status="api_error",
            bvid=bvid,
            aid=aid,
            error_message=f"B站接口错误: {msg}",
        )

    data = payload.get("data") or {}
    real_bvid = str(data.get("bvid") or bvid)
    real_aid = str(data.get("aid") or aid)
    title = str(data.get("title") or "").strip()
    desc = str(data.get("desc") or "").strip()
    duration = int(data.get("duration") or 0)
    pubdate = _format_pubdate(data.get("pubdate"))
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    owner_name = str(owner.get("name") or "").strip()
    stat = data.get("stat") if isinstance(data.get("stat"), dict) else {}
    view_count = int(stat.get("view") or 0)
    like_count = int(stat.get("like") or 0)

    pages = data.get("pages") if isinstance(data.get("pages"), list) else []
    first_page = pages[0] if pages and isinstance(pages[0], dict) else {}
    cid = first_page.get("cid") or data.get("cid")
    part_title = str(first_page.get("part") or "").strip()

    # 2. Fetch Player V2 API for subtitles (with WBI signing)
    has_subtitles = False
    subtitles_text = ""
    if cid:
        player_params: dict[str, Any] = {"cid": cid}
        if real_bvid:
            player_params["bvid"] = real_bvid
        else:
            player_params["aid"] = real_aid
        signed_player_params = sign_wbi_params(player_params)
        try:
            player_resp = try_proxied_get(
                BILIBILI_PLAYER_URL,
                params=signed_player_params,
                proxies=config.proxies,
                timeout=getattr(config, "request_timeout", 10.0),
                headers=_headers(),
            )
            player_data = player_resp.json()
            if isinstance(player_data, dict) and player_data.get("code") == 0:
                p_data = player_data.get("data") or {}
                sub_data = p_data.get("subtitle") or {}
                subtitles = sub_data.get("subtitles") or []
                if subtitles and isinstance(subtitles, list):
                    best = _best_subtitle(subtitles)
                    sub_url = str(best.get("subtitle_url") or "")
                    if sub_url:
                        subtitles_text = _download_subtitles(sub_url)
                        if subtitles_text:
                            has_subtitles = True
        except Exception as exc:
            logger.debug("Bilibili Player V2 API fetch failed: %s", exc)

    return BilibiliVideoPayload(
        ok=True,
        status="success",
        bvid=real_bvid,
        aid=real_aid,
        title=title,
        owner_name=owner_name,
        duration_seconds=duration,
        pubdate_str=pubdate,
        desc=desc,
        part_title=part_title,
        view_count=view_count,
        like_count=like_count,
        has_subtitles=has_subtitles,
        subtitles_text=subtitles_text,
    )
