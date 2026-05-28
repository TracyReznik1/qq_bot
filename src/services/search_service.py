import logging
from dataclasses import dataclass

from src.config import config

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None


logger = logging.getLogger("qq-bot")


@dataclass(frozen=True)
class SearchResult:
    ok: bool
    status: str
    text: str


def search(query: str) -> SearchResult:
    query = query.strip()
    if not query:
        return SearchResult(ok=False, status="empty_query", text="没有可搜索的关键词。")
    if DDGS is None:
        return SearchResult(ok=False, status="missing_dependency", text="网页搜索组件 ddgs 没有安装。")

    try:
        with DDGS(proxy=config.proxy_url or None, timeout=config.request_timeout) as ddgs:
            results = list(ddgs.text(query, max_results=config.search_max_results))
    except Exception:
        logger.exception("Web search failed")
        return SearchResult(ok=False, status="request_error", text="网页搜索失败，可能是网络或代理暂时不可用。")

    if not results:
        return SearchResult(ok=False, status="no_results", text="没有搜到有用结果。")

    lines = []
    for index, result in enumerate(results, 1):
        title = result.get("title") or "无标题"
        body = result.get("body") or ""
        href = result.get("href") or result.get("url") or ""
        lines.append(f"{index}. {title}\n摘要：{body}\n链接：{href}")
    return SearchResult(ok=True, status="success", text="\n\n".join(lines))


def web_search(query: str) -> str:
    return search(query).text


def has_search_results(search_result: SearchResult) -> bool:
    return search_result.ok
