"""Markdown library: one page per thread, a rolling 3-month view, an index, and a README block.

library/data/*.json (WeekResult) is the source of truth; every .md file is regenerated from it,
deterministically, so re-rendering without new data produces no diff.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from .pipeline import PLAYED, WeekResult

WINDOW_DAYS = 91
TOP_N_ROLLING = 50
README_START, README_END = "<!-- library:start -->", "<!-- library:end -->"


# ---------------------------------------------------------------- helpers


def stem(w: WeekResult) -> str:
    return f"{w.published[:10]}-{w.number}"


def when(w: WeekResult) -> datetime:
    return datetime.fromisoformat(w.published)


def day(w: WeekResult) -> str:
    d = when(w)
    return f"{d.day} {d:%b %Y}"


def label(w: WeekResult) -> str:
    return f"#{w.number}"


def esc(s: str) -> str:
    return s.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def game_label(name: str, year: int | None) -> str:
    return f"{esc(name)} ({year})" if year else esc(name)


def in_table(g) -> bool:
    return g.players > 0 or g.mentioners > 1


def load(lib: Path) -> list[WeekResult]:
    weeks = [WeekResult.from_json(p.read_text(encoding="utf-8")) for p in (lib / "data").glob("*.json")]
    return sorted(weeks, key=lambda w: (w.published, w.number or 0))


def save(lib: Path, w: WeekResult) -> Path:
    (lib / "data").mkdir(parents=True, exist_ok=True)
    for old in (lib / "data").glob(f"*-{w.number}.json"):  # published date may have been corrected
        old.unlink()
    p = lib / "data" / f"{stem(w)}.json"
    p.write_text(w.to_json(), encoding="utf-8")
    return p


def has_week(lib: Path, number: int) -> bool:
    return any((lib / "data").glob(f"*-{number}.json"))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- pages


def week_page(w: WeekResult, prev: WeekResult | None, nxt: WeekResult | None) -> str:
    nav = [f"[← {label(prev)}]({stem(prev)}.md)" if prev else None, "[All weeks](../index.md)",
           "[Last 3 months](../last-3-months.md)", f"[{label(nxt)} →]({stem(nxt)}.md)" if nxt else None]
    shown = [g for g in w.games if in_table(g)]
    rest = [g for g in w.games if not in_table(g)]
    lines = [
        f"# What are we all playing this weekend? {label(w)}",
        "",
        f"{day(w)} · [Thread on Rock Paper Shotgun]({w.url}) · {w.comment_count} comments from "
        f"{w.commenters} commenters · {len(w.games)} games mentioned",
        "",
        " · ".join(n for n in nav if n),
        "",
        "| # | Game | Played by | Mentioned by | Likes |",
        "|--:|---|--:|--:|--:|",
    ]
    lines += [f"| {i} | {game_label(g.name, g.year)} | {g.players} | {g.mentioners} | {g.likes} |" for i, g in enumerate(shown, 1)]
    if rest:
        lines += ["", "**Also mentioned once:** " + ", ".join(game_label(g.name, g.year) for g in sorted(rest, key=lambda g: g.name.lower()))]
    lines += [
        "",
        "*Played by* counts commenters who are playing, finished or dropped the game this week; "
        "*Mentioned by* counts everyone who named it; *Likes* is the total on those comments.",
        "",
    ]
    return "\n".join(lines)


def rolling_page(weeks: list[WeekResult]) -> str:
    newest = weeks[-1]
    cutoff = when(newest) - timedelta(days=WINDOW_DAYS)
    window = [w for w in weeks if when(w) >= cutoff]

    agg: dict[str, dict] = defaultdict(lambda: {"players": set(), "mentioners": set(), "weeks": []})
    names: dict[str, tuple[str, int | None]] = {}
    for w in window:
        for g in w.games:
            names[g.key] = (g.name, g.year)  # latest week wins
            agg[g.key]["weeks"].append(w)
        for m in w.mentions:
            agg[m.game_key]["mentioners"].add(m.author)
            if m.relation in PLAYED:
                agg[m.game_key]["players"].add(m.author)

    ranked = sorted(agg.items(), key=lambda kv: (-len(kv[1]["players"]), -len(kv[1]["mentioners"]),
                                                  -len(kv[1]["weeks"]), names[kv[0]][0].lower()))
    link = lambda w: f"[{label(w)}](weeks/{stem(w)}.md)"
    lines = [
        "# Last three months",
        "",
        f"{len(window)} thread{'s' if len(window) != 1 else ''} from {day(window[0])} to {day(newest)} · {len(agg)} games mentioned · "
        "[All weeks](index.md)",
        "",
        "| # | Game | Played by | Mentioned by | Weeks | First seen | Last seen |",
        "|--:|---|--:|--:|--:|---|---|",
    ]
    for i, (key, s) in enumerate(ranked[:TOP_N_ROLLING], 1):
        ws = s["weeks"]
        lines.append(f"| {i} | {game_label(*names[key])} | {len(s['players'])} | {len(s['mentioners'])} | "
                     f"{len(ws)} | {link(ws[0])} | {link(ws[-1])} |")
    if len(ranked) > TOP_N_ROLLING:
        lines += ["", f"…and {len(ranked) - TOP_N_ROLLING} more; see the weekly pages."]

    earlier = {g.key for w in window[:-1] for g in w.games}
    new = [g for g in newest.games if in_table(g) and g.key not in earlier]
    if len(window) > 1:
        lines += ["", f"## New in {link(newest)}", ""]
        lines += [f"- {game_label(g.name, g.year)} — played by {g.players}, mentioned by {g.mentioners}" for g in new] or ["- nothing new this week"]
    lines += [
        "",
        "*Played by* and *Mentioned by* count unique commenters across the whole window; "
        "*Weeks* is how many threads mentioned the game.",
        "",
    ]
    return "\n".join(lines)


def index_page(weeks: list[WeekResult]) -> str:
    lines = ["# All weeks", "", "[Last 3 months](last-3-months.md)", ""]
    for w in reversed(weeks):
        top = ", ".join(esc(g.name) for g in w.games[:3])
        lines.append(f"- [{label(w)} · {day(w)}](weeks/{stem(w)}.md) — {w.comment_count} comments · {top}")
    return "\n".join(lines) + "\n"


def readme_block(weeks: list[WeekResult]) -> str:
    w = weeks[-1]
    top = ", ".join(esc(g.name) for g in w.games[:5])
    return "\n".join([
        README_START,
        f"**Latest thread:** [{label(w)} · {day(w)}](library/weeks/{stem(w)}.md) — {top}",
        "",
        "**Library:** [Last 3 months](library/last-3-months.md) · [All weeks](library/index.md)",
        README_END,
    ])


def update_readme(readme: Path, block: str) -> None:
    text = readme.read_text(encoding="utf-8")
    if README_START in text and README_END in text:
        text = re.sub(re.escape(README_START) + r".*?" + re.escape(README_END), lambda _: block, text, flags=re.S)
    else:  # insert right below the H1
        head, _, tail = text.partition("\n")
        text = f"{head}\n\n{block}\n{tail}"
    _write(readme, text)


def render(lib: Path, readme: Path) -> int:
    weeks = load(lib)
    if not weeks:
        return 0
    for i, w in enumerate(weeks):
        prev = weeks[i - 1] if i else None
        nxt = weeks[i + 1] if i + 1 < len(weeks) else None
        _write(lib / "weeks" / f"{stem(w)}.md", week_page(w, prev, nxt))
    _write(lib / "last-3-months.md", rolling_page(weeks))
    _write(lib / "index.md", index_page(weeks))
    update_readme(readme, readme_block(weeks))
    return len(weeks)
