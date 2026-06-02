import logging
from dataclasses import dataclass

from src.config import config

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

logger = logging.getLogger("qq-bot")


@dataclass(frozen=True)
class SearchResult:
    ok: bool
    status: str
    text: str


def _tavily_search(query: str) -> list[dict]:
    if TavilyClient is None or not config.tavily_api_key:
        return []
    try:
        client = TavilyClient(api_key=config.tavily_api_key, proxies=config.proxies)
        response = client.search(
            query,
            search_depth="basic",
            max_results=config.search_max_results,
        )
        results = []
        for item in response.get("results", []):
            title = item.get("title") or ""
            content = item.get("content") or ""
            url = item.get("url") or ""
            if title and content:
                results.append({"title": title, "body": content[:500], "href": url})
        return results
    except Exception:
        logger.debug("Tavily search failed, falling back to ddgs")
        return []


def _ddgs_search(query: str) -> list[dict]:
    if DDGS is None:
        return []
    for use_proxy in (config.proxy_url or None, None):
        try:
            with DDGS(proxy=use_proxy, timeout=config.request_timeout) as ddgs:
                return list(ddgs.text(query, max_results=config.search_max_results))
        except Exception:
            if use_proxy is None:
                logger.debug("ddgs search failed")
    return []


def search(query: str) -> SearchResult:
    query = query.strip()
    if not query:
        return SearchResult(ok=False, status="empty_query", text="没有可搜索的关键词。")

    lines = []

    # 优先 Tavily，失败则 ddgs
    results = _tavily_search(query)
    if not results:
        results = _ddgs_search(query)

    for index, result in enumerate(results, 1):
        title = result.get("title") or "无标题"
        body = result.get("body") or ""
        href = result.get("href") or result.get("url") or ""
        lines.append(f"{index}. {title}\n摘要：{body}\n链接：{href}")

    if not lines:
        if TavilyClient is None and DDGS is None:
            return SearchResult(ok=False, status="missing_dependency", text="搜索组件未安装。需要 ddgs 或 tavily-python。")
        return SearchResult(ok=False, status="no_results", text="没有搜到有用结果。")
    return SearchResult(ok=True, status="success", text="\n\n".join(lines))


def web_search(query: str) -> str:
    return search(query).text


def has_search_results(search_result: SearchResult) -> bool:
    return search_result.ok
