"""Fetch an RPS article's comment thread as server-rendered HTML."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

BASE = "https://www.rockpapershotgun.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; rps-games/0.1)"}
THREAD_RE = re.compile(r"/community/thread/(\d+)")
PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')


def client() -> httpx.Client:
    return httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30)


def article_meta(article_url: str, http: httpx.Client) -> tuple[str, str]:
    """Return (thread_id, published ISO timestamp).

    The plain article page carries the JSON-LD publish date; only the ?view=comments page
    carries the comment thread id, so both are fetched.
    """
    base = article_url.split("?")[0]
    p = PUBLISHED_RE.search(http.get(base).raise_for_status().text)
    if not p:
        raise RuntimeError(f"No datePublished found on {base}")
    m = THREAD_RE.search(http.get(base + "?view=comments").raise_for_status().text)
    if not m:
        raise RuntimeError(f"No /community/thread/<id> found on {base}?view=comments")
    return m.group(1), p.group(1)


def fetch_thread(article_url: str, cache_dir: Path) -> tuple[str, str, str]:
    """Return (thread_id, published, thread_html). Cached on disk so reruns don't hit RPS."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = article_url.rstrip("/").split("/")[-1].split("?")[0]
    cached = cache_dir / f"{slug}.html"
    meta = cache_dir / f"{slug}.thread"
    if cached.exists() and meta.exists():
        raw = meta.read_text().strip()
        # Older caches stored only the bare thread id.
        m = json.loads(raw) if raw.startswith("{") else {"thread_id": raw, "published": ""}
        if m["published"]:
            return m["thread_id"], m["published"], cached.read_text(encoding="utf-8")

    with client() as http:
        tid, published = article_meta(article_url, http)
        html = http.get(f"{BASE}/community/thread/{tid}").raise_for_status().text

    cached.write_text(html, encoding="utf-8")
    meta.write_text(json.dumps({"thread_id": tid, "published": published}))
    return tid, published, html
