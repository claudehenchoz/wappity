"""rps-games: game mentions from RPS's weekly "What are we all playing this weekend?" threads.

  rps-games thread URL     process one thread, write CSVs to data/thread-<id>/
  rps-games weekly         find the newest thread(s), process them, update library/ and README.md
  rps-games render         regenerate library/ markdown and the README block from library/data/
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from . import library
from .discover import list_threads
from .fetch import fetch_thread
from .parse import parse_thread
from .pipeline import Options, process_thread

LIB = Path("library")
README = Path("README.md")


def _add_pipeline_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data", type=Path, default=Path("data"), help="cache + CSV output dir (default: data/)")
    p.add_argument("--model", default="claude-opus-5-5", help="Claude model for extraction/disambiguation")
    p.add_argument("--effort", default="low", choices=["low", "medium", "high"], help="extraction effort")
    p.add_argument("--batch-chars", type=int, default=12000, help="comment chars per LLM call")
    p.add_argument("--min-confidence", type=float, default=0.5)


def _opts(a: argparse.Namespace) -> Options:
    return Options(a.data, a.model, a.effort, a.batch_chars, a.min_confidence)


def cmd_thread(a: argparse.Namespace) -> int:
    if a.parse_only:
        tid, _, html = fetch_thread(a.url, a.data / "raw")
        comments = parse_thread(html)
        out = a.data / f"thread-{tid}"
        out.mkdir(parents=True, exist_ok=True)
        (out / "comments.json").write_text(json.dumps([c.to_dict() for c in comments], ensure_ascii=False, indent=1))
        print(f"thread {tid}: {len(comments)} comments -> {out / 'comments.json'}", file=sys.stderr)
        return 0
    w = process_thread(a.url, _opts(a))
    if a.save:
        library.save(LIB, w)
        library.render(LIB, README)
    print(f"\n{'played':>6} {'ment.':>5}  game")
    for g in w.games[:25]:
        print(f"{g.players:>6} {g.mentioners:>5}  {g.name}{f' ({g.year})' if g.year else ''}")
    return 0


def cmd_weekly(a: argparse.Namespace) -> int:
    want = max(1, a.backfill_weeks)
    threads = [t for t in list_threads(months_back=math.ceil(want / 4) + 1) if t.number is not None]
    if not threads:
        print("error: no weekend threads found in the RPS archive", file=sys.stderr)
        return 1
    selected = threads[:want]
    todo = [t for t in selected if a.force or not library.has_week(LIB, t.number)]
    if not todo:
        print(f"nothing new (latest is #{threads[0].number}, already in the library)", file=sys.stderr)
        library.render(LIB, README)
        return 0

    failed = 0
    for t in reversed(todo):  # oldest first
        print(f"== #{t.number} {t.url}", file=sys.stderr)
        try:
            library.save(LIB, process_thread(t.url, _opts(a)))
        except Exception as e:  # keep going; the next run retries anything missing
            failed += 1
            print(f"error processing #{t.number}: {e}", file=sys.stderr)
    n = library.render(LIB, README)
    print(f"library: {n} weeks rendered to {LIB}/", file=sys.stderr)
    return 1 if failed == len(todo) else 0


def cmd_render(a: argparse.Namespace) -> int:
    n = library.render(LIB, README)
    print(f"library: {n} weeks rendered to {LIB}/", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0].startswith("http"):  # back-compat: `rps-games URL`
        argv = ["thread", *argv]

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("thread", help="process one thread URL")
    p.add_argument("url", help="RPS article URL (with or without ?view=comments)")
    p.add_argument("--save", action="store_true", help="also add the result to library/ and re-render")
    p.add_argument("--parse-only", action="store_true", help="fetch + parse, write comments.json, stop")
    _add_pipeline_opts(p)
    p.set_defaults(fn=cmd_thread)

    p = sub.add_parser("weekly", help="process the newest thread(s) and update the library")
    p.add_argument("--backfill-weeks", type=int, default=0, help="also process the N newest threads (default: just the latest)")
    p.add_argument("--force", action="store_true", help="reprocess threads already in the library")
    _add_pipeline_opts(p)
    p.set_defaults(fn=cmd_weekly)

    p = sub.add_parser("render", help="regenerate library markdown + README block (no network)")
    p.set_defaults(fn=cmd_render)

    a = ap.parse_args(argv)
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
