import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from src.config import config
from src.services.url_fetch_service import extract_first_url, fetch_url
from src.util import try_proxied_get


logger = logging.getLogger("qq-bot")

BILIBILI_VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
BILIBILI_PLAYER_URL = "https://api.bilibili.com/x/player/v2"
BILIBILI_BV_ID_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])BV[0-9A-Za-z]{10}(?![0-9A-Za-z])")
BILIBILI_AV_ID_PATTERN = re.compile(r"(?i)(?<![0-9A-Za-z])av(\d+)(?![0-9A-Za-z])")
BILIBILI_SHORT_LINK_PATTERN = re.compile(r"(?i)https?://b23\.tv/[^\s<>'\"]+")
DIRECT_MEDIA_EXTENSIONS = (".mp4", ".m3u8", ".mov", ".mkv", ".webm", ".avi", ".flv")
MEDIA_PIPELINE_PLAN = "受控下载或截取视频片段 -> 音频 ASR 转写 -> 抽取关键帧 -> 多模态总结"
VIDEO_PAGE_DOMAINS = (
    "bilibili.com",
    "b23.tv",
    "youtube.com",
    "youtu.be",
    "douyin.com",
    "ixigua.com",
    "v.qq.com",
    "youku.com",
    "tudou.com",
    "acfun.cn",
)
TEXT_LIMIT = 4000


@dataclass(frozen=True)
class VideoUnderstandingResult:
    ok: bool
    status: str
    text: str


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _truncate_text(text: str, limit: int = TEXT_LIMIT) -> str:
    text = _collapse_spaces(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip("，,。；;：:") + "..."


def _absolute_url(value: object, base: str = "https://www.bilibili.com") -> str:
    url = str(value or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return base.rstrip("/") + url
    return url


def _line_value(text: str, label: str) -> str:
    prefix = f"{label}："
    for line in str(text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _section_after(text: str, marker: str) -> str:
    raw_text = str(text or "")
    if marker not in raw_text:
        return ""
    return _truncate_text(raw_text.split(marker, 1)[1])


def _format_pubdate(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def _format_duration(seconds: object) -> str:
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        return str(seconds or "")
    minutes, second = divmod(value, 60)
    hour, minute = divmod(minutes, 60)
    if hour:
        return f"{hour}:{minute:02d}:{second:02d}"
    return f"{minute}:{second:02d}"


def _format_count(value: object) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return str(value or "")
    if count < 10000:
        return str(count)
    text = f"{count / 10000:.1f}".rstrip("0").rstrip(".")
    return f"{text}万"


def _headers(referer: str = "https://www.bilibili.com/") -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def extract_video_url(text: str) -> str:
    return extract_first_url(text)


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_bilibili_url(url: str) -> bool:
    host = _hostname(url)
    return host == "b23.tv" or host.endswith("bilibili.com")


def _is_direct_media_url(url: str) -> bool:
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return False
    return path.endswith(DIRECT_MEDIA_EXTENSIONS)


def _is_likely_video_page(url: str) -> bool:
    host = _hostname(url)
    if not host:
        return False
    if host.startswith("video.") or any(host == domain or host.endswith(f".{domain}") for domain in VIDEO_PAGE_DOMAINS):
        return True
    try:
        path = urlparse(url).path.lower()
    except ValueError:
        return False
    return any(marker in path for marker in ("/video/", "/watch/", "/play/", "/v/"))


def has_video_url(text: str) -> bool:
    if BILIBILI_BV_ID_PATTERN.search(str(text or "")) or BILIBILI_AV_ID_PATTERN.search(str(text or "")):
        return True
    url = extract_video_url(text)
    return bool(url and (_is_direct_media_url(url) or _is_bilibili_url(url) or _is_likely_video_page(url)))


def _format_failure(video_type: str, status: str, url: str, message: str) -> str:
    return (
        f"视频理解状态：{status}\n"
        f"视频类型：{video_type}\n"
        f"URL：{url or '无'}\n"
        f"说明：{message}"
    )


def _config_int(name: str, default: int) -> int:
    try:
        return int(getattr(config, name, default))
    except (TypeError, ValueError):
        return default


def _format_media_pipeline_unavailable(url: str) -> str:
    enabled = bool(getattr(config, "video_enable_media_pipeline", False))
    has_openai_key = bool(str(getattr(config, "openai_api_key", "") or "").strip())
    ffmpeg_available = bool(shutil.which("ffmpeg"))
    ytdlp_available = bool(shutil.which("yt-dlp"))
    max_seconds = _config_int("video_max_seconds", 600)
    max_download_mb = _config_int("video_max_download_mb", 50)

    missing = []
    if not enabled:
        missing.append("VIDEO_ENABLE_MEDIA_PIPELINE=true")
    if not ffmpeg_available:
        missing.append("ffmpeg")
    if not has_openai_key:
        missing.append("OPENAI_API_KEY")

    missing_text = "；".join(missing) if missing else "实际转写/抽帧执行器"
    return "\n".join(
        [
            "视频理解状态：media_pipeline_unavailable",
            "视频类型：direct_media",
            f"URL：{url}",
            f"媒体处理计划：{MEDIA_PIPELINE_PLAN}",
            f"安全限制：最多 {max_seconds} 秒；最多 {max_download_mb} MB",
            (
                "能力探测："
                f"VIDEO_ENABLE_MEDIA_PIPELINE={'true' if enabled else 'false'}；"
                f"ffmpeg={'available' if ffmpeg_available else 'missing'}；"
                f"yt-dlp={'available' if ytdlp_available else 'missing'}；"
                f"OPENAI_API_KEY={'configured' if has_openai_key else 'missing'}"
            ),
            f"缺少能力：{missing_text}",
            "说明：当前没有执行下载、转写或抽帧；因此不能总结视频画面或声音。",
        ]
    )


def _resolve_b23_url(url: str) -> str:
    if _hostname(url) != "b23.tv":
        return url
    try:
        response = try_proxied_get(
            url,
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_headers(),
            allow_redirects=True,
        )
        response.raise_for_status()
        return str(getattr(response, "url", "") or url)
    except Exception:
        logger.debug("Bilibili short video URL resolve failed", exc_info=True)
        return url


def _bilibili_ids(text: str) -> tuple[str, str, str]:
    value = str(text or "")
    url = extract_video_url(value)
    if url:
        url = _resolve_b23_url(url)
        value = f"{value} {url}"
    bv_match = BILIBILI_BV_ID_PATTERN.search(value)
    if bv_match:
        bvid = "BV" + bv_match.group(0)[2:]
        return bvid, "", f"https://www.bilibili.com/video/{bvid}"
    av_match = BILIBILI_AV_ID_PATTERN.search(value)
    if av_match:
        avid = av_match.group(1)
        return "", avid, f"https://www.bilibili.com/video/av{avid}"
    return "", "", url


def _fetch_bilibili_view(bvid: str, aid: str) -> dict:
    params = {"bvid": bvid} if bvid else {"aid": aid}
    response = try_proxied_get(
        BILIBILI_VIEW_URL,
        params=params,
        proxies=config.proxies,
        timeout=config.request_timeout,
        headers=_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError("bilibili view response is not successful")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("bilibili view response has no data")
    return data


def _fetch_bilibili_player(bvid: str, aid: str, cid: object) -> dict:
    if not cid:
        return {}
    params = {"cid": cid}
    if bvid:
        params["bvid"] = bvid
    elif aid:
        params["aid"] = aid
    else:
        return {}
    response = try_proxied_get(
        BILIBILI_PLAYER_URL,
        params=params,
        proxies=config.proxies,
        timeout=config.request_timeout,
        headers=_headers(),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def _best_subtitle(subtitles: list[dict]) -> dict:
    if not subtitles:
        return {}
    for preferred in ("zh-CN", "zh-Hans", "ai-zh"):
        for item in subtitles:
            if str(item.get("lan") or "").casefold() == preferred.casefold():
                return item
    return subtitles[0]


def _fetch_subtitle_text(player_data: dict) -> tuple[str, str]:
    subtitle_data = player_data.get("subtitle") if isinstance(player_data, dict) else {}
    subtitles = subtitle_data.get("subtitles") if isinstance(subtitle_data, dict) else []
    if not isinstance(subtitles, list) or not subtitles:
        return "no_subtitle", ""

    subtitle = _best_subtitle([item for item in subtitles if isinstance(item, dict)])
    subtitle_url = _absolute_url(subtitle.get("subtitle_url") or "")
    if not subtitle_url:
        return "no_subtitle", ""
    try:
        response = try_proxied_get(
            subtitle_url,
            proxies=config.proxies,
            timeout=config.request_timeout,
            headers=_headers("https://www.bilibili.com/"),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.debug("Bilibili subtitle fetch failed", exc_info=True)
        return "subtitle_error", ""

    body = payload.get("body") if isinstance(payload, dict) else []
    if not isinstance(body, list):
        return "subtitle_error", ""
    lines = []
    for item in body:
        if not isinstance(item, dict):
            continue
        content = _collapse_spaces(item.get("content") or "")
        if content:
            lines.append(content)
    if not lines:
        return "no_subtitle", ""
    return "success", _truncate_text(" ".join(lines))


def _understand_bilibili_video(text: str) -> VideoUnderstandingResult:
    bvid, aid, url = _bilibili_ids(text)
    if not bvid and not aid:
        return VideoUnderstandingResult(
            ok=False,
            status="invalid_video_url",
            text=_format_failure("bilibili", "invalid_video_url", url, "没有识别到 B站 BV/av 视频号。"),
        )

    try:
        data = _fetch_bilibili_view(bvid, aid)
    except Exception:
        logger.debug("Bilibili video metadata fetch failed", exc_info=True)
        return VideoUnderstandingResult(
            ok=False,
            status="metadata_error",
            text=_format_failure("bilibili", "metadata_error", url, "B站视频信息读取失败。"),
        )

    bvid = str(data.get("bvid") or bvid)
    aid = str(data.get("aid") or aid)
    url = f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://www.bilibili.com/video/av{aid}"
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    stat = data.get("stat") if isinstance(data.get("stat"), dict) else {}
    pages = data.get("pages") if isinstance(data.get("pages"), list) else []
    first_page = pages[0] if pages and isinstance(pages[0], dict) else {}
    cid = first_page.get("cid") or data.get("cid")

    player_data = {}
    try:
        player_data = _fetch_bilibili_player(bvid, aid, cid)
    except Exception:
        logger.debug("Bilibili player metadata fetch failed", exc_info=True)
    subtitle_status, subtitle_text = _fetch_subtitle_text(player_data) if player_data else ("no_subtitle", "")

    lines = [
        "视频理解状态：success",
        "视频类型：bilibili",
        f"URL：{url}",
        f"标题：{_collapse_spaces(data.get('title') or '无标题')}",
    ]
    owner_name = _collapse_spaces(owner.get("name") or "")
    if owner_name:
        lines.append(f"UP主：{owner_name}")
    duration = _format_duration(data.get("duration"))
    if duration:
        lines.append(f"时长：{duration}")
    pubdate = _format_pubdate(data.get("pubdate"))
    if pubdate:
        lines.append(f"发布时间：{pubdate}")
    for label, key in (("播放", "view"), ("弹幕", "danmaku"), ("点赞", "like")):
        value = _format_count(stat.get(key))
        if value:
            lines.append(f"{label}：{value}")
    desc = _truncate_text(data.get("desc") or "", 1200)
    if desc:
        lines.append(f"简介：{desc}")
    part = _collapse_spaces(first_page.get("part") or "")
    if part:
        lines.append(f"分P：{part}")
    lines.append(f"字幕状态：{subtitle_status}")
    if subtitle_text:
        lines.append(f"字幕摘录：{subtitle_text}")
    lines.append("能力边界：当前结果基于视频页面信息和可用字幕，不包含逐帧画面理解或音频 ASR。")
    return VideoUnderstandingResult(ok=True, status="success", text="\n".join(lines))


def _understand_generic_video_page(url: str) -> VideoUnderstandingResult:
    result = fetch_url(url)
    text = str(getattr(result, "text", "") or "")
    if not getattr(result, "ok", False):
        return VideoUnderstandingResult(
            ok=False,
            status=str(getattr(result, "status", "") or "page_error"),
            text=_format_failure("generic_page", str(getattr(result, "status", "") or "page_error"), url, "视频页文字信息读取失败。"),
        )
    title = _line_value(text, "标题") or "无标题"
    excerpt = _section_after(text, "正文摘录：")
    lines = [
        "视频理解状态：success",
        "视频类型：generic_page",
        f"URL：{url}",
        f"标题：{title}",
        "字幕状态：not_available",
    ]
    if excerpt:
        lines.append(f"页面文字摘录：{excerpt}")
    lines.append("能力边界：当前只读取视频页文字信息，没有读取视频画面、音频或字幕。")
    return VideoUnderstandingResult(ok=True, status="success", text="\n".join(lines))


def understand_video(text: str) -> VideoUnderstandingResult:
    raw_text = str(text or "")
    url = extract_video_url(raw_text)
    if url and _is_direct_media_url(url):
        return VideoUnderstandingResult(
            ok=False,
            status="media_pipeline_unavailable",
            text=_format_media_pipeline_unavailable(url),
        )
    if _is_bilibili_url(url) or BILIBILI_BV_ID_PATTERN.search(raw_text) or BILIBILI_AV_ID_PATTERN.search(raw_text):
        return _understand_bilibili_video(raw_text)
    if url and _is_likely_video_page(url):
        return _understand_generic_video_page(url)
    if not url:
        return VideoUnderstandingResult(
            ok=False,
            status="empty_url",
            text=_format_failure("unknown", "empty_url", "", "没有找到视频 URL。"),
        )
    return VideoUnderstandingResult(
        ok=False,
        status="unsupported_platform",
        text=_format_failure("unknown", "unsupported_platform", url, "暂不支持这个视频平台；可以先用 /url 读取网页文字。"),
    )


def video_understanding(text: str) -> str:
    return understand_video(text).text
