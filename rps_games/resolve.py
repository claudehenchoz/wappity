"""Normalize extracted titles to canonical games.

With TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET set: look each title up on IGDB, accept clear fuzzy
matches, and let the LLM pick among candidates when ambiguous (remakes, same-name reboots, typos).
Without them: cluster near-identical LLM titles and use the most common spelling.

Resolutions are cached in aliases.json (normalized title -> game), so repeated weekly runs mostly
skip both IGDB and the LLM. Edit that file by hand to fix a bad match; it is never overwritten.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import anthropic
import httpx
from pydantic import BaseModel
from rapidfuzz import fuzz

ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = [ROMAN.get(w, w) for w in s.split()]
    if words and words[0] == "the":
        words = words[1:]
    return " ".join(words)


@dataclass
class Game:
    key: str  # stable id: "igdb:1234" or "title:<normalized>"
    name: str
    year: int | None = None
    method: str = ""  # how it was resolved: exact / fuzzy / llm / unresolved / cluster


@dataclass
class MentionRef:
    title: str
    surface: str
    context: str


# ---------------------------------------------------------------- IGDB


class IGDB:
    def __init__(self, client_id: str, client_secret: str):
        tok = httpx.post(
            "https://id.twitch.tv/oauth2/token",
            params={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"},
            timeout=30,
        ).raise_for_status().json()["access_token"]
        self.http = httpx.Client(
            base_url="https://api.igdb.com/v4",
            headers={"Client-ID": client_id, "Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        self._last = 0.0

    def search(self, title: str, limit: int = 10) -> list[dict]:
        wait = 0.26 - (time.monotonic() - self._last)  # IGDB allows 4 req/s
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        q = title.replace('"', "")
        body = (
            f'search "{q}"; fields name,first_release_date,alternative_names.name,total_rating_count; '
            f"limit {limit};"
        )
        return self.http.post("/games", content=body).raise_for_status().json()


def _year(c: dict) -> int | None:
    ts = c.get("first_release_date")
    return time.gmtime(ts).tm_year if ts else None


def _score(title: str, cand: dict) -> float:
    names = [cand["name"]] + [a["name"] for a in cand.get("alternative_names", [])]
    t = norm(title)
    return max(fuzz.token_sort_ratio(t, norm(n)) for n in names)


class Pick(BaseModel):
    title: str
    igdb_id: int | None


class Picks(BaseModel):
    picks: list[Pick]


PICK_SYSTEM = """You match video game titles mentioned in forum comments to IGDB entries. For each item \
you get the title as interpreted, the original wording, comment excerpts, and IGDB candidates. Return the \
igdb_id of the game the commenter means, using context and release years to tell remakes, remasters and \
same-name reboots apart (with no other signal, prefer the most recent / most popular entry). Return null \
if no candidate is that game, or if the title is not a video game."""


def _llm_pick(client: anthropic.Anthropic, model: str, items: list[dict]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for i in range(0, len(items), 25):
        chunk = items[i : i + 25]
        resp = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=PICK_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(chunk, ensure_ascii=False, indent=1)}],
            output_config={"effort": "low"},
            output_format=Picks,
        )
        if resp.stop_reason != "end_turn" or resp.parsed_output is None:
            print(f"  disambiguation chunk failed: {resp.stop_reason}", file=sys.stderr)
            continue
        valid = {it["title"]: {c["id"] for c in it["candidates"]} for it in chunk}
        for p in resp.parsed_output.picks:
            if p.title in valid:
                out[p.title] = p.igdb_id if p.igdb_id in valid[p.title] else None
    return out


def _resolve_igdb(
    titles: dict[str, list[MentionRef]], aliases: dict, igdb: IGDB, model: str
) -> None:
    ambiguous: list[dict] = []
    cands_by_title: dict[str, list[dict]] = {}
    for title, refs in titles.items():
        cands = igdb.search(title)
        if not cands:
            aliases[norm(title)] = {"key": f"title:{norm(title)}", "name": title, "year": None, "method": "unresolved"}
            continue
        scored = sorted(((_score(title, c), c.get("total_rating_count") or 0, c) for c in cands), key=lambda x: x[:2], reverse=True)
        best, runner = scored[0], scored[1] if len(scored) > 1 else None
        clear = best[0] >= 92 and (runner is None or runner[0] < best[0] - 3)
        if clear:
            c = best[2]
            aliases[norm(title)] = {"key": f"igdb:{c['id']}", "name": c["name"], "year": _year(c), "method": "exact" if best[0] == 100 else "fuzzy"}
        else:
            cands_by_title[title] = cands
            ambiguous.append({
                "title": title,
                "as_written": sorted({r.surface for r in refs}),
                "excerpts": [r.context for r in refs[:3]],
                "candidates": [{"id": c["id"], "name": c["name"], "year": _year(c)} for _, _, c in scored[:8]],
            })

    if ambiguous:
        print(f"  asking {model} to disambiguate {len(ambiguous)} titles", file=sys.stderr)
        picks = _llm_pick(anthropic.Anthropic(), model, ambiguous)
        for item in ambiguous:
            title = item["title"]
            pid = picks.get(title)
            c = next((c for c in cands_by_title[title] if c["id"] == pid), None)
            aliases[norm(title)] = (
                {"key": f"igdb:{c['id']}", "name": c["name"], "year": _year(c), "method": "llm"}
                if c
                else {"key": f"title:{norm(title)}", "name": title, "year": None, "method": "unresolved"}
            )


# ---------------------------------------------------------------- fallback (no IGDB)


def _resolve_cluster(titles: dict[str, list[MentionRef]], aliases: dict) -> None:
    # Most-mentioned spelling first becomes the cluster head.
    order = sorted(titles, key=lambda t: -len(titles[t]))
    heads: list[str] = [h for h in (a["name"] for a in aliases.values())]
    for t in order:
        n = norm(t)
        head = next((h for h in heads if fuzz.ratio(n, norm(h)) >= 95), None)
        if head is None:
            heads.append(t)
            head = t
        aliases[n] = {"key": f"title:{norm(head)}", "name": head, "year": None, "method": "cluster"}


# ---------------------------------------------------------------- entry point


def resolve(refs: list[MentionRef], aliases_path: Path, model: str) -> dict[str, Game]:
    """Return {normalized title: Game} for every title in refs, updating the alias cache."""
    aliases: dict = json.loads(aliases_path.read_text()) if aliases_path.exists() else {}
    by_title: dict[str, list[MentionRef]] = defaultdict(list)
    for r in refs:
        by_title[r.title].append(r)
    # One representative spelling per normalized title.
    rep: dict[str, str] = {}
    for t in sorted(by_title, key=lambda t: -len(by_title[t])):
        rep.setdefault(norm(t), t)
    todo = {t: [r for tt in by_title if norm(tt) == n for r in by_title[tt]] for n, t in rep.items() if n not in aliases}

    if todo:
        cid, secret = os.environ.get("TWITCH_CLIENT_ID"), os.environ.get("TWITCH_CLIENT_SECRET")
        if cid and secret:
            print(f"resolving {len(todo)} new titles against IGDB", file=sys.stderr)
            _resolve_igdb(todo, aliases, IGDB(cid, secret), model)
        else:
            print(f"no TWITCH_CLIENT_ID/SECRET: clustering {len(todo)} titles without IGDB", file=sys.stderr)
            _resolve_cluster(todo, aliases)
        aliases_path.parent.mkdir(parents=True, exist_ok=True)
        aliases_path.write_text(json.dumps(dict(sorted(aliases.items())), ensure_ascii=False, indent=1))

    return {n: Game(**aliases[n]) for n in rep}

