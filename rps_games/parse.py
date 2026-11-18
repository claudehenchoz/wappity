"""Parse the /community/thread/<id> HTML fragment into flat comment records."""

from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup, Tag


@dataclass
class Comment:
    id: str
    parent_id: str | None
    depth: int
    author: str
    date: float
    likes: int
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _text(content: Tag) -> str:
    # Keep paragraph breaks; collapse everything else.
    paras = [p.get_text(" ", strip=True) for p in content.find_all(["p", "li", "blockquote"])]
    paras = [p for p in paras if p]
    if not paras:
        paras = [content.get_text(" ", strip=True)]
    return re.sub(r"[ \t]+", " ", "\n".join(paras)).strip()


def _parent_id(post: Tag) -> str | None:
    # Layout: div.post__wrapper > (div.post, div.post__children > div.post__wrapper > ...)
    wrapper = post.find_parent("div", class_="post__wrapper")
    children = wrapper.find_parent("div", class_="post__children") if wrapper else None
    if children is None:
        return None
    parent_wrapper = children.find_parent("div", class_="post__wrapper")
    parent_post = parent_wrapper.find("div", class_="post", recursive=False) if parent_wrapper else None
    return parent_post.get("data-hashid") if parent_post else None


def parse_thread(html: str) -> list[Comment]:
    soup = BeautifulSoup(html, "lxml")
    comments: list[Comment] = []
    for post in soup.select("div.post[data-hashid]"):
        content = post.select_one(".what .markdown")
        if content is None:  # removed / deleted comments
            continue
        name = post.select_one(".username .name")
        comments.append(
            Comment(
                id=post["data-hashid"],
                parent_id=_parent_id(post),
                depth=int(post.get("data-parent-count", 0)),
                author=name.get_text(strip=True) if name else "?",
                date=float(post.get("data-date", 0)),
                likes=int(post.get("data-like-count", 0)),
                text=_text(content),
            )
        )

    stated = soup.select_one(".post_count .count")
    if stated and int(stated.get_text(strip=True)) > len(comments):
        print(
            f"warning: thread says {stated.get_text(strip=True)} comments, parsed {len(comments)} "
            "(removed comments are skipped; a large gap may mean pagination)",
            file=sys.stderr,
        )
    return comments
