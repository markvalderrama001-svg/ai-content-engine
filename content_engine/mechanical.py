"""Mechanical checks: rules a script can enforce without trusting a model.

These run on the source article (to brief the writer), after every writer
pass (critic step) and once more on the final draft (verifier step). A model
can be persuaded; a regex cannot.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import EditorialRules
from .htmltext import headings, images, links, prose_text, visible_text, word_count

EM_DASH = "—"
EN_DASH = "–"

# First-person claims of having done the work yourself. "I haven't run" does not match.
FIRST_PERSON_CLAIM = re.compile(
    r"\b(in my experience (?:running|closing|reconciling|managing)|"
    r"I(?:'ve| have)? (?:run|closed|reconciled|managed) (?:the|our|my|a|this)|when I (?:ran|closed|managed)|"
    r"I (?:run|close|reconcile) (?:the|our|my|a)|my (?:own )?(?:finance team|books|close|clients?))\b",
    re.I,
)


@dataclass
class Issue:
    code: str
    message: str
    excerpt: str = ""
    blocking: bool = True


@dataclass
class MechanicalReport:
    issues: list[Issue] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not any(i.blocking for i in self.issues)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.issues:
            out[i.code] = out.get(i.code, 0) + 1
        return out

    def summary(self) -> str:
        if not self.issues:
            return "PASS"
        parts = [f"{code} x{n}" for code, n in self.counts().items()]
        return ("PASS (warnings: " if self.passed else "FAIL: ") + ", ".join(parts) + (")" if self.passed else "")


def _context(text: str, start: int, end: int, pad: int = 35) -> str:
    """Excerpt around a match, widened to whole words."""
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    while lo > 0 and not text[lo - 1].isspace():
        lo -= 1
    while hi < len(text) and not text[hi].isspace():
        hi += 1
    return ("..." if lo > 0 else "") + text[lo:hi].strip() + ("..." if hi < len(text) else "")


def check_article(
    markup: str,
    rules: EditorialRules,
    *,
    first_person_confirmed: bool = False,
    original: str | None = None,
) -> MechanicalReport:
    rep = MechanicalReport()
    prose = prose_text(markup)
    text = visible_text(markup)
    lower = text.lower()

    # 1. Em / en dashes in prose. The entity form is tolerated only outside <p>/<li> (label separators).
    for m in re.finditer(f"[{EM_DASH}{EN_DASH}]", prose):
        rep.issues.append(Issue("em_dash", "raw em/en dash in prose", _context(prose, m.start(), m.end())))
    if not rules.allow_dash_entity_in_labels and "&#8212;" in markup:
        rep.issues.append(Issue("em_dash", "&#8212; entity present"))

    # 2. Banned phrases (stock LLM phrasing, comment-bait closings).
    for phrase in rules.banned_phrases:
        for m in re.finditer(re.escape(phrase), lower):
            rep.issues.append(Issue("banned_phrase", f"banned phrase: '{phrase}'", _context(text, m.start(), m.end())))

    # 3. Competitor mentions (text or links).
    for comp in rules.competitors:
        if comp.lower() in markup.lower():
            rep.issues.append(Issue("competitor", f"competitor mentioned: {comp}"))

    # 4. First-person keeping claims the author has not confirmed.
    if not first_person_confirmed:
        for m in FIRST_PERSON_CLAIM.finditer(prose):
            rep.issues.append(Issue("unconfirmed_first_person", "first-person experience claim not confirmed by the author",
                                    _context(prose, m.start(), m.end())))

    # 5. Hedging (warning only; the reviewer weighs it).
    hedges = sum(len(re.findall(r"\b" + re.escape(h) + r"\b", lower)) for h in rules.hedge_words)
    if hedges > rules.max_hedges:
        rep.issues.append(Issue("hedging", f"{hedges} hedge words (max {rules.max_hedges})", blocking=False))

    # 6. JSON-LD must parse.
    for block in re.findall(r"<script type=\"application/ld\+json\">(.*?)</script>", markup, re.S):
        try:
            json.loads(block)
        except json.JSONDecodeError as exc:
            rep.issues.append(Issue("jsonld_invalid", f"JSON-LD does not parse: {exc.msg}"))

    # 7. Preservation against the live original: words, images, links, headings.
    if original is not None:
        before, after = word_count(original), word_count(markup)
        ratio = after / before if before else 1.0
        rep.stats["words"] = f"{before}>{after} ({ratio:.0%})"
        if ratio < rules.min_word_ratio:
            rep.issues.append(Issue("content_loss", f"visible words fell to {ratio:.0%} of original"))
        for src in images(original):
            if src not in markup:
                rep.issues.append(Issue("image_missing", f"image dropped: {src}"))
        competitor_hosts = [c.lower() for c in rules.competitors]
        for href in links(original):
            if href not in markup and not any(c in href.lower() for c in competitor_hosts):
                rep.issues.append(Issue("link_missing", f"link dropped: {href}"))
        new_heads = set(headings(markup))
        for h in headings(original):
            if h not in new_heads:
                rep.issues.append(Issue("heading_missing", f"heading dropped: {h}"))

    rep.stats["em_dash_raw"] = prose.count(EM_DASH) + prose.count(EN_DASH)
    rep.stats["hedges"] = hedges
    return rep
