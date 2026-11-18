"""rps-games: article URL -> comments -> game mentions -> canonical games -> CSVs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from .extract import extract
from .fetch import fetch_thread
from .parse import parse_thread
from .resolve import MentionRef, norm, resolve

# Relations that count as "someone is actually playing this".
PLAYED = {"playing", "finished", "dropped"}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", help="RPS article URL (with or without ?view=comments)")
    ap.add_argument("--data", type=Path, default=Path("data"), help="cache + output dir (default: data/)")
    ap.add_argument("--model", default="claude-opus-5-5", help="Claude model for extraction/disambiguation")
    ap.add_argument("--effort", default="low", choices=["low", "medium", "high"], help="extraction effort")
    ap.add_argument("--batch-chars", type=int, default=12000, help="comment chars per LLM call")
    ap.add_argument("--min-confidence", type=float, default=0.5)
    ap.add_argument("--parse-only", action="store_true", help="fetch + parse, write comments.json, stop")
    a = ap.parse_args(argv)

    tid, html = fetch_thread(a.url, a.data / "raw")
    comments = parse_thread(html)
    out = a.data / f"thread-{tid}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "comments.json").write_text(json.dumps([c.to_dict() for c in comments], ensure_ascii=False, indent=1))
    print(f"thread {tid}: {len(comments)} comments -> {out / 'comments.json'}", file=sys.stderr)
    if a.parse_only:
        return

    mentions = extract(comments, out / "extractions.json", a.model, a.effort, a.batch_chars)
    by_id = {c.id: c for c in comments}

    refs = []
    rows = []
    for cid, ms in mentions.items():
        c = by_id[cid]
        for m in ms:
            if m.confidence < a.min_confidence:
                continue
            refs.append(MentionRef(m.title, m.surface, c.text[:400]))
            rows.append((c, m))

    games = resolve(refs, a.data / "aliases.json", a.model)

    # --- mentions.csv: one row per (comment, game)
    with open(out / "mentions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["comment_id", "author", "likes", "depth", "surface", "llm_title", "game_key", "game", "year", "relation", "confidence", "method"])
        for c, m in rows:
            g = games[norm(m.title)]
            w.writerow([c.id, c.author, c.likes, c.depth, m.surface, m.title, g.key, g.name, g.year or "", m.relation, round(m.confidence, 2), g.method])

    # --- games.csv: aggregated, each commenter counted once per game
    agg: dict[str, dict] = defaultdict(lambda: {"players": set(), "mentioners": set(), "likes": 0, "comments": set()})
    names: dict[str, tuple[str, int | None]] = {}
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

    ranked = sorted(agg.items(), key=lambda kv: (-len(kv[1]["players"]), -len(kv[1]["mentioners"]), -kv[1]["likes"]))
    with open(out / "games.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["game_key", "game", "year", "players", "mentioners", "comments", "likes_on_comments"])
        for key, s in ranked:
            name, year = names[key]
            w.writerow([key, name, year or "", len(s["players"]), len(s["mentioners"]), len(s["comments"]), s["likes"]])

    print(f"{len(rows)} mentions, {len(agg)} distinct games -> {out / 'games.csv'}, {out / 'mentions.csv'}", file=sys.stderr)
    print(f"\n{'players':>7} {'ment.':>5}  game")
    for key, s in ranked[:25]:
        name, year = names[key]
        print(f"{len(s['players']):>7} {len(s['mentioners']):>5}  {name}{f' ({year})' if year else ''}")


if __name__ == "__main__":
    main()
