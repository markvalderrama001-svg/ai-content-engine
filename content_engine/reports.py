"""Console output and Markdown review reports."""
from __future__ import annotations

import os
import sys

from .orchestrator import PipelineResult, StageEvent
from .publisher import PublishResult

COLORS = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "grey": "90", "bold": "1"}


class Console:
    def __init__(self, color: bool | None = None):
        if color is None:
            color = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))
        self.color = color

    def c(self, text: str, name: str) -> str:
        return f"\x1b[{COLORS[name]}m{text}\x1b[0m" if self.color else text

    def line(self, text: str = "") -> None:
        print(text, flush=True)

    def event(self, ev: StageEvent) -> None:
        if ev.stage in ("READY", "BLOCKED"):
            tag = self.c(f"  => {ev.stage}", "green" if ev.stage == "READY" else "red")
            self.line(f"{tag}  {ev.detail}")
            return
        rnd = f"r{ev.round}" if ev.round else ""
        score = f"{ev.score}/{ev.max_score}" if ev.score is not None else ""
        if ev.threshold is not None:
            gate = f"{'PASS' if ev.passed else 'FAIL'} >={ev.threshold}"
            gate = self.c(f"{gate:<10}", "green" if ev.passed else "red")
        elif ev.passed is False:
            gate = self.c(f"{'FAIL':<10}", "red")
        else:
            gate = " " * 10
        detail = self.c(ev.detail, "grey") if ev.stage in ("source checks",) else ev.detail
        self.line(f"  {ev.stage:<14}{rnd:<4}{score:<7}{gate} {detail}")

    def publish(self, r: PublishResult) -> None:
        color = {"OK": "green", "DRY_RUN": "yellow"}.get(r.status, "red")
        self.line(f"  {'publish':<14}{'':<4}{'':<7}{self.c(f'{r.status:<10}', color)} {r.reason}")
        if r.backup:
            self.line(self.c(f"  {'':<25} backup: {r.backup}", "grey"))
        if r.checks:
            checks = " ".join(f"{k}={'ok' if v else 'MISMATCH'}" for k, v in r.checks.items())
            self.line(self.c(f"  {'':<25} verify: {checks}", "grey"))


def review_report_md(res: PipelineResult, pub: PublishResult | None = None) -> str:
    out = [f"# Review report: {res.title}", ""]
    status = res.status if res.ready else f"{res.status} at {res.blocked_at}"
    out += [f"**Slug:** `{res.slug}`  ", f"**Pipeline status:** {status}  "]
    if pub:
        out.append(f"**Publish:** {pub.status} ({pub.mode}), {pub.reason}  ")
    out.append("")

    out += ["## Gate scores", "", "| Gate | Score | Threshold | Result |", "|---|---|---|---|"]
    for ev in res.events:
        if ev.threshold is not None:
            rnd = f" r{ev.round}" if ev.round else ""
            out.append(f"| {ev.stage}{rnd} | {ev.score}/{ev.max_score} | {ev.threshold} | "
                       f"{'PASS' if ev.passed else 'FAIL'} |")
    out.append("")

    if res.source_checks and res.source_checks.issues:
        out += ["## Found on the live article (mechanical checks)", ""]
        for i in res.source_checks.issues:
            out.append(f"- **{i.code}**: {i.message}" + (f" (\"{i.excerpt}\")" if i.excerpt else ""))
        out.append("")

    for rv in res.reviews:
        out += [f"## Reviewer round {rv['round'] if rv['round'] < 100 else 're-verify'}: "
                f"{rv['score']}/10, {rv['verdict']}", ""]
        if rv.get("identity"):
            out.append(f"*Identity:* {rv['identity']}")
            out.append("")
        for label, key in (("What is working", "working"), ("What is holding it back", "holding_back"),
                           ("Required fixes", "required_fixes")):
            if rv.get(key):
                out += [f"**{label}:**", ""]
                out += [f"- {x}" for x in rv[key]]
                out.append("")

    if res.humanizer_notes:
        out += ["## Humanizer", ""] + [f"- {n}" for n in res.humanizer_notes] + [""]
    if res.info_gain:
        out += ["## Information gain", "", "| Dimension | Points |", "|---|---|"]
        out += [f"| {k} | {v} |" for k, v in res.info_gain["dimensions"].items()]
        out += [f"| **total** | **{res.info_gain['total']}/8** |", ""]
    if res.faq:
        out += [f"**FAQ schema:** {res.faq}", ""]
    if res.final_checks:
        out += [f"**Final mechanical checks:** {res.final_checks.summary()} "
                f"(words {res.final_checks.stats.get('words', 'n/a')})", ""]
    if not res.ready:
        out += ["## Blocked", "", res.reason, ""]
    return "\n".join(out)


def log_table(entries: list[dict], console: Console) -> None:
    console.line(f"  {'slug':<20}{'mode':<14}{'status':<15}{'drift':<7}{'review':<8}{'voice':<7}{'info':<6}{'modified':<21}")
    console.line("  " + "-" * 96)
    for e in entries:
        color = {"OK": "green", "DRY_RUN": "yellow"}.get(e["status"], "red")
        s = e.get("scores", {})
        drift = {True: "yes", False: "no", None: "-"}[e.get("live_changed_since_snapshot")]
        status = console.c(f"{e['status']:<15}", color)
        console.line(f"  {e['slug']:<20}{e['mode']:<14}{status}{drift:<7}"
                     f"{str(s.get('review', '-')) + '/10':<8}{str(s.get('voice', '-')) + '/10':<7}"
                     f"{str(s.get('info_gain', '-')) + '/8':<6}{e.get('modified') or '-':<21}")
        if not e.get("ok"):
            console.line(console.c(f"  {'':<20}reason: {e['reason']}", "grey"))
