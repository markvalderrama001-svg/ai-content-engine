"""Deterministic offline stand-in for the five agents.

It is not a language model. It applies the same contract the real agents
follow, using structural markers in the HTML and the author's notes:

- writer: tightens language, removes dashes, competitor sentences and
  unconfirmed first-person claims, and adds sections built from the author
  notes. Like a real first draft it is incomplete: it adds at most
  FIRST_PASS_SECTIONS new editorial sections on round 1, and on later rounds
  only what the brief asks for.
- reviewer: 2 points base + 1 per editorial element present + 1 for clean
  language, with the same guardrails as the real rubric.
- humanizer / polisher / info-gain judge: rule-based equivalents.

Same input, same output, every time, which is what the tests and the demo need.
"""
from __future__ import annotations

import html as htmllib
import json
import re

from .agents import verdict_for
from .htmltext import prose_text, sentences, slugify
from .mechanical import EM_DASH, EN_DASH, FIRST_PERSON_CLAIM

FIRST_PASS_SECTIONS = 4

# key -> (marker that proves it is present, keyword the reviewer uses in a fix)
EDITORIAL = {
    "identity": ('class="topic-identity"', "identity"),
    "wrong": ('id="what-people-get-wrong"', "what people get wrong"),
    "mistake": ('id="biggest-mistake"', "biggest mistake"),
    "hard_rule": ('class="hard-rule"', "hard rule"),
    "good_fit": ('id="who-this-fits"', "good fit"),
    "memorable": ('class="memorable-line"', "memorable line"),
}
INFO = {
    "data_log": ('class="data-log"', "proprietary_data"),
    "first_hand": ('class="first-hand"', "first_hand"),
    "rating": ('class="difficulty-rating"', "original_framework"),
    "expert_take": ('class="expert-take"', "expert_attribution"),
    "freshness": ('class="freshness"', "freshness"),
}
FRIENDLY = {"identity": "identity line", "wrong": "What People Get Wrong section",
            "mistake": "Biggest Mistake section", "hard_rule": "Hard Rule", "good_fit": "Good fit / Avoid if section",
            "memorable": "memorable line"}
IMPACT = {"identity": "the reader cannot tell what kind of task this is (caps the score at 7)",
          "wrong": "nothing separates it from competitor pages", "mistake": "no stakes, everything sounds easy",
          "hard_rule": "advice stays hedged", "good_fit": "facts only, no decision for the reader",
          "memorable": "accurate but forgettable (caps the score at 8)"}

# Banned phrases (a mechanical-check failure): the writer is told to remove these.
BANNED_FIXES = {
    r"It(?:'s| is) important to note that\s+": "",
    r"It(?:'s| is) worth noting that\s+": "",
    r"\bdelve into\b": "look at",
    r"\bdive into\b": "look at",
    r"In conclusion,\s+": "",
}
# Softer machine tells (not banned outright): the humanizer's job.
VOICE_TELLS = {"Moreover": r"\bMoreover,\s+", "Furthermore": r"\bFurthermore,\s+",
               "Additionally": r"\bAdditionally,\s+"}


def _esc(s: str) -> str:
    return htmllib.escape(s, quote=False)


def _build(key: str, notes: dict) -> str | None:
    n = notes
    if key == "identity" and n.get("identity_line"):
        return f'<p class="topic-identity"><strong>{_esc(n["identity_line"])}</strong></p>'
    if key == "memorable" and n.get("memorable_line"):
        return f'<p class="memorable-line"><strong>{_esc(n["memorable_line"])}</strong></p>'
    if key == "wrong" and n.get("what_people_get_wrong"):
        return f'<h2 id="what-people-get-wrong">What People Get Wrong</h2>\n<p>{_esc(n["what_people_get_wrong"])}</p>'
    if key == "mistake" and n.get("biggest_mistake"):
        return f'<h2 id="biggest-mistake">The Biggest Mistake</h2>\n<p>{_esc(n["biggest_mistake"])}</p>'
    if key == "hard_rule" and n.get("hard_rule"):
        return f'<div class="hard-rule"><p><strong>Hard Rule:</strong> {_esc(n["hard_rule"])}</p></div>'
    if key == "good_fit" and n.get("good_fit_if"):
        good = "".join(f"<li>{_esc(x)}</li>" for x in n["good_fit_if"])
        avoid = "".join(f"<li>{_esc(x)}</li>" for x in n.get("avoid_if", []))
        return ('<h2 id="who-this-fits">Who This Fits</h2>\n'
                f"<h3>Good fit if</h3>\n<ul>{good}</ul>\n<h3>Avoid if</h3>\n<ul>{avoid}</ul>")
    if key == "data_log" and n.get("data_log"):
        rows = "".join(f"<tr><td>{_esc(a)}</td><td>{_esc(b)}</td></tr>" for a, b in n["data_log"])
        return ('<h2 id="by-the-numbers">By the Numbers</h2>\n'
                f'<table class="data-log"><tr><th>Measured</th><th>Value</th></tr>{rows}</table>')
    if key == "first_hand" and n.get("first_hand"):
        return f'<p class="first-hand">{_esc(n["first_hand"])}</p>'
    if key == "rating" and n.get("difficulty_rating"):
        return (f'<div class="difficulty-rating"><p><strong>Difficulty Rating:</strong> '
                f'{_esc(n["difficulty_rating"])}</p></div>')
    if key == "expert_take" and n.get("expert_take"):
        return (f'<div class="expert-take"><p><strong>Expert Take | {_esc(n.get("author", "Site Editor"))}'
                f'</strong></p><p>{_esc(n["expert_take"])}</p></div>')
    if key == "freshness" and n.get("freshness"):
        return f'<p class="freshness"><em>{_esc(n["freshness"])}</em></p>'
    return None


def _insert(markup: str, block: str, key: str) -> str:
    if key in ("identity", "memorable", "freshness"):
        # Top-of-article lines go after any identity line already placed.
        anchor = re.search(r'<p class="(?:topic-identity|memorable-line)">.*?</p>\n', markup)
        if anchor and key != "identity":
            return markup[:anchor.end()] + block + "\n" + markup[anchor.end():]
        return block + "\n" + markup
    faq = re.search(r'<h2[^>]*id="faq"', markup)
    if faq:
        return markup[:faq.start()] + block + "\n" + markup[faq.start():]
    return markup + "\n" + block


def _clean_language(markup: str, notes: dict, rules: dict) -> str:
    out = re.sub(rf"\s*[{EM_DASH}{EN_DASH}]\s*", ", ", markup)
    for pat, repl in BANNED_FIXES.items():
        out = re.sub(pat, repl, out, flags=re.I)
    out = re.sub(r"(<p[^>]*>)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    out = re.sub(r"\bcan be\b", "is", out)
    out = re.sub(r"\bmay need\b", "needs", out)
    competitors = [c.lower() for c in rules.get("competitors", [])]
    disclosure_used = 'class="first-hand-disclosure"' in out

    def fix_paragraph(m: re.Match) -> str:
        nonlocal disclosure_used
        body = m.group(2)
        kept = []
        for sent in re.split(r"(?<=[.!?])\s+", body):
            low = sent.lower()
            if any(c in low for c in competitors):
                continue
            if not notes.get("first_person_confirmed") and FIRST_PERSON_CLAIM.search(sent):
                if not disclosure_used and notes.get("disclosure"):
                    kept.append(_esc(notes["disclosure"]))
                    disclosure_used = True
                continue
            kept.append(sent)
        text = " ".join(kept).strip()
        return f"<p{m.group(1)}>{text}</p>" if text else ""

    out = re.sub(r"<p(\b[^>]*)>(.*?)</p>", fix_paragraph, out, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", out)


class FakeLLM:
    name = "fake (deterministic, offline)"

    def __init__(self):
        self.calls: list[str] = []

    def complete(self, *, stage: str, system: str, user: str, model: str, max_tokens: int = 4000) -> str:
        self.calls.append(stage)
        payload = json.loads(user)
        handler = {
            "writer": self._writer,
            "reviewer": self._reviewer,
            "polisher": self._polisher,
            "humanizer": self._humanizer,
            "info-gain-judge": self._info_gain,
        }[stage]
        return handler(payload)

    # --- writer ---------------------------------------------------------
    def _writer(self, p: dict) -> str:
        notes, brief = p.get("author_notes", {}), " ".join(p.get("brief", [])).lower()
        markup = _clean_language(p["article_html"], notes, p.get("rules", {}))
        added = 0
        for key, (marker, keyword) in EDITORIAL.items():
            if marker in markup:
                continue
            if p.get("round", 1) == 1:
                wanted = added < FIRST_PASS_SECTIONS   # incomplete first draft, by design
            else:
                wanted = keyword in brief              # later rounds: only what the brief asks for
            block = _build(key, notes) if wanted else None
            if block:
                markup = _insert(markup, block, key)
                added += 1
        for key, (marker, dimension) in INFO.items():
            if marker in markup:
                continue
            if p.get("round", 1) == 1 or dimension in brief:
                block = _build(key, notes)
                if block:
                    markup = _insert(markup, block, key)
        return markup

    # --- reviewer -------------------------------------------------------
    def _reviewer(self, p: dict) -> str:
        markup = p["article_html"]
        present = [k for k, (marker, _) in EDITORIAL.items() if marker in markup]
        missing = [k for k in EDITORIAL if k not in present]
        prose = prose_text(markup).lower()
        clean = EM_DASH not in prose and len(re.findall(r"\b(can be|may need|might)\b", prose)) <= 1
        score = 2 + len(present) + (1 if clean else 0)
        if "memorable" in missing:
            score = min(score, 8)
        if "identity" in missing:
            score = min(score, 7)
        labels = {
            "identity": "Add identity: open with what kind of task this is and why that matters",
            "wrong": "Add section: What People Get Wrong - correct the real misconception for this topic",
            "mistake": "Add section: Biggest Mistake - the most common failure and its consequence",
            "hard_rule": "Add hard rule: one direct rule, no hedging",
            "good_fit": "Add decision section: Good fit if / Avoid if bullets",
            "memorable": "Add memorable line: one short, true line specific to the topic",
        }
        return json.dumps({
            "score": score,
            "verdict": verdict_for(score),
            "identity": p.get("author_notes", {}).get("identity", "unclear"),
            "working": [f"{FRIENDLY[k]} is present" for k in present] + (["clean, direct language"] if clean else []),
            "holding_back": [f"no {FRIENDLY[k]}: {IMPACT[k]}" for k in missing] + ([] if clean else ["hedging or dashes in prose"]),
            "required_fixes": [labels[k] for k in missing] + ([] if clean else ["Tighten language: remove hedges and dashes"]),
        })

    # --- polisher -------------------------------------------------------
    def _polisher(self, p: dict) -> str:
        def add_id(m: re.Match) -> str:
            attrs, inner = m.group(1), m.group(2)
            if "id=" in attrs:
                return m.group(0)
            return f'<h2{attrs} id="{slugify(inner)}">{inner}</h2>'

        return re.sub(r"<h2(\b[^>]*)>(.*?)</h2>", add_id, p["article_html"], flags=re.S)

    # --- humanizer ------------------------------------------------------
    def _humanizer(self, p: dict) -> str:
        markup, notes = p["article_html"], []
        for word, pat in VOICE_TELLS.items():
            markup, n = re.subn(pat, "", markup)
            if n:
                notes.append(f"removed filler transition '{word},' x{n}")
        # Re-capitalise a sentence start left lower-case by a removal.
        markup = re.sub(r"(<p[^>]*>)([a-z])", lambda m: m.group(1) + m.group(2).upper(), markup)
        prose = prose_text(markup)
        sents = sentences(prose)
        mean = sum(len(s.split()) for s in sents) / max(1, len(sents))
        score = 10
        score -= 2 * (prose.count(EM_DASH) + prose.count(EN_DASH))
        score -= 1 if mean > 20 else 0
        score -= 1 if mean > 24 else 0
        score -= 1 if not re.search(r"\bI\b", prose) else 0  # no author voice at all
        notes.append(f"mean sentence length {mean:.1f} words over {len(sents)} sentences")
        return json.dumps({"voice_score": max(1, score), "notes": notes, "html": markup})

    # --- info-gain judge -----------------------------------------------
    def _info_gain(self, p: dict) -> str:
        markup, notes = p["article_html"], p.get("author_notes", {})
        dims = {
            "proprietary_data": 2 if 'class="data-log"' in markup else 0,
            "first_hand": (2 if notes.get("first_person_confirmed") else 1) if 'class="first-hand"' in markup else 0,
            "original_framework": 2 if 'class="difficulty-rating"' in markup else 0,
            "expert_attribution": 1 if 'class="expert-take"' in markup else 0,
            "freshness": 1 if 'class="freshness"' in markup else 0,
        }
        hints = {
            "proprietary_data": "proprietary_data: add the author's own measured data (data log)",
            "first_hand": "first_hand: add a confirmed first-hand or client-level observation",
            "original_framework": "original_framework: add a difficulty rating or tier placement",
            "expert_attribution": "expert_attribution: add an Expert Take with the author's name",
            "freshness": "freshness: add a dated update note (recent research or reclassification)",
        }
        full = {"proprietary_data": 2, "first_hand": 2, "original_framework": 2, "expert_attribution": 1, "freshness": 1}
        return json.dumps({"dimensions": dims, "missing": [hints[k] for k, v in dims.items() if v < full[k]]})
