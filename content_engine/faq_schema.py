"""FAQPage JSON-LD from the article's visible FAQ section.

Rules:
- Only questions and answers a reader can see on the page go into the schema.
- Idempotent: if the content already carries FAQPage markup, nothing changes.
- The injected block must parse as JSON (re-checked before returning).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .htmltext import visible_text

FAQ_H2 = re.compile(r"<h2\b[^>]*>(?:[^<]*?)(?:FAQ|Frequently Asked Questions)[^<]*</h2>", re.I)


@dataclass
class FaqResult:
    html: str
    injected: bool
    pairs: list[tuple[str, str]]
    reason: str


def extract_faq_pairs(markup: str) -> list[tuple[str, str]]:
    start = FAQ_H2.search(markup)
    if not start:
        return []
    rest = markup[start.end():]
    nxt = re.search(r"<h2\b", rest, re.I)
    section = rest[: nxt.start()] if nxt else rest
    pairs = []
    blocks = re.split(r"(?=<h3\b)", section)
    for blk in blocks:
        q = re.match(r"<h3\b[^>]*>(.*?)</h3>", blk, re.S | re.I)
        if not q:
            continue
        answer = " ".join(visible_text(p) for p in re.findall(r"<p\b[^>]*>(.*?)</p>", blk, re.S | re.I))
        question = visible_text(q.group(1))
        if question and answer:
            pairs.append((question, answer))
    return pairs


def build_faq_jsonld(pairs: list[tuple[str, str]]) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in pairs
        ],
    }
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False, indent=1) + "</script>"


def inject_faq_schema(markup: str) -> FaqResult:
    if '"FAQPage"' in markup or "'FAQPage'" in markup:
        return FaqResult(markup, False, [], "FAQPage already present, left unchanged")
    pairs = extract_faq_pairs(markup)
    if not pairs:
        return FaqResult(markup, False, [], "no visible FAQ section, nothing injected")
    block = build_faq_jsonld(pairs)
    json.loads(block[block.index(">") + 1: block.rindex("<")])  # must parse
    return FaqResult(markup.rstrip() + "\n" + block + "\n", True, pairs, f"FAQPage injected ({len(pairs)} Q&A)")
