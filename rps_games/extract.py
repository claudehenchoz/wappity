"""LLM extraction of game mentions from comments (batched, structured output, cached)."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

import anthropic
from pydantic import BaseModel

from .parse import Comment

Relation = Literal["playing", "finished", "dropped", "planning", "mentioned", "comparison"]


class Mention(BaseModel):
    surface: str  # exactly as written in the comment
    title: str  # full official title, best guess
    relation: Relation
    confidence: float


class CommentMentions(BaseModel):
    comment_id: str
    mentions: list[Mention]


class BatchResult(BaseModel):
    comments: list[CommentMentions]


SYSTEM = """You extract video game mentions from reader comments on Rock Paper Shotgun's weekly \
"What are we all playing this weekend?" thread.

For each comment, list every distinct video game it names or clearly refers to. Rules:
- Only video games (including DLC/expansions, which you should name as the expansion). Not films, \
books, TV, board games, studios, people, engines, platforms or genres.
- Resolve abbreviations, nicknames and misspellings to the full official title, e.g. "KOTOR2"/"TSL" -> \
"Star Wars: Knights of the Old Republic II - The Sith Lords", "BG3" -> "Baldur's Gate 3".
- Use the reply context: if a reply says "I loved that one too" about a game named in the parent, \
record that game for the reply with relation "mentioned" (or "playing" if they say so). Do not \
otherwise copy games from the parent comment.
- A series name with no specific entry ("the Crazy Machines games") -> use the series name as title \
and confidence <= 0.5.
- relation: "playing" = currently/this weekend playing; "finished" = completed recently; "dropped" = \
gave up; "planning" = intends to play; "comparison" = only invoked to compare ("feels like Planescape"); \
"mentioned" = anything else.
- confidence: 0-1, how sure you are the title is right and it is a game.
- Same game named several ways in one comment -> one mention, surface = the clearest form.
- Return every input comment_id, with an empty list if it names no games."""


def _batches(comments: list[Comment], max_chars: int) -> list[list[Comment]]:
    out, cur, size = [], [], 0
    for c in comments:
        if cur and size + len(c.text) > max_chars:
            out.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(c.text)
    if cur:
        out.append(cur)
    return out


def _render(batch: list[Comment], by_id: dict[str, Comment]) -> str:
    items = []
    for c in batch:
        item = {"comment_id": c.id, "author": c.author, "text": c.text}
        if c.parent_id and (p := by_id.get(c.parent_id)):
            item["in_reply_to"] = {"author": p.author, "text": p.text[:1200]}
        items.append(item)
    return "<comments>\n" + json.dumps(items, ensure_ascii=False, indent=1) + "\n</comments>"


def _call(client: anthropic.Anthropic, model: str, effort: str, batch_text: str) -> BatchResult:
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": batch_text}],
        output_config={"effort": effort},
        output_format=BatchResult,
    )
    if model in {"claude-opus-5-5", "claude-sonnet-5-5"}:
        # Server-side fallback if a safety classifier declines (unlikely here, but cheap insurance).
        resp = client.beta.messages.parse(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        )
    else:
        resp = client.messages.parse(**kwargs)

    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens; lower --batch-chars")
    return resp.parsed_output


def extract(
    comments: list[Comment],
    cache_path: Path,
    model: str,
    effort: str = "low",
    batch_chars: int = 12000,
    workers: int = 4,
) -> dict[str, list[Mention]]:
    """Return {comment_id: [Mention, ...]}. Cached per (model, comment_id) in cache_path."""
    cache: dict = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    done: dict = cache.setdefault(model, {})
    todo = [c for c in comments if c.id not in done]
    by_id = {c.id: c for c in comments}

    if todo:
        client = anthropic.Anthropic()
        batches = _batches(todo, batch_chars)
        print(f"extracting {len(todo)} comments in {len(batches)} batches with {model}", file=sys.stderr)

        def run(batch: list[Comment]) -> tuple[list[Comment], BatchResult | Exception]:
            try:
                return batch, _call(client, model, effort, _render(batch, by_id))
            except Exception as e:  # keep going; failed batches are retried on next run
                return batch, e

        with ThreadPoolExecutor(workers) as pool:
            for batch, result in pool.map(run, batches):
                if isinstance(result, Exception):
                    print(f"  batch of {len(batch)} failed: {result}", file=sys.stderr)
                    continue
                wanted = {c.id for c in batch}
                for cm in result.comments:
                    if cm.comment_id in wanted:
                        done[cm.comment_id] = [m.model_dump() for m in cm.mentions]
                missing = wanted - done.keys()
                if missing:
                    print(f"  model skipped {len(missing)} comment ids; rerun to retry", file=sys.stderr)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1))

    return {cid: [Mention(**m) for m in done[cid]] for cid in by_id if cid in done}
