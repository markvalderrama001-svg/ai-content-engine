"""LLM backends.

`AnthropicLLM` calls the Messages API when ANTHROPIC_API_KEY is set.
`FakeLLM` (see fake_llm.py) is a deterministic offline stand-in with the same
interface, so the whole pipeline runs and is tested without a network.
"""
from __future__ import annotations

import os
from typing import Protocol


class LLM(Protocol):
    name: str

    def complete(self, *, stage: str, system: str, user: str, model: str, max_tokens: int = 4000) -> str:
        ...


class AnthropicLLM:
    name = "anthropic"

    def __init__(self, client=None):
        if client is None:
            import anthropic  # optional dependency, imported only when used

            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        self.client = client

    def complete(self, *, stage: str, system: str, user: str, model: str, max_tokens: int = 4000) -> str:
        resp = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")


def get_llm(force_fake: bool = False) -> LLM:
    from .fake_llm import FakeLLM

    if force_fake or not os.environ.get("ANTHROPIC_API_KEY"):
        return FakeLLM()
    return AnthropicLLM()
