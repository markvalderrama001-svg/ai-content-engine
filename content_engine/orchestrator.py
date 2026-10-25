"""The editorial pipeline: Writer -> Reviewer -> Polisher -> Humanizer -> Info-gain gate.

Rules the orchestrator enforces (the agents cannot opt out):
- Every gate has a numeric threshold from config.Gates. Scores are clamped and
  recomputed here; a judge's own arithmetic is never trusted.
- Every loop is bounded. When the bound is hit the article is BLOCKED with a
  reason, never waved through.
- Mechanical checks run after every stage that edits text (critic). A failing
  check is fed back to the writer as a required fix (fixer) and re-checked
  (verifier). A late stage that breaks a check is rolled back.
- After an information-gain fix, the reviewer re-scores the article so a fix
  cannot quietly undo an earlier pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .agents import (HUMANIZER, INFO_GAIN_JUDGE, INFO_GAIN_MAX, POLISHER, REVIEWER, WRITER,
                     AgentOutputError, verdict_for)
from .config import Settings
from .faq_schema import inject_faq_schema
from .htmltext import word_count
from .llm import LLM
from .mechanical import MechanicalReport, check_article

STANDARD_BRIEF = [
    "Upgrade the article using the author notes: identity, what people get wrong, biggest mistake, "
    "hard rule, good fit / avoid, memorable line, and the information-gain material.",
]


@dataclass
class Article:
    slug: str
    title: str
    html: str
    notes: dict = field(default_factory=dict)


@dataclass
class StageEvent:
    stage: str
    round: int | None
    detail: str
    score: int | None = None
    max_score: int | None = None
    threshold: int | None = None
    passed: bool | None = None


@dataclass
class PipelineResult:
    slug: str
    title: str
    status: str = "RUNNING"          # READY | BLOCKED
    blocked_at: str | None = None
    reason: str = ""
    final_html: str = ""
    events: list[StageEvent] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    info_gain: dict = field(default_factory=dict)
    humanizer_notes: list[str] = field(default_factory=list)
    source_checks: MechanicalReport | None = None
    final_checks: MechanicalReport | None = None
    faq: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "READY"


def _clamp(value, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return lo


def run_article(article: Article, llm: LLM, settings: Settings,
                emit: Callable[[StageEvent], None] | None = None) -> PipelineResult:
    g, rules = settings.gates, settings.rules
    confirmed = bool(article.notes.get("first_person_confirmed"))
    res = PipelineResult(slug=article.slug, title=article.title)

    def event(ev: StageEvent) -> None:
        res.events.append(ev)
        if emit:
            emit(ev)

    def checks(markup: str) -> MechanicalReport:
        return check_article(markup, rules, first_person_confirmed=confirmed, original=article.html)

    def block(stage: str, reason: str) -> PipelineResult:
        res.status, res.blocked_at, res.reason = "BLOCKED", stage, reason
        event(StageEvent("BLOCKED", None, f"{stage}: {reason}", passed=False))
        return res

    def payload(markup: str, brief: list[str], rnd: int) -> dict:
        return {"title": article.title, "article_html": markup, "author_notes": article.notes,
                "brief": brief, "round": rnd,
                "rules": {"competitors": list(rules.competitors), "banned_phrases": list(rules.banned_phrases)}}

    def review(markup: str, rnd: int, label: str = "reviewer") -> tuple[int, dict]:
        try:
            rv = REVIEWER.run(llm, settings, payload(markup, [], rnd))
        except AgentOutputError as exc:
            rv = {"score": 0, "required_fixes": [], "holding_back": [f"unparseable review: {exc}"]}
        score = _clamp(rv.get("score"), 0, 10)
        rv["score"], rv["verdict"], rv["round"] = score, verdict_for(score), rnd
        res.reviews.append(rv)
        return score, rv

    # Source checks brief the writer on what the live article already gets wrong.
    res.source_checks = check_article(article.html, rules, first_person_confirmed=confirmed)
    event(StageEvent("source checks", None, res.source_checks.summary()
                     if res.source_checks.issues else "clean"))
    brief = STANDARD_BRIEF + [f"Fix: {i.message}" for i in res.source_checks.issues if i.blocking]

    # 1. Writer <-> Reviewer loop (critic-fixer-verifier), bounded.
    draft, passed = article.html, False
    for rnd in range(1, g.max_review_rounds + 1):
        try:
            draft = WRITER.run(llm, settings, payload(draft, brief, rnd))
        except AgentOutputError as exc:
            event(StageEvent("writer", rnd, f"unusable output ({exc}); round counted", passed=False))
            continue
        mech = checks(draft)
        event(StageEvent("writer", rnd, f"draft {word_count(draft):,} words | checks {mech.summary()}",
                         passed=mech.passed))
        score, rv = review(draft, rnd)
        ok = score >= g.review_min and mech.passed
        fixes = rv.get("required_fixes", []) + [f"Fix: {i.message}" for i in mech.issues if i.blocking]
        tail = "" if ok else f" -> {len(fixes)} required fix(es) back to writer"
        event(StageEvent("reviewer", rnd, f"{rv['verdict']}{tail}", score, 10, g.review_min, ok))
        if ok:
            passed = True
            break
        brief = fixes
    if not passed:
        return block("review gate", f"score below {g.review_min}/10 after {g.max_review_rounds} rounds")
    res.scores["review"] = score

    # 2. Polisher (consistency only). Rolled back if it breaks a mechanical check.
    polished = POLISHER.run(llm, settings, payload(draft, [], 1))
    mech = checks(polished)
    if mech.passed:
        draft = polished
        event(StageEvent("polisher", None, "consistency pass applied | checks PASS", passed=True))
    else:
        event(StageEvent("polisher", None, f"rolled back: {mech.summary()}", passed=False))

    # 3. Humanizer, bounded. The rewrite is re-checked by code before it is accepted.
    feedback: list[str] = []
    for rnd in range(1, g.max_voice_rounds + 1):
        try:
            out = HUMANIZER.run(llm, settings, payload(draft, feedback, rnd))
            candidate = str(out.get("html", ""))
            voice = _clamp(out.get("voice_score"), 0, 10)
        except AgentOutputError as exc:
            out, candidate, voice = {"notes": [str(exc)]}, draft, 0
        cand_mech = checks(candidate) if candidate else None
        if cand_mech is None or not cand_mech.passed:
            voice = min(voice, 6)  # self-score overridden: code found machine tells or breakage
        ok = voice >= g.voice_min
        event(StageEvent("humanizer", rnd, "rewrite accepted" if ok else "rewrite rejected",
                         voice, 10, g.voice_min, ok))
        if ok:
            draft = candidate
            res.humanizer_notes = list(out.get("notes", []))
            break
        feedback = list(out.get("notes", [])) + ([i.message for i in cand_mech.issues] if cand_mech else [])
    else:
        return block("voice gate", f"voice below {g.voice_min}/10 after {g.max_voice_rounds} rounds")
    res.scores["voice"] = voice

    # 4. Information-gain gate, bounded. A failure sends `missing` back to the writer,
    #    then the reviewer re-verifies before the judge scores again.
    for rnd in range(1, g.max_info_gain_rounds + 1):
        try:
            ig = INFO_GAIN_JUDGE.run(llm, settings, payload(draft, [], rnd))
        except AgentOutputError:
            ig = {"dimensions": {}, "missing": ["judge output unparseable"]}
        dims = {k: _clamp(ig.get("dimensions", {}).get(k), 0, mx) for k, mx in INFO_GAIN_MAX.items()}
        total = sum(dims.values())
        ok = total >= g.info_gain_min
        detail = " ".join(f"{k.split('_')[0]} {v}/{INFO_GAIN_MAX[k]}" for k, v in dims.items())
        event(StageEvent("info-gain", rnd, detail, total, 8, g.info_gain_min, ok))
        res.info_gain = {"dimensions": dims, "total": total, "missing": ig.get("missing", [])}
        if ok:
            break
        if rnd == g.max_info_gain_rounds:
            return block("info-gain gate", f"{total}/8 after {rnd} rounds; missing: "
                         + "; ".join(ig.get("missing", [])))
        draft = WRITER.run(llm, settings, payload(draft, list(ig.get("missing", [])), 100 + rnd))
        score, rv = review(draft, 100 + rnd)
        mech = checks(draft)
        event(StageEvent("reviewer", None, "re-verify after info-gain fix", score, 10, g.review_min,
                         score >= g.review_min and mech.passed))
        if score < g.review_min or not mech.passed:
            return block("review gate", "info-gain fix dropped the review score or broke a check")
    res.scores["info_gain"] = total

    # 5. FAQ schema (visible FAQ -> FAQPage JSON-LD), idempotent.
    if settings.inject_faq_schema:
        fr = inject_faq_schema(draft)
        draft, res.faq = fr.html, fr.reason
        event(StageEvent("faq-schema", None, fr.reason, passed=True))

    # 6. Final verifier: the publish candidate must pass every mechanical check.
    res.final_checks = checks(draft)
    event(StageEvent("final checks", None, res.final_checks.summary(), passed=res.final_checks.passed))
    if not res.final_checks.passed:
        return block("final checks", res.final_checks.summary())
    res.final_html, res.status = draft, "READY"
    event(StageEvent("READY", None, "eligible to publish", passed=True))
    return res
