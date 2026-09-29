"""Loads versioned prompt files from ``src/prompts``. Prompts are never hardcoded."""

import re
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")


def load_prompt(agent: str, version: str, variables: dict[str, str] | None = None) -> str:
    if not (_SAFE_NAME.match(agent) and _SAFE_NAME.match(version)):
        raise ValueError("invalid prompt identifier")
    text = (PROMPTS_DIR / agent / f"{version}.txt").read_text(encoding="utf-8")
    for key, value in (variables or {}).items():
        text = text.replace("{{" + key + "}}", value)
    return text
