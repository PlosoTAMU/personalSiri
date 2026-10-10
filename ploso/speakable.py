"""Turn an agent's markdown reply into text worth sending to a speech synthesiser."""

from __future__ import annotations

import re

_FENCE = re.compile(r"```.*?(```|\Z)", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKS = re.compile(r"[*_`#>]+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def speakable(text: str, max_chars: int = 0) -> str:
    """Drop code blocks, tables and markdown marks. max_chars > 0 cuts at a sentence end."""
    lines = []
    for line in _FENCE.sub(" ", text).splitlines():
        line = line.strip()
        if not line or line.startswith("|") or set(line) <= set("-=| :"):
            continue
        line = _MARKS.sub("", _LINK.sub(r"\1", _BULLET.sub("", line))).strip()
        if line:
            lines.append(line if line[-1] in ".!?:;," else line + ".")
    out = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if max_chars and len(out) > max_chars:
        ends = [m.end() for m in _SENTENCE_END.finditer(out, 0, max_chars)]
        out = out[: ends[-1]] if ends else out[:max_chars].rsplit(" ", 1)[0] + "."
    return out
