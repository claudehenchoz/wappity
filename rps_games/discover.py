"""Find "What are we all playing this weekend?" threads via RPS's monthly archive pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .fetch import BASE, client

URL_RE = re.compile(re.escape(BASE) + r"/what-are-we-all-playing-this-weekend(?:-(\d+))?(?=[\"'?#/<\s])")


@dataclass(frozen=True)
class ThreadLink:
    url: str
    number: int | None


def _months(back: int, today: date) -> list[tuple[int, int]]:
    y, m = today.year, today.month
    out = []
    for _ in range(back + 1):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def list_threads(months_back: int, today: date | None = None) -> list[ThreadLink]:
    """All weekend threads in the current month and the previous `months_back` months, newest first."""
    found: dict[str, ThreadLink] = {}
    with client() as http:
        for y, m in _months(months_back, today or date.today()):
            r = http.get(f"{BASE}/archive/{y}/{m:02d}")
            if r.status_code == 404:  # month not started / no archive yet
                continue
            r.raise_for_status()
            for match in URL_RE.finditer(r.text):
                url = match.group(0)
                found[url] = ThreadLink(url, int(match.group(1)) if match.group(1) else None)
    return sorted(found.values(), key=lambda t: t.number or 0, reverse=True)
