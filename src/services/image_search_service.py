"""Image search service — search, download, and cache images.

First edition uses Tavily ``include_images`` when available, falling back
to extracting ``og:image`` or image URLs from regular Tavily results.

This module is designed to be reused by both ``/pic`` and future
``/image`` auto-reference workflows.
"""

import hashlib
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

from src.config import config
from src.util import try_proxied_get

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

logger = logging.getLogger("qq-bot")

_ALLOWED_CONTENT_TYPES = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
})

_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

_IMAGE_URL_PATTERN = re.compile(
    r"https?://\S+\.(?:jpg|jpeg|png|webp|gif)(?:\?\S*)?",
    re.IGNORECASE,
)


@dataclass
class ImageSearchResult:
    """A single image search result with local cached path."""
    local_path: str
    image_url: str
    source_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    provider: str = "tavily"


@dataclass
class _RawImageHit:
    """Internal: a candidate image URL before download."""
    image_url: str
    source_url: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None


def _cache_dir() -> Path:
    """Resolve and create the image search cache directory."""
    raw = config.image_search_cache_dir
    path = Path(raw)
    if not path.is_absolute():
        from src.config import BASE_DIR
        path = BASE_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(url: str, content_type: str) -> str:
    """Generate a safe filename from the URL hash + correct extension."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    ext = _EXT_MAP.get(content_type, ".jpg")
    return f"img_{url_hash}_{uuid.uuid4().hex[:8]}{ext}"


def _download_image(url: str, cache_path: Path) -> Optional[Path]:
    """Download an image URL to cache_path, enforcing size and type limits.

    Returns the local Path on success, or None on failure.
    """
    max_bytes = config.image_search_max_download_mb * 1024 * 1024
    try:
        resp = try_proxied_get(
            url,
            proxies=config.proxies,
            timeout=config.request_timeout,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ATRI-bot/1.0)"},
        )
        resp.raise_for_status()

        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type not in _ALLOWED_CONTENT_TYPES:
            logger.debug("Image download rejected: content_type=%s url=%s", content_type, url)
            return None

        filename = _safe_filename(url, content_type)
        dest = cache_path / filename

        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    logger.debug("Image download too large: %s bytes url=%s", downloaded, url)
                    f.close()
                    dest.unlink(missing_ok=True)
                    return None
                f.write(chunk)

        if downloaded == 0:
            dest.unlink(missing_ok=True)
            return None

        logger.info("Image downloaded: %s bytes -> %s", downloaded, dest.name)
        return dest

    except Exception:
        logger.debug("Image download failed: url=%s", url, exc_info=True)
        return None


def _tavily_image_search(query: str, max_results: int) -> list[_RawImageHit]:
    """Search for images using Tavily API with include_images option."""
    if TavilyClient is None or not config.tavily_api_key:
        return []

    try:
        client = TavilyClient(api_key=config.tavily_api_key, proxies=config.proxies)
        response = client.search(
            query,
            search_depth="basic",
            max_results=max_results,
            include_images=True,
        )

        hits: list[_RawImageHit] = []

        # 1. Use dedicated image results from Tavily
        for img_url in response.get("images", []):
            if img_url and isinstance(img_url, str) and img_url.startswith("http"):
                hits.append(_RawImageHit(
                    image_url=img_url,
                    source_url=None,
                    title=None,
                    description=f"Image result for: {query}",
                ))

        # 2. Also extract image URLs from regular result content/urls
        for item in response.get("results", []):
            item_url = item.get("url") or ""
            content = item.get("content") or ""
            title = item.get("title") or ""

            # Check if the result URL itself is an image
            if _IMAGE_URL_PATTERN.match(item_url):
                hits.append(_RawImageHit(
                    image_url=item_url,
                    source_url=item_url,
                    title=title,
                    description=content[:200] if content else None,
                ))

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[_RawImageHit] = []
        for hit in hits:
            if hit.image_url not in seen:
                seen.add(hit.image_url)
                unique.append(hit)

        return unique

    except Exception:
        logger.debug("Tavily image search failed", exc_info=True)
        return []


def search_and_download_images(
    query: str, limit: int = 1
) -> list[ImageSearchResult]:
    """Search for images, download them to cache, and return results.

    Args:
        query: Search keywords.
        limit: Maximum number of images to return (capped at config max).

    Returns:
        List of ImageSearchResult with local_path set to cached files.
    """
    send_max = min(config.image_search_send_max, 3)
    limit = max(1, min(limit, send_max))
    fetch_limit = config.image_search_max_results

    # Search for candidate images
    provider = config.image_search_provider
    if provider == "tavily":
        candidates = _tavily_image_search(query, fetch_limit)
    else:
        logger.warning("Unsupported image search provider: %s", provider)
        return []

    if not candidates:
        return []

    cache_path = _cache_dir()
    results: list[ImageSearchResult] = []

    for candidate in candidates:
        if len(results) >= limit:
            break

        local_path = _download_image(candidate.image_url, cache_path)
        if local_path is None:
            continue

        results.append(ImageSearchResult(
            local_path=str(local_path),
            image_url=candidate.image_url,
            source_url=candidate.source_url,
            title=candidate.title,
            description=candidate.description,
            provider=provider,
        ))

    return results
