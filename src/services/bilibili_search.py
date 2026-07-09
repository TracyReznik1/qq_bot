"""
Bilibili user/video search — API + HTML fallback.

Public API:
    bilibili_user_search_lines(query) -> list[str]
    bilibili_video_search_lines(query) -> list[str]
    has_exact_bilibili_user_match(query, lines) -> bool
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from src.config import config
from src.services.llm_client import get_llm_client
from src.services.search_service import format_search_failure, format_search_success
from src.util import try_proxied_get

logger = logging.getLogger("qq-bot")
BILIBILI_USER_SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
BILIBILI_SEARCH_MARKERS = (
    "b站",
    "bilibili",
    "哔哩哔哩",
    "小破站",
    "阿b",
    "阿 b",
    "up主",
    "up 主",
    "主播",
    "直播间",
    "bv号",
    "bv 号",
    "av号",
    "av 号",
    "投稿",
)
BILIBILI_BV_ID_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])BV[0-9A-Za-z]{10}(?![0-9A-Za-z])")
BILIBILI_AV_ID_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])")
BILIBILI_SHORT_LINK_PATTERN = re.compile(r"(?i)(?:https?:)?//b23\.tv/[^\s<>'\"]+")
_keyword_filter_client = get_llm_client()


@dataclass(frozen=True)
class BilibiliSearchResult:
    ok: bool
    status: str
    text: str


@dataclass(frozen=True)
class BilibiliUserItem:
    name: str
    profile_url: str
    sign: object = None
    fans: object = None
    live_room_url: str = ""
    video_title: str = ""
    video_url: str = ""


@dataclass(frozen=True)
class BilibiliVideoItem:
    title: str
    url: str
    author: str = ""
    description: str = ""
    duration: str = ""
    cover_url: str = ""
    play: object = None
    danmaku: object = None
    pubdate: object = None


def has_bilibili_search_signal(text: str) -> bool:
    value = str(text or "")
    normalized = value.casefold()
    return any(marker in normalized for marker in BILIBILI_SEARCH_MARKERS) or bool(
        BILIBILI_BV_ID_PATTERN.search(value)
        or BILIBILI_AV_ID_PATTERN.search(value)
        or BILIBILI_SHORT_LINK_PATTERN.search(value)
    )


def bilibili_keyword(query: str) -> str:
    keyword = str(query or "")
    keyword = re.sub(r"(?i)^\s*/(?:bfuser|buser|bfu|bu|bfsearch|bsearch|bfs|bs)\b", " ", keyword, count=1)
    keyword = re.sub(r"(?:https?:)?//(?:www\.|m\.)?bilibili\.com/video/([A-Za-z0-9]+).*", r"\1", keyword)
    keyword = re.sub(
        r"(?i)(?:https?:)?//(?:space\.bilibili\.com|(?:www\.|m\.)?bilibili\.com/space)/(\d+).*",
        r"\1",
        keyword,
    )
    keyword = re.sub(r"(?i)(?:https?:)?//b23\.tv/([^\s<>'\"]+)", r"https://b23.tv/\1", keyword)
    keyword = re.sub(r"(?i)bilibili", " ", keyword)
    keyword = re.sub(
        r"(?i)(哔哩哔哩|小破站|阿\s*B|B\s*站用户|B\s*站视频|B\s*站|UP\s*主|主播|直播间)",
        " ",
        keyword,
    )
    keyword = re.sub(
        r"(这个人|那个人|是谁|是什么|什么意思|什么梗|你认识吗|资料|简介|搜索|查一下|帮我找|找一下)",
        " ",
        keyword,
    )
    keyword = re.sub(r"[@#：:，,。！？!?]+", " ", keyword)
    keyword = re.sub(r"(?i)\bhttps\s+//b23\.tv/([^\s<>'\"]+)", r"https://b23.tv/\1", keyword)
    keyword = " ".join(keyword.split()).strip()
    return keyword or str(query or "").strip()


def bilibili_video_keyword(query: str) -> str:
    keyword = bilibili_keyword(query)
    keyword = re.sub(r"(?i)^\s*/?(?:bfvideo|bvideo|bfv|bv)\b", " ", keyword, count=1)
    keyword = re.sub(r"(搜索视频|搜视频|找视频|视频|这个视频|那个视频|投稿)", " ", keyword)
    keyword = " ".join(keyword.split()).strip()
    return keyword or bilibili_keyword(query)


def _sanitize_llm_keyword(value: str) -> str:
    keyword = _clean_html(str(value or ""))
    keyword = re.sub(r"^(关键词|搜索关键词|keyword)\s*[:：]\s*", "", keyword, flags=re.I)
    keyword = keyword.strip().strip("\"'`“”‘’")
    keyword = " ".join(keyword.split()).strip()
    if not keyword or len(keyword) > 80 or "\n" in keyword:
        return ""
    return keyword


def filter_bilibili_search_keyword(query: str, kind: str) -> str:
    fallback = bilibili_video_keyword(query) if kind == "video" else bilibili_keyword(query)
    if not fallback:
        return ""
    try:
        response = _keyword_filter_client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你只负责把用户原话改写成B站搜索关键词。只输出关键词，不要解释。"
                        "去掉命令名、寒暄、提问语气、'B站'、'视频'、'UP主'等噪声词，"
                        "保留作品名、人名、UP名、BV号、av号、主题词。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"搜索类型：{kind}\n用户原话：{query}\n本地兜底关键词：{fallback}",
                },
            ],
            temperature=0,
            max_tokens=32,
        )
    except Exception:
        logger.debug("Bilibili keyword LLM filter failed", exc_info=True)
        return fallback
    keyword = _sanitize_llm_keyword(response.content)
    return keyword or fallback


def _bilibili_headers(referer: str, accept: str = "application/json, text/plain, */*") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _bilibili_user_item(result: dict) -> BilibiliUserItem | None:
    uname = _clean_html(str(result.get("uname") or "").strip())
    if not uname:
        return None
    mid = str(result.get("mid") or "").strip()
    room_id = str(result.get("room_id") or "").strip()
    live_room_url = f"https://live.bilibili.com/{room_id}" if room_id else ""
    videos = result.get("res")
    first_video = videos[0] if isinstance(videos, list) and videos and isinstance(videos[0], dict) else {}
    return BilibiliUserItem(
        name=uname,
        profile_url=f"https://space.bilibili.com/{mid}" if mid else "https://www.bilibili.com",
        sign=_clean_html(str(result.get("usign") or "").strip()),
        fans=result.get("fans"),
        live_room_url=live_room_url,
        video_title=_clean_html(str(first_video.get("title") or "").strip()),
        video_url=_absolute_url(first_video.get("arcurl")),
    )


def _format_bilibili_user_item(item: BilibiliUserItem) -> str:
    details = []
    if item.sign:
        details.append(f"签名：{item.sign}")
    if item.fans is not None:
        details.append(f"粉丝：{_format_fans(item.fans)}")
    if item.live_room_url:
        details.append(f"直播间：{item.live_room_url}")
    if item.video_title:
        details.append(f"代表视频：{item.video_title}")
    if item.video_url:
        details.append(f"视频链接：{item.video_url}")
    body = "；".join(details) if details else "B站用户搜索结果。"
    return f"B站用户：{item.name}\n摘要：{body}\n链接：{item.profile_url}"


def _format_fans(value: object) -> str:
    return _format_chinese_count(value)


def _format_chinese_count(value: object) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return str(value)
    if count < 10000:
        return str(count)
    text = f"{count / 10000:.1f}".rstrip("0").rstrip(".")
    return f"{text}万"


def bilibili_user_search_lines(query: str) -> list[str]:
    keyword = str(query or "").strip()
    return _bilibili_user_search_lines_for_keyword(keyword)


def bilibili_filtered_user_search_lines(query: str) -> list[str]:
    keyword = filter_bilibili_search_keyword(query, "user")
    return _bilibili_user_search_lines_for_keyword(keyword)


def _bilibili_user_search_lines_for_keyword(keyword: str) -> list[str]:
    if not keyword:
        return []

    try:
        response = try_proxied_get(
            BILIBILI_USER_SEARCH_URL,
            params={"search_type": "bili_user", "keyword": keyword},
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_bilibili_headers("https://search.bilibili.com/"),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.debug("Bilibili API search failed; falling back to HTML search")
        return bilibili_user_html_search_lines(keyword)

    if payload.get("code") != 0:
        return bilibili_user_html_search_lines(keyword)

    data = payload.get("data") if isinstance(payload, dict) else {}
    results = data.get("result") if isinstance(data, dict) else []
    if not isinstance(results, list):
        return []

    lines = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = _bilibili_user_item(result)
        if item is None:
            continue
        lines.append(_format_bilibili_user_item(item))
        if len(lines) >= 2:
            break
    return lines


def _format_count(value: object) -> str:
    if value is None or value == "":
        return ""
    return _format_chinese_count(value)


def _video_url(item: dict) -> str:
    arcurl = str(item.get("arcurl") or "").strip()
    if arcurl:
        return _absolute_url(arcurl)
    bvid = str(item.get("bvid") or "").strip()
    if bvid:
        return f"https://www.bilibili.com/video/{bvid}"
    aid = str(item.get("aid") or "").strip()
    if aid:
        return f"https://www.bilibili.com/video/av{aid}"
    return "https://www.bilibili.com"


def _absolute_url(value: object) -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    return url


def _video_url_from_href(href: str) -> str:
    href = html.unescape(str(href or "").strip())
    bvid = re.search(r"(BV[0-9A-Za-z]+)", href)
    if bvid:
        return f"https://www.bilibili.com/video/{bvid.group(1)}"
    aid = re.search(r"/video/(av\d+)", href, flags=re.I)
    if aid:
        return f"https://www.bilibili.com/video/{aid.group(1)}"
    return ""


def _format_pubdate(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def _bilibili_video_item(result: dict) -> BilibiliVideoItem | None:
    title = _clean_html(str(result.get("title") or "").strip())
    if not title:
        return None
    return BilibiliVideoItem(
        title=title,
        url=_video_url(result),
        author=_clean_html(str(result.get("author") or "").strip()),
        description=_clean_html(str(result.get("description") or "").strip()),
        duration=str(result.get("duration") or "").strip(),
        cover_url=_absolute_url(result.get("pic") or result.get("cover")),
        play=result.get("play"),
        danmaku=result.get("danmaku"),
        pubdate=result.get("pubdate"),
    )


def _format_bilibili_video_item(item: BilibiliVideoItem) -> str:
    details = []
    if item.author:
        details.append(f"UP主：{item.author}")
    if item.duration:
        details.append(f"时长：{item.duration}")
    play = _format_count(item.play)
    if play:
        details.append(f"播放：{play}")
    danmaku = _format_count(item.danmaku)
    if danmaku:
        details.append(f"弹幕：{danmaku}")
    pubdate = _format_pubdate(item.pubdate)
    if pubdate:
        details.append(f"发布时间：{pubdate}")
    if item.cover_url:
        details.append(f"封面：{item.cover_url}")
    if item.description:
        details.append(f"简介：{item.description}")
    body = "；".join(details) if details else "B站视频搜索结果。"
    return f"B站视频：{item.title}\n摘要：{body}\n链接：{item.url}"


def _direct_video_id_lines(keyword: str) -> list[str]:
    value = str(keyword or "")
    bv_match = BILIBILI_BV_ID_PATTERN.search(value)
    if bv_match:
        bvid = "BV" + bv_match.group(0)[2:]
        return [
            _format_bilibili_video_item(
                BilibiliVideoItem(
                    title=bvid,
                    url=f"https://www.bilibili.com/video/{bvid}",
                )
            )
        ]
    av_match = BILIBILI_AV_ID_PATTERN.search(value)
    if not av_match:
        return []
    avid = f"av{av_match.group(1)}"
    return [
        _format_bilibili_video_item(
            BilibiliVideoItem(
                title=avid,
                url=f"https://www.bilibili.com/video/{avid}",
            )
        )
    ]


def _resolve_bilibili_short_video_lines(keyword: str) -> list[str]:
    match = BILIBILI_SHORT_LINK_PATTERN.search(str(keyword or ""))
    if not match:
        return []
    short_url = _absolute_url(match.group(0).rstrip(".,，。！？!?)）]】"))
    try:
        response = try_proxied_get(
            short_url,
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_bilibili_headers(
                "https://www.bilibili.com/",
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            ),
        )
        response.raise_for_status()
    except Exception:
        logger.debug("Bilibili short link resolve failed")
        return []
    return _direct_video_id_lines(getattr(response, "url", ""))


def _html_attr(tag: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*(['\"])(.*?)\1", tag, flags=re.I | re.S)
    if not match:
        return ""
    return html.unescape(match.group(2)).strip()


def _context_author(context: str) -> str:
    for match in re.finditer(r"<a\b(?P<tag>[^>]*)>(?P<body>.*?)</a>", context, flags=re.I | re.S):
        tag = match.group("tag")
        href = _html_attr(tag, "href")
        class_name = _html_attr(tag, "class").casefold()
        if "space.bilibili.com" not in href and not any(marker in class_name for marker in ("up", "author")):
            continue
        author = _clean_html(match.group("body"))
        if author:
            return author
    return ""


def _context_description(context: str) -> str:
    for match in re.finditer(r"<p\b(?P<tag>[^>]*)>", context, flags=re.I | re.S):
        tag = match.group("tag")
        class_name = _html_attr(tag, "class").casefold()
        title = _html_attr(tag, "title")
        if title and (
            not class_name
            or any(marker in class_name for marker in ("des", "desc", "summary", "b_text", "text2"))
        ):
            return _clean_html(title)
    return ""


def bilibili_video_html_search_lines(keyword: str) -> list[str]:
    keyword = str(keyword or "").strip()
    if not keyword:
        return []

    try:
        response = try_proxied_get(
            "https://search.bilibili.com/video",
            params={"keyword": keyword},
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_bilibili_headers(
                "https://www.bilibili.com/",
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            ),
        )
        response.raise_for_status()
    except Exception:
        logger.debug("Bilibili video HTML search failed")
        return []

    lines = []
    seen_urls: set[str] = set()
    text = response.text
    for match in re.finditer(r"<a\b(?P<tag>[^>]*)>(?P<body>.*?)</a>", text, flags=re.I | re.S):
        tag = match.group("tag")
        href = _html_attr(tag, "href")
        if "/video/" not in href:
            continue
        url = _video_url_from_href(href)
        if not url or url in seen_urls:
            continue
        title = _clean_html(match.group("body")) or _clean_html(_html_attr(tag, "title"))
        if not title:
            continue
        context = text[match.start() : match.start() + 2000]
        lines.append(
            _format_bilibili_video_item(
                BilibiliVideoItem(
                    title=title,
                    url=url,
                    author=_context_author(context),
                    description=_context_description(context),
                )
            )
        )
        seen_urls.add(url)
        if len(lines) >= 3:
            break
    return lines


def bilibili_video_search_lines(query: str) -> list[str]:
    keyword = str(query or "").strip()
    return _bilibili_video_search_lines_for_keyword(keyword)


def bilibili_filtered_video_search_lines(query: str) -> list[str]:
    keyword = filter_bilibili_search_keyword(query, "video")
    return _bilibili_video_search_lines_for_keyword(keyword)


def _bilibili_video_search_lines_for_keyword(keyword: str) -> list[str]:
    if not keyword:
        return []

    short_link_lines = _resolve_bilibili_short_video_lines(keyword)
    if short_link_lines:
        return short_link_lines

    try:
        response = try_proxied_get(
            BILIBILI_USER_SEARCH_URL,
            params={"search_type": "video", "keyword": keyword},
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_bilibili_headers("https://search.bilibili.com/"),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.debug("Bilibili video API search failed; falling back to HTML search")
        return bilibili_video_html_search_lines(keyword) or _direct_video_id_lines(keyword)

    if not isinstance(payload, dict) or payload.get("code") != 0:
        return bilibili_video_html_search_lines(keyword) or _direct_video_id_lines(keyword)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    results = data.get("result") if isinstance(data, dict) else []
    if not isinstance(results, list):
        return _direct_video_id_lines(keyword)

    lines = []
    for result in results:
        if not isinstance(result, dict):
            continue
        item = _bilibili_video_item(result)
        if item is None:
            continue
        lines.append(_format_bilibili_video_item(item))
        if len(lines) >= 3:
            break
    return lines or _direct_video_id_lines(keyword)


def search_bilibili_users(query: str) -> BilibiliSearchResult:
    query = query.strip()
    if not query:
        return BilibiliSearchResult(
            ok=False,
            status="empty_query",
            text=format_search_failure("bilibili_user", "empty_query", query, "没有可搜索的 B站用户关键词。"),
        )

    lines = bilibili_user_search_lines(query)
    if not lines:
        return BilibiliSearchResult(
            ok=False,
            status="no_results",
            text=format_search_failure("bilibili_user", "no_results", query, "没有搜到匹配的 B站用户。"),
        )
    return BilibiliSearchResult(ok=True, status="success", text=format_search_success("bilibili_user", query, lines))


def bilibili_user_search(query: str) -> str:
    return search_filtered_bilibili_users(query).text


def search_bilibili_videos(query: str) -> BilibiliSearchResult:
    query = query.strip()
    if not query:
        return BilibiliSearchResult(
            ok=False,
            status="empty_query",
            text=format_search_failure("bilibili_video", "empty_query", query, "没有可搜索的 B站视频关键词。"),
        )

    lines = bilibili_video_search_lines(query)
    if not lines:
        return BilibiliSearchResult(
            ok=False,
            status="no_results",
            text=format_search_failure("bilibili_video", "no_results", query, "没有搜到匹配的 B站视频。"),
        )
    return BilibiliSearchResult(ok=True, status="success", text=format_search_success("bilibili_video", query, lines))


def search_filtered_bilibili_users(query: str) -> BilibiliSearchResult:
    query = query.strip()
    if not query:
        return BilibiliSearchResult(
            ok=False,
            status="empty_query",
            text=format_search_failure("bilibili_user", "empty_query", query, "没有可搜索的 B站用户关键词。"),
        )

    keyword = filter_bilibili_search_keyword(query, "user")
    if not keyword:
        return BilibiliSearchResult(
            ok=False,
            status="empty_query",
            text=format_search_failure("bilibili_user", "empty_query", keyword, "没有可搜索的 B站用户关键词。"),
        )
    lines = _bilibili_user_search_lines_for_keyword(keyword)
    if not lines:
        return BilibiliSearchResult(
            ok=False,
            status="no_results",
            text=format_search_failure("bilibili_user", "no_results", keyword, "没有搜到匹配的 B站用户。"),
        )
    return BilibiliSearchResult(ok=True, status="success", text=format_search_success("bilibili_user", keyword, lines))


def search_filtered_bilibili_videos(query: str) -> BilibiliSearchResult:
    query = query.strip()
    if not query:
        return BilibiliSearchResult(
            ok=False,
            status="empty_query",
            text=format_search_failure("bilibili_video", "empty_query", query, "没有可搜索的 B站视频关键词。"),
        )

    keyword = filter_bilibili_search_keyword(query, "video")
    if not keyword:
        return BilibiliSearchResult(
            ok=False,
            status="empty_query",
            text=format_search_failure("bilibili_video", "empty_query", keyword, "没有可搜索的 B站视频关键词。"),
        )
    lines = _bilibili_video_search_lines_for_keyword(keyword)
    if not lines:
        return BilibiliSearchResult(
            ok=False,
            status="no_results",
            text=format_search_failure("bilibili_video", "no_results", keyword, "没有搜到匹配的 B站视频。"),
        )
    return BilibiliSearchResult(ok=True, status="success", text=format_search_success("bilibili_video", keyword, lines))


def bilibili_video_search(query: str) -> str:
    return search_filtered_bilibili_videos(query).text


def bilibili_user_html_search_lines(keyword: str) -> list[str]:
    try:
        response = try_proxied_get(
            "https://search.bilibili.com/upuser",
            params={"keyword": keyword},
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_bilibili_headers(
                "https://www.bilibili.com/",
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            ),
        )
        response.raise_for_status()
    except Exception:
        logger.debug("Bilibili HTML search failed")
        return []

    text = response.text
    lines = []
    seen_mids: set[str] = set()
    for match in re.finditer(r"<a\b(?P<tag>[^>]*)>(?P<body>.*?)</a>", text, flags=re.I | re.S):
        tag = match.group("tag")
        href = _html_attr(tag, "href")
        mid_match = re.search(r"space\.bilibili\.com/(\d+)", href, flags=re.I)
        if not mid_match:
            continue
        mid = mid_match.group(1)
        if mid in seen_mids:
            continue
        name = _clean_html(_html_attr(tag, "title") or match.group("body"))
        if not name:
            continue
        context = text[match.start() : match.start() + 3000]
        desc = _context_description(context)
        body = desc or "B站用户搜索结果。"
        lines.append(
            f"B站用户：{name}\n摘要：{body}\n链接：https://space.bilibili.com/{mid}"
        )
        seen_mids.add(mid)
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
