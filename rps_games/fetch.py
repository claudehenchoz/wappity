"""Fetch an RPS article's comment thread as server-rendered HTML."""

from __future__ import annotations

import re
from pathlib import Path

import httpx

BASE = "https://www.rockpapershotgun.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; rps-games/0.1)"}
THREAD_RE = re.compile(r"/community/thread/(\d+)")


def thread_id_for(article_url: str, client: httpx.Client) -> str:
    """Find the comment thread id embedded in the article page."""
    url = article_url.split("?")[0] + "?view=comments"
    html = client.get(url).raise_for_status().text
    m = THREAD_RE.search(html)
    if not m:
        raise RuntimeError(f"No /community/thread/<id> found on {url}")
    return m.group(1)


def fetch_thread(article_url: str, cache_dir: Path) -> tuple[str, str]:
    """Return (thread_id, thread_html). Cached on disk so reruns don't hit RPS."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = article_url.rstrip("/").split("/")[-1].split("?")[0]
    cached = cache_dir / f"{slug}.html"
    meta = cache_dir / f"{slug}.thread"
    if cached.exists() and meta.exists():
        return meta.read_text().strip(), cached.read_text(encoding="utf-8")

    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
        tid = thread_id_for(article_url, client)
        html = client.get(f"{BASE}/community/thread/{tid}").raise_for_status().text

    cached.write_text(html, encoding="utf-8")
    meta.write_text(tid)
    return tid, html
