"""Fetch real page content for the research agent.

search_web only returns short SERP snippets, which frequently omit the
actual price of a product. fetch_page lets the agent read the real text of
a real URL it found in search results. Still zero fabricated data, just a
second, deeper look at a page that genuinely exists on the live web.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("agentauth.fetch")

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

MAX_CHARS = 4000


class FetchError(Exception):
    pass


def _fetch_sync(url: str) -> str:
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}) as client:
        resp = client.get(url)
        resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise FetchError(f"Unsupported content type: {content_type or 'unknown'}")

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise FetchError("Page returned no readable text content.")
    return text[:MAX_CHARS]


async def fetch_page(url: str) -> str:
    try:
        return await asyncio.to_thread(_fetch_sync, url)
    except FetchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise FetchError(f"Failed to fetch page: {exc}") from exc
