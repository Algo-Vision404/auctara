"""Live web research tool.

No fabricated results are ever returned. Every result returned by
`search_web` comes from a real HTTP response from a real search engine at
call time. If every provider fails, the error propagates so the caller must
surface SEARCH_FAILED. We never invent or hardcode results.

Primary provider: `ddgs` (DuckDuckGo/meta-search aggregator).
Fallback provider: a direct, real-time HTML scrape of Bing search results.
The fallback exists because some sandboxed/datacenter network environments
are soft-blocked by DuckDuckGo/Yahoo (they return HTTP 200/202 with a
"temporary problem" / consent page instead of results) while still being
able to reach Bing normally. Both paths return only data that was actually
present in a live response body.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs, urlparse
import base64

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger("auctara.search")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class SearchError(Exception):
    pass


def _search_sync_ddgs(query: str, max_results: int) -> list[dict]:
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=max_results))
    normalized = []
    for r in results:
        normalized.append(
            {
                "title": r.get("title"),
                "url": r.get("href") or r.get("url"),
                "snippet": r.get("body") or r.get("snippet"),
            }
        )
    return normalized


def _decode_bing_redirect(href: str) -> str:
    """Bing wraps organic result links in a /ck/a? redirect with the real
    destination base64-encoded in the `u` query param, prefixed with "a1".
    If anything about that doesn't parse, fall back to the raw href. Never
    fabricate a URL.
    """
    try:
        parsed = urlparse(href)
        if "bing.com" not in parsed.netloc or parsed.path != "/ck/a":
            return href
        qs = parse_qs(parsed.query)
        u = qs.get("u", [None])[0]
        if not u:
            return href
        b64 = u[2:] if u.startswith("a1") else u
        b64 += "=" * (-len(b64) % 4)
        return base64.urlsafe_b64decode(b64).decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return href


def _search_sync_bing(query: str, max_results: int) -> list[dict]:
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}) as client:
        resp = client.get("https://www.bing.com/search", params={"q": query, "count": max_results})
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for li in soup.select("li.b_algo")[:max_results]:
        h2 = li.find("h2")
        a = h2.find("a") if h2 else None
        if not a or not a.get("href"):
            continue
        title = a.get_text(strip=True)
        url = _decode_bing_redirect(a["href"])
        caption = li.select_one(".b_caption p") or li.find("p")
        snippet = caption.get_text(strip=True) if caption else ""
        results.append({"title": title, "url": url, "snippet": snippet})
    return results


async def search_web(query: str, max_results: int = 8) -> list[dict]:
    errors: list[str] = []

    try:
        results = await asyncio.to_thread(_search_sync_ddgs, query, max_results)
        if results:
            return results
        errors.append("ddgs: no results")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ddgs: {exc}")

    try:
        results = await asyncio.to_thread(_search_sync_bing, query, max_results)
        if results:
            return results
        errors.append("bing: no results")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"bing: {exc}")

    logger.warning("All web search providers failed for query %r: %s", query, "; ".join(errors))
    raise SearchError(
        "Web search is temporarily unavailable; the search providers this agent "
        "relies on did not return results. Please try again shortly."
    )
