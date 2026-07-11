"""Prompt template loader (§6.7, §8): versioned jinja2 templates in this
directory. Each file has a `## SYSTEM` and `## USER` section — this loader
splits on that heading and renders the user section with `**context`, so
prompt wording changes are reviewable diffs, not buried in Python strings.
"""

from __future__ import annotations

from pathlib import Path

import jinja2

from src.ai.ports.llm import LLMMessage

_DIR = Path(__file__).resolve().parent
_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_DIR),
    autoescape=False,
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_prompt(template_name: str, **context: object) -> LLMMessage:
    raw = _ENV.get_template(template_name).render(**context)
    system_part, _, user_part = raw.partition("\n## USER\n")
    system = system_part.removeprefix("## SYSTEM\n").strip()
    return LLMMessage(system=system, user=user_part.strip())
