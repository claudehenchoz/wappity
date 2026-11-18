"""One thread end to end: fetch -> parse -> extract -> resolve -> aggregate (+ CSVs)."""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .extract import extract
from .fetch import fetch_thread
from .parse import parse_thread
from .resolve import MentionRef, norm, resolve

# Relations that count as "someone is actually playing this".
PLAYED = {"playing", "finished", "dropped"}


@dataclass
class Options:
    data: Path = Path("data")
    model: str = "claude-opus-5-5"
    effort: str = "low"
    batch_chars: int = 12000
    min_confidence: float = 0.5


@dataclass
class GameRow:
    key: str
    name: str
    year: int | None
    players: int
    mentioners: int
    comments: int
    likes: int


@dataclass
class MentionRow:
    comment_id: str
    author: str
    game_key: str
    relation: str


@dataclass
class WeekResult:
    url: str
    number: int | None
    thread_id: str
    published: str  # ISO timestamp from the article
    comment_count: int
    commenters: int
    games: list[GameRow] = field(default_factory=list)  # ranked
    mentions: list[MentionRow] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "WeekResult":
        d = json.loads(text)
        d["games"] = [GameRow(**g) for g in d["games"]]
        d["mentions"] = [MentionRow(**m) for m in d["mentions"]]
        return cls(**d)


def thread_number(url: str) -> int | None:
    m = re.search(r"-(\d+)/?(?:\?|$)", url)
    return int(m.group(1)) if m else None


def process_thread(url: str, opt: Options) -> WeekResult:
    tid, published, html = fetch_thread(url, opt.data / "raw")
    comments = parse_thread(html)
    out = opt.data / f"thread-{tid}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "comments.json").write_text(json.dumps([c.to_dict() for c in comments], ensure_ascii=False, indent=1))
    print(f"thread {tid}: {len(comments)} comments", file=sys.stderr)

    mentions = extract(comments, out / "extractions.json", opt.model, opt.effort, opt.batch_chars)
    by_id = {c.id: c for c in comments}

    refs, rows = [], []
    for cid, ms in mentions.items():
        c = by_id[cid]
        for m in ms:
            if m.confidence < opt.min_confidence:
                continue
            refs.append(MentionRef(m.title, m.surface, c.text[:400]))
            rows.append((c, m))

    games = resolve(refs, opt.data / "aliases.json", opt.model)

    # --- mentions.csv: one row per (comment, game)
    with open(out / "mentions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["comment_id", "author", "likes", "depth", "surface", "llm_title", "game_key", "game", "year", "relation", "confidence", "method"])
        for c, m in rows:
            g = games[norm(m.title)]
            w.writerow([c.id, c.author, c.likes, c.depth, m.surface, m.title, g.key, g.name, g.year or "", m.relation, round(m.confidence, 2), g.method])

    # --- aggregate: each commenter counted once per game
    agg: dict[str, dict] = defaultdict(lambda: {"players": set(), "mentioners": set(), "likes": 0, "comments": set()})
    names: dict[str, tuple[str, int | None]] = {}
    mention_rows: dict[tuple[str, str], MentionRow] = {}
    for c, m in rows:
        g = games[norm(m.title)]
        names[g.key] = (g.name, g.year)
        s = agg[g.key]
        s["mentioners"].add(c.author)
        if m.relation in PLAYED:
            s["players"].add(c.author)
        if c.id not in s["comments"]:
            s["comments"].add(c.id)
            s["likes"] += c.likes
        # One row per (comment, game); keep the strongest relation if a comment repeats a game.
        k = (c.id, g.key)
        if k not in mention_rows or (m.relation in PLAYED and mention_rows[k].relation not in PLAYED):
            mention_rows[k] = MentionRow(c.id, c.author, g.key, m.relation)

    ranked = sorted(agg.items(), key=lambda kv: (-len(kv[1]["players"]), -len(kv[1]["mentioners"]), -kv[1]["likes"], names[kv[0]][0].lower()))
    game_rows = [
        GameRow(key, names[key][0], names[key][1], len(s["players"]), len(s["mentioners"]), len(s["comments"]), s["likes"])
        for key, s in ranked
    ]

    with open(out / "games.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["game_key", "game", "year", "players", "mentioners", "comments", "likes_on_comments"])
        for g in game_rows:
            w.writerow([g.key, g.name, g.year or "", g.players, g.mentioners, g.comments, g.likes])
    print(f"{len(rows)} mentions, {len(game_rows)} distinct games -> {out / 'games.csv'}, {out / 'mentions.csv'}", file=sys.stderr)

    return WeekResult(
        url=url.split("?")[0],
        number=thread_number(url),
        thread_id=tid,
        published=published,
        comment_count=len(comments),
        commenters=len({c.author for c in comments}),
        games=game_rows,
        mentions=sorted(mention_rows.values(), key=lambda r: (r.comment_id, r.game_key)),
    )
