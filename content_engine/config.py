"""Gate thresholds, retry bounds and editorial rules.

Every number that decides whether an article moves forward lives here, so a
reviewer can audit the control settings in one place.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-haiku-4-5"


@dataclass(frozen=True)
class Gates:
    review_min: int = 9          # Reviewer score out of 10 (EEAT / accuracy / decision value)
    voice_min: int = 9           # Humanizer voice score out of 10
    info_gain_min: int = 7       # Information-gain score out of 8
    max_review_rounds: int = 3   # writer -> reviewer loops before the article is BLOCKED
    max_voice_rounds: int = 2    # humanizer attempts before BLOCKED
    max_info_gain_rounds: int = 2  # info-gain judge attempts (each failure sends a brief back to the writer)


@dataclass(frozen=True)
class EditorialRules:
    """Mechanical rules checked by code, not by a model."""

    banned_phrases: tuple[str, ...] = (
        "it's important to note",
        "it is important to note",
        "it's worth noting",
        "delve into",
        "dive into",
        "in today's fast-paced world",
        "game-changer",
        "in conclusion",
        "let me know in the comments",
        "look no further",
        "unlock the secrets",
    )
    competitors: tuple[str, ...] = ("RivalLedger Software", "rivalledger.example")
    hedge_words: tuple[str, ...] = ("can be", "may need", "might", "may be", "sometimes")
    max_hedges: int = 3
    min_word_ratio: float = 0.85   # upgraded article must keep at least 85% of the original's words
    allow_dash_entity_in_labels: bool = True  # "&#8212;" allowed only inside label separators


@dataclass(frozen=True)
class Settings:
    gates: Gates = field(default_factory=Gates)
    rules: EditorialRules = field(default_factory=EditorialRules)
    writer_model: str = DEFAULT_MODEL
    judge_model: str = DEFAULT_MODEL
    inject_faq_schema: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            writer_model=os.environ.get("CONTENT_ENGINE_WRITER_MODEL", DEFAULT_MODEL),
            judge_model=os.environ.get("CONTENT_ENGINE_JUDGE_MODEL", DEFAULT_MODEL),
        )
