from types import SimpleNamespace

import pytest

from content_engine.agents import ALL_AGENTS, AgentOutputError, parse_html, parse_json
from content_engine.config import Settings
from content_engine.llm import AnthropicLLM, get_llm


def test_every_agent_has_a_prompt():
    for agent in ALL_AGENTS:
        assert len(agent.system_prompt) > 200, agent.name


def test_parsers():
    assert parse_json('Sure:\n```json\n{"score": 9}\n```') == {"score": 9}
    assert parse_html("```html\n<p>x</p>\n```") == "<p>x</p>"
    with pytest.raises(AgentOutputError):
        parse_json("no json here")


def test_anthropic_backend_uses_configured_models(monkeypatch):
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"score": 9}')])

    llm = AnthropicLLM(client=SimpleNamespace(messages=Messages()))
    reviewer = next(a for a in ALL_AGENTS if a.name == "reviewer")
    out = reviewer.run(llm, Settings(judge_model="claude-haiku-4-5"), {"article_html": "<p>x</p>"})
    assert out == {"score": 9}
    assert calls[0]["model"] == "claude-haiku-4-5"
    assert "Reviewer agent" in calls[0]["system"]


def test_without_api_key_the_fake_llm_is_used(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert get_llm().name.startswith("fake")
