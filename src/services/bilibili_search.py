"""
Bilibili user search — API + HTML fallback.

Public API:
    bilibili_user_search_lines(query) -> list[str]
    has_exact_bilibili_user_match(query, lines) -> bool
"""

import html
import logging
import re
from dataclasses import dataclass

from src.config import config
from src.util import try_proxied_get

logger = logging.getLogger("qq-bot")
BILIBILI_USER_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
BILIBILI_SEARCH_MARKERS = ("b站", "bilibili", "哔哩哔哩", "up主", "up 主", "主播", "直播间")


@dataclass(frozen=True)
class BilibiliSearchResult:
    ok: bool
    status: str
    text: str


def has_bilibili_search_signal(text: str) -> bool:
    normalized = str(text or "").casefold()
    return any(marker in normalized for marker in BILIBILI_SEARCH_MARKERS)


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[一-鿿]", text))


def bilibili_keyword(query: str) -> str:
    keyword = re.sub(r"(?i)\b(bilibili|b站|up主|主播)\b", " ", query)
    keyword = re.sub(r"(是谁|是什么|什么意思|什么梗|你认识吗|资料|简介)", " ", keyword)
    keyword = " ".join(keyword.split()).strip()
    return keyword or query.strip()


def bilibili_user_search_lines(query: str) -> list[str]:
    keyword = bilibili_keyword(query)
    if not has_cjk(keyword):
        return []

    try:
        response = try_proxied_get(
            BILIBILI_USER_SEARCH_URL,
            params={"search_type": "bili_user", "keyword": keyword},
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://search.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.debug("Bilibili API search failed; falling back to HTML search")
        return bilibili_user_html_search_lines(keyword)

    if payload.get("code") != 0:
        return []

    data = payload.get("data") if isinstance(payload, dict) else {}
    results = data.get("result") if isinstance(data, dict) else []
    if not isinstance(results, list):
        return []

    lines = []
    for result in results[:2]:
        if not isinstance(result, dict):
            continue
        uname = str(result.get("uname") or "").strip()
        if not uname:
            continue
        mid = str(result.get("mid") or "").strip()
        sign = str(result.get("usign") or "").strip()
        fans = result.get("fans")
        room_id = result.get("room_id")
        link = f"https://space.bilibili.com/{mid}" if mid else "https://www.bilibili.com"

        details = []
        if sign:
            details.append(f"签名：{sign}")
        if fans is not None:
            details.append(f"粉丝：{fans}")
        if room_id:
            details.append(f"直播间：https://live.bilibili.com/{room_id}")

        videos = result.get("res")
        if isinstance(videos, list) and videos:
            first_video = videos[0] if isinstance(videos[0], dict) else {}
            title = str(first_video.get("title") or "").strip()
            arcurl = str(first_video.get("arcurl") or "").strip()
            if title:
                details.append(f"代表视频：{title}")
            if arcurl:
                details.append(f"视频链接：{arcurl}")

        body = "；".join(details) if details else "B站用户搜索结果。"
        lines.append(f"B站用户：{uname}\n摘要：{body}\n链接：{link}")
    return lines


def search_bilibili_users(query: str) -> BilibiliSearchResult:
    query = query.strip()
    if not query:
        return BilibiliSearchResult(ok=False, status="empty_query", text="没有可搜索的 B站用户关键词。")

    lines = bilibili_user_search_lines(query)
    if not lines:
        return BilibiliSearchResult(ok=False, status="no_results", text="没有搜到匹配的 B站用户。")
    return BilibiliSearchResult(ok=True, status="success", text="\n\n".join(lines))


def bilibili_user_search(query: str) -> str:
    return search_bilibili_users(query).text


def bilibili_user_html_search_lines(keyword: str) -> list[str]:
    try:
        response = try_proxied_get(
            "https://search.bilibili.com/upuser",
            params={"keyword": keyword},
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()
    except Exception:
        logger.debug("Bilibili HTML search failed")
        return []

    text = response.text
    pattern = re.compile(
        r'<a[^>]+href="//space\.bilibili\.com/(?P<mid>\d+)"[^>]+title="(?P<name>[^"]+)"[^>]*>.*?</a>'
        r'.{0,3000}?<p[^>]+title="(?P<desc>[^"]*)"',
        re.S,
    )
    lines = []
    for match in pattern.finditer(text):
        name = _clean_html(match.group("name"))
        mid = match.group("mid")
        desc = _clean_html(match.group("desc"))
        if not name:
            continue
        body = desc or "B站用户搜索结果。"
        lines.append(
            f"B站用户：{name}\n摘要：{body}\n链接：https://space.bilibili.com/{mid}"
        )
        if len(lines) >= 2:
            break
    return lines


def _clean_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    return " ".join(html.unescape(value).split())


def has_exact_bilibili_user_match(query: str, lines: list[str]) -> bool:
    keyword = bilibili_keyword(query).casefold()
    if not keyword or not lines:
        return False
    prefix = f"B站用户：{keyword}\n".casefold()
    return any(line.casefold().startswith(prefix) for line in lines)
