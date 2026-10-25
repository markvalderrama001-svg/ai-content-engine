import json
from pathlib import Path

import pytest

from content_engine.fake_llm import FakeLLM
from content_engine.orchestrator import Article

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class ScriptedLLM(FakeLLM):
    """FakeLLM with per-stage overrides, to force a gate to fail."""

    def __init__(self, **overrides):
        super().__init__()
        self.overrides = overrides

    def complete(self, *, stage, system, user, model, max_tokens=4000):
        key = stage.replace("-", "_")
        if key in self.overrides:
            self.calls.append(stage)
            value = self.overrides[key]
            return value(json.loads(user)) if callable(value) else value
        return super().complete(stage=stage, system=system, user=user, model=model, max_tokens=max_tokens)


@pytest.fixture
def notes():
    return json.loads((FIXTURES / "author_notes.json").read_text(encoding="utf-8"))


def load_article(slug, notes):
    site = json.loads((FIXTURES / "demo_site.json").read_text(encoding="utf-8"))
    post = next(p for p in site["posts"] if p["slug"] == slug)
    html = (FIXTURES / post["file"]).read_text(encoding="utf-8")
    return Article(slug, post["title"], html, notes[slug])


@pytest.fixture
def card(notes):
    return load_article("card-reconciliation", notes)


@pytest.fixture
def close(notes):
    return load_article("month-end-close", notes)


@pytest.fixture
def accrual(notes):
    return load_article("cash-vs-accrual", notes)
