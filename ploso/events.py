"""Activity log the desktop window shows: what was heard, decided, run and answered."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import STATE_DIR

EVENTS_FILE = STATE_DIR / "events.jsonl"
MAX_BYTES = 1_000_000
MAX_TEXT = 4000


def emit(kind: str, text: str) -> None:
    """Append one event. kind: heard, route, tool, claude, reply, error."""
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if EVENTS_FILE.exists() and EVENTS_FILE.stat().st_size > MAX_BYTES:
            EVENTS_FILE.replace(EVENTS_FILE.with_suffix(".old"))
        line = json.dumps({"t": time.time(), "kind": kind, "text": text[:MAX_TEXT]})
        with open(EVENTS_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_new(offset: int) -> tuple[list[dict], int]:
    """Events appended after byte offset, and the new offset. A shrunk file restarts at 0."""
    try:
        size = EVENTS_FILE.stat().st_size
        if size < offset:
            offset = 0
        with open(EVENTS_FILE, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError:
        return [], offset
    end = data.rfind(b"\n") + 1  # leave a half-written line for next time
    events = []
    for line in data[:end].splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    return events, offset + end
