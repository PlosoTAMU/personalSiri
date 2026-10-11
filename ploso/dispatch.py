"""Run a headless Claude Code agent or a script and return its text."""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

from .config import ROOT

log = logging.getLogger(__name__)


@dataclass
class Result:
    ok: bool
    text: str
    session_id: str | None = None
    error: str = ""  # "timeout", "failed", "missing"


def find_claude(name: str = "claude") -> str | None:
    """systemd user services get a short PATH, so also look where the installer puts it."""
    return shutil.which(name) or shutil.which(name, path=str(Path.home() / ".local/bin"))


def agent_command(
    claude: str,
    prompt: str,
    *,
    resume: str | None = None,
    allowed: list[str] | None = None,
    denied: list[str] | None = None,
    model: str = "",
    permission_mode: str = "",
    stream: bool = False,
) -> list[str]:
    # The prompt stays directly after -p: the tool flags take several values and would
    # swallow a positional that came after them.
    cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose"] if stream else [
        claude, "-p", prompt, "--output-format", "json"]
    if resume:
        cmd += ["--resume", resume]
    if model:
        cmd += ["--model", model]
    if permission_mode:
        cmd += ["--permission-mode", permission_mode]
    if allowed:
        cmd += ["--allowedTools", *allowed]
    if denied:
        cmd += ["--disallowedTools", *denied]
    return cmd


def _describe_tool(name: str, args: dict) -> str:
    for key in ("command", "file_path", "path", "pattern", "url", "query", "description"):
        if args.get(key):
            return f"{name}: {str(args[key])[:300]}"
    return name


def announce(event: dict, on_event: Callable[[str, str], None]) -> None:
    """Turn one stream-json line into tool/claude events for the activity window."""
    if event.get("type") != "assistant":
        return
    for block in (event.get("message") or {}).get("content") or []:
        if block.get("type") == "tool_use":
            on_event("tool", _describe_tool(block.get("name", "tool"), block.get("input") or {}))
        elif block.get("type") == "text" and block.get("text", "").strip():
            on_event("claude", block["text"].strip())


def _stream(cmd, cwd, timeout, on_event):
    """Run claude with stream-json, report each step, return (result event, exit code, timed out)."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    timed_out = threading.Event()
    timer = threading.Timer(timeout, lambda: (timed_out.set(), proc.kill()))
    timer.start()
    final, tail = None, []
    try:
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                tail = (tail + [line])[-20:]
                continue
            if event.get("type") == "result":
                final = event
            else:
                announce(event, on_event)
        proc.wait()
    finally:
        timer.cancel()
    if final is None and not timed_out.is_set():
        log.error("claude exit %s: %s", proc.returncode, "".join(tail)[-2000:])
    return final, proc.returncode, timed_out.is_set()


def run_agent(
    prompt: str,
    cwd: Path,
    *,
    resume: str | None = None,
    allowed: list[str] | None = None,
    denied: list[str] | None = None,
    model: str = "",
    claude: str = "claude",
    timeout: int = 600,
    permission_mode: str = "",
    on_event: Callable[[str, str], None] | None = None,
) -> Result:
    exe = find_claude(claude)
    if not exe:
        return Result(False, "", error="missing")
    if not Path(cwd).is_dir():
        log.error("skill directory does not exist: %s", cwd)
        return Result(False, "", error="missing")
    cmd = agent_command(exe, prompt, resume=resume, allowed=allowed, denied=denied, model=model,
                        permission_mode=permission_mode, stream=on_event is not None)
    log.info("agent in %s: %s", cwd, shlex.join(cmd[1:]))
    if on_event is None:
        try:
            proc = subprocess.run(
                cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return Result(False, "", session_id=resume, error="timeout")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            log.error("claude exit %s: %s", proc.returncode, (proc.stderr or proc.stdout)[-2000:])
            return Result(False, "", session_id=resume, error="failed")
        returncode = proc.returncode
    else:
        data, returncode, timed_out = _stream(cmd, cwd, timeout, on_event)
        if timed_out:
            return Result(False, "", session_id=resume, error="timeout")
        if data is None:
            return Result(False, "", session_id=resume, error="failed")
    for denial in data.get("permission_denials") or []:
        log.warning("denied: %s", denial.get("tool_input"))
    ok = returncode == 0 and not data.get("is_error")
    if not ok:
        log.error("claude reported an error: %s", str(data.get("result"))[:2000])
    return Result(
        ok,
        data.get("result") or "",
        session_id=data.get("session_id") or resume,
        error="" if ok else "failed",
    )


def run_script(command: str, *, timeout: int = 120) -> Result:
    """Run a script skill from the repo root. A leading `python` means this venv's Python."""
    cmd = shlex.split(command)
    if cmd and cmd[0] == "python":
        cmd[0] = sys.executable
    log.info("script: %s", shlex.join(cmd))
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return Result(False, "", error="timeout")
    except FileNotFoundError:
        return Result(False, "", error="missing")
    if proc.returncode != 0:
        log.error("script exit %s: %s", proc.returncode, proc.stderr[-2000:])
        # A script may print a sentence for the user before exiting non-zero.
        return Result(False, proc.stdout.strip(), error="failed")
    return Result(True, proc.stdout.strip())
