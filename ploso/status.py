"""Persistent enable state, daemon heartbeat, and the small desktop status control."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from . import events
from .config import STATE_DIR

STATUS_FILE = STATE_DIR / "status.json"
HEALTHY_FOR_SECONDS = 15
PROMPT_TEXT = "What can I help you with?"
PROMPT_SECONDS = 6
LOG_IDLE_SECONDS = 30  # the activity window hides this long after the last event
LOG_LABELS = {"heard": "HEARD", "route": "ROUTE", "tool": "RUN", "claude": "CLAUDE", "reply": "REPLY", "error": "ERROR"}
LOG_COLORS = {"heard": "#8ab4f8", "route": "#c58af9", "tool": "#fdd663", "claude": "#bdc1c6", "reply": "#81c995", "error": "#f28b82"}


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
        "woke": float(state.get("woke", 0)),
    }


def set_enabled(enabled: bool) -> None:
    state = _read()
    state["enabled"] = enabled
    state["changed"] = time.time()
    _write(state)


def signal_wake() -> None:
    """Record that the wake word was just heard so the desktop control can pop a prompt."""
    state = _read()
    state["woke"] = time.time()
    _write(state)


def prompt_visible(state: dict[str, Any], now: float | None = None) -> bool:
    return 0 <= (now or time.time()) - state["woke"] < PROMPT_SECONDS


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

    popup: dict[str, Any] = {"win": None, "woke": 0.0}

    log_win = tk.Toplevel(root)
    log_win.title("Ploso activity")
    log_win.attributes("-topmost", True)
    log_win.geometry("600x300+12+64")
    log_win.configure(bg="#202124")
    text = tk.Text(log_win, bg="#202124", fg="#e8eaed", font=("Monospace", 10), wrap="word",
                   state="disabled", borderwidth=0, padx=8, pady=6)
    scroll = tk.Scrollbar(log_win, command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    text.pack(side="left", fill="both", expand=True)
    for kind, color in LOG_COLORS.items():
        text.tag_configure(kind, foreground=color)
    try:  # start after old events so a restart does not pop the window open
        start = events.EVENTS_FILE.stat().st_size
    except OSError:
        start = 0
    offset = {"n": start}
    log_visible = {"on": False, "pinned": False, "last": 0.0, "woke": 0.0}
    log_win.withdraw()

    def show_events() -> None:
        new, offset["n"] = events.read_new(offset["n"])
        if not new:
            return
        log_visible["last"] = time.time()
        set_log_visible(True)
        text.configure(state="normal")
        for e in new:
            stamp = time.strftime("%H:%M:%S", time.localtime(e["t"]))
            label = LOG_LABELS.get(e["kind"], e["kind"])
            text.insert("end", f"{stamp} {label}: ", e["kind"])
            text.insert("end", e["text"] + "\n\n")
        text.configure(state="disabled")
        text.see("end")

    def set_log_visible(on: bool) -> None:
        if log_visible["on"] == on:
            return
        log_visible["on"] = on
        (log_win.deiconify if on else log_win.withdraw)()
        log_button.configure(text="Hide log" if on else "Show log")

    def toggle_log() -> None:
        """Manual show stays open until hidden by hand; hiding also clears the pin."""
        log_visible["pinned"] = not log_visible["on"]
        log_visible["last"] = time.time()
        set_log_visible(not log_visible["on"])

    def auto_show_hide(state: dict[str, Any]) -> None:
        if state["woke"] != log_visible["woke"]:
            log_visible["woke"] = state["woke"]
            log_visible["last"] = time.time()
            if time.time() - state["woke"] < PROMPT_SECONDS:  # a live wake, not an old one at startup
                set_log_visible(True)
        elif log_visible["on"] and not log_visible["pinned"] and time.time() - log_visible["last"] > LOG_IDLE_SECONDS:
            set_log_visible(False)

    log_button = tk.Button(root, text="Show log", padx=8, pady=4, command=toggle_log)
    log_button.pack(side="right", padx=(0, 7), pady=5)
    log_win.protocol("WM_DELETE_WINDOW", toggle_log)

    def show_prompt(state: dict[str, Any]) -> None:
        """Banner beside the control, shown for PROMPT_SECONDS after each wake word."""
        if prompt_visible(state) and popup["woke"] != state["woke"]:
            popup["woke"] = state["woke"]
            if popup["win"]:
                popup["win"].destroy()
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#1a73e8")
            tk.Label(win, text=PROMPT_TEXT, padx=18, pady=10, bg="#1a73e8", fg="white",
                     font=("Sans", 13, "bold")).pack()
            win.geometry(f"+{root.winfo_width() + 24}+12")
            popup["win"] = win
        elif popup["win"] and not prompt_visible(state):
            popup["win"].destroy()
            popup["win"] = None

    def refresh() -> None:
        state = snapshot()
        show_prompt(state)
        show_events()
        auto_show_hide(state)
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
