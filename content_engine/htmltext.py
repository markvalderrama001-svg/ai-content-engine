"""Small HTML helpers (standard library only)."""
from __future__ import annotations

import html
import re

TAG = re.compile(r"<[^>]+>")
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)


def visible_text(markup: str) -> str:
    """Text a reader sees: scripts removed, tags stripped, entities decoded."""
    text = SCRIPT.sub(" ", markup)
    text = TAG.sub(" ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def prose_text(markup: str) -> str:
    """Running prose only: <p> and <li> contents (labels, tables and headings excluded)."""
    parts = re.findall(r"<(p|li)\b[^>]*>(.*?)</\1>", SCRIPT.sub(" ", markup), re.S | re.I)
    return " ".join(visible_text(body) for _, body in parts)


def word_count(markup: str) -> int:
    return len(visible_text(markup).split())


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 2]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", visible_text(text).lower()).strip("-")


def headings(markup: str) -> list[str]:
    return [visible_text(h) for _, h in re.findall(r"<h([1-6])\b[^>]*>(.*?)</h\1>", markup, re.S | re.I)]


def links(markup: str) -> list[str]:
    return re.findall(r"<a\b[^>]*href=\"([^\"]+)\"", markup, re.I)


def images(markup: str) -> list[str]:
    return re.findall(r"<img\b[^>]*src=\"([^\"]+)\"", markup, re.I)
