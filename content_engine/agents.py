"""Agent stage definitions.

Each agent is a system prompt (prompts/*.md), a model role and an output
parser. Writing, reviewing, polishing, humanizing and judging are separate
agents on purpose: one model asked to write and grade its own work grades
generously.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .llm import LLM

PROMPTS = Path(__file__).parent / "prompts"


class AgentOutputError(ValueError):
    """The model returned something the pipeline cannot parse. Treated as a failed round."""


def parse_json(text: str) -> dict:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AgentOutputError(f"expected JSON, got: {text[:120]!r}") from exc
    if not isinstance(data, dict):
        raise AgentOutputError("expected a JSON object")
    return data


def parse_html(text: str) -> str:
    fenced = re.search(r"```(?:html)?\s*(.*?)```", text, re.S)
    out = (fenced.group(1) if fenced else text).strip()
    if "<" not in out:
        raise AgentOutputError("expected HTML")
    return out


@dataclass(frozen=True)
class Agent:
    name: str
    prompt_file: str
    role: str        # "writer" or "judge" -> picks the model from Settings
    output: str      # "html" or "json"
    max_tokens: int = 4000

    @property
    def system_prompt(self) -> str:
        return (PROMPTS / self.prompt_file).read_text(encoding="utf-8")

    def run(self, llm: LLM, settings: Settings, payload: dict):
        model = settings.writer_model if self.role == "writer" else settings.judge_model
        raw = llm.complete(stage=self.name, system=self.system_prompt,
                           user=json.dumps(payload, ensure_ascii=False), model=model,
                           max_tokens=self.max_tokens)
        return parse_html(raw) if self.output == "html" else parse_json(raw)


WRITER = Agent("writer", "writer.md", "writer", "html", max_tokens=16000)
REVIEWER = Agent("reviewer", "reviewer.md", "judge", "json")
POLISHER = Agent("polisher", "polisher.md", "writer", "html", max_tokens=16000)
HUMANIZER = Agent("humanizer", "humanizer.md", "writer", "json", max_tokens=16000)
INFO_GAIN_JUDGE = Agent("info-gain-judge", "info_gain_judge.md", "judge", "json")

ALL_AGENTS = (WRITER, REVIEWER, POLISHER, HUMANIZER, INFO_GAIN_JUDGE)

INFO_GAIN_MAX = {"proprietary_data": 2, "first_hand": 2, "original_framework": 2,
                 "expert_attribution": 1, "freshness": 1}


def verdict_for(score: int) -> str:
    if score >= 9:
        return "Top 1 Contender"
    if score == 8:
        return "Top 3 Capable"
    if score >= 6:
        return "Page 1 Possible"
    return "Not Competitive"
