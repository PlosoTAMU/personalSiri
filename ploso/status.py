"""Persistent enable state, daemon heartbeat, and the small desktop status control."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .config import STATE_DIR

STATUS_FILE = STATE_DIR / "status.json"
HEALTHY_FOR_SECONDS = 15


def _read() -> dict[str, Any]:
    try:
        data = json.loads(STATUS_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict[str, Any]) -> None:
    """Atomically replace the state file so the UI never reads a partial update."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="status-", suffix=".json", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, STATUS_FILE)
    finally:
        try:
            Path(name).unlink()
        except FileNotFoundError:
            pass


def snapshot() -> dict[str, Any]:
    """Return the durable enable selection and most recent daemon health report."""
    state = _read()
    return {
        "enabled": bool(state.get("enabled", True)),
        "heartbeat": float(state.get("heartbeat", 0)),
        "error": str(state.get("error", "")),
    }


def set_enabled(enabled: bool) -> None:
    state = _read()
    state["enabled"] = enabled
    state["changed"] = time.time()
    _write(state)


def heartbeat(*, error: str = "") -> None:
    state = _read()
    state.setdefault("enabled", True)
    state["heartbeat"] = time.time()
    state["error"] = error
    _write(state)


def healthy(state: dict[str, Any], now: float | None = None) -> bool:
    return bool(state["heartbeat"]) and (now or time.time()) - state["heartbeat"] < HEALTHY_FOR_SECONDS


def run_window(on_toggle: Callable[[bool], None] = set_enabled) -> None:
    """Show the always-visible top-left control. Requires an active graphical session."""
    try:
        import tkinter as tk
    except ImportError as exc:  # pragma: no cover - platform packaging dependent
        raise RuntimeError("Tk is required for the Ploso desktop status control") from exc

    root = tk.Tk()
    root.title("Ploso Siri")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.geometry("+12+12")
    root.configure(bg="#202124")

    label = tk.Label(root, padx=12, pady=7, anchor="w", bg="#202124", fg="white", font=("Sans", 11, "bold"))
    label.pack(side="left")
    button = tk.Button(root, padx=10, pady=4)
    button.pack(side="right", padx=(0, 7), pady=5)

    def refresh() -> None:
        state = snapshot()
        is_enabled = state["enabled"]
        if is_enabled:
            detail = "listening" if healthy(state) else "starting or reconnecting"
            label.configure(text=f"Ploso Siri is enabled — {detail}", fg="#b9f6ca")
            button.configure(text="Disable", command=lambda: on_toggle(False))
        else:
            label.configure(text="Ploso Siri is disabled", fg="#ffcc80")
            button.configure(text="Enable", command=lambda: on_toggle(True))
        root.after(1000, refresh)

    refresh()
    root.mainloop()
