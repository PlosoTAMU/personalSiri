"""Skill table (skills.toml) and the phrase matcher that picks a skill for an utterance."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from .config import ROOT, resolve

MATCH_CUTOFF = 85
FALLBACK = "fallback"

# Appended to follow-up turns so the first sentences of the reply are fit to speak.
DEFAULT_FOLLOWUP_SUFFIX = (
    "\n\n(This request was spoken. Do what it asks, then start your reply with a one or "
    "two sentence plain-speech summary of what you did or found.)"
)


@dataclass
class Skill:
    name: str
    kind: str  # "agent" or "script"
    phrases: list[str] = field(default_factory=list)
    ack: str = ""
    # agent
    cwd: Path | None = None
    prompt: str = ""
    speak_prompt: str = ""
    followup_suffix: str = DEFAULT_FOLLOWUP_SUFFIX
    allowed_tools: list[str] = field(default_factory=list)
    # Follow-ups containing one of confirm_words need a spoken "confirm". Until then
    # every turn runs with gated_tools denied, so the agent cannot act on its own.
    confirm_words: list[str] = field(default_factory=list)
    gated_tools: list[str] = field(default_factory=list)
    # script
    run: str = ""
    max_speak_chars: int | None = None
    timeout: int | None = None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", " ", text.lower())).strip()


def load(path: Path | None = None) -> dict[str, Skill]:
    """Skills from path, else $PLOSO_SKILLS, else skills.toml in the repo."""
    with open(path or os.environ.get("PLOSO_SKILLS") or ROOT / "skills.toml", "rb") as f:
        raw = tomllib.load(f)
    skills = {}
    for name, entry in raw.items():
        entry = dict(entry)
        if "cwd" in entry:
            entry["cwd"] = resolve(entry["cwd"])
        skill = Skill(name=name, **entry)
        if skill.kind not in ("agent", "script"):
            raise ValueError(f"skill {name}: kind must be 'agent' or 'script'")
        if skill.kind == "agent" and not skill.cwd:
            raise ValueError(f"skill {name}: agent skills need cwd")
        if skill.kind == "script" and not skill.run:
            raise ValueError(f"skill {name}: script skills need run")
        if skill.confirm_words and not skill.gated_tools:
            raise ValueError(f"skill {name}: confirm_words without gated_tools gates nothing")
        skills[name] = skill
    return skills


def match(text: str, skills: dict[str, Skill]) -> Skill | None:
    """Best skill whose phrase is (nearly) contained in the utterance, else None.

    token_set_ratio scores 100 whenever every word of a phrase appears in the utterance,
    so several phrases can tie. The longest phrase wins: "full daily brief" beats
    "daily brief".
    """
    said = normalize(text)
    best: tuple[float, int, Skill] | None = None
    for skill in skills.values():
        for phrase in skill.phrases:
            score = fuzz.token_set_ratio(said, normalize(phrase))
            rank = (score, len(phrase))
            if score >= MATCH_CUTOFF and (best is None or rank > best[:2]):
                best = (score, len(phrase), skill)
    return best[2] if best else None
