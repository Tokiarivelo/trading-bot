"""Cleanup helpers for raw LLM completions, shared by `pdf_to_strategy.py`
and `refinement_loop.py`.

Prompts tell the model to output "no markdown fences, no commentary", but
that instruction isn't always obeyed — a stray preamble line (a title, an
apology, a one-line summary) left in front of the actual code is exactly
what turns into "unterminated string literal" or "invalid syntax" a few
lines in once `sandbox.py`'s `ast.parse` gets hold of it. These helpers
recover the payload regardless of whether the model wrapped it in a fence,
prefixed it with commentary, or both.
"""

from __future__ import annotations

import re

_FENCE_RE = re.compile(r"```(?:\w+)?\n(.*?)\n```", re.DOTALL)
_CODE_START_RE = re.compile(r"^(?:import|from|class|def|@)\b", re.MULTILINE)


def strip_fences(raw: str) -> str:
    """Recover the contents of a markdown code fence found anywhere in
    `raw`, tolerating preamble/trailing commentary around it. Falls back to
    the trimmed raw text when there's no fence."""
    text = raw.strip()
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text


def extract_python_code(raw: str) -> str:
    """Like `strip_fences`, but also drops any unfenced preamble line before
    the code proper — the first line matching `import`/`from`/`class`/`def`/
    a decorator wins, and everything before it is discarded."""
    text = strip_fences(raw)
    match = _CODE_START_RE.search(text)
    if match and match.start() > 0:
        text = text[match.start() :]
    return text.strip()
