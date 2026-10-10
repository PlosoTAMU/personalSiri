"""Run a headless Claude Code agent or a script and return its text."""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
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
) -> list[str]:
    # The prompt stays directly after -p: the tool flags take several values and would
    # swallow a positional that came after them.
    cmd = [claude, "-p", prompt, "--output-format", "json"]
    if resume:
        cmd += ["--resume", resume]
    if model:
        cmd += ["--model", model]
    if allowed:
        cmd += ["--allowedTools", *allowed]
    if denied:
        cmd += ["--disallowedTools", *denied]
    return cmd


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
) -> Result:
    exe = find_claude(claude)
    if not exe:
        return Result(False, "", error="missing")
    if not Path(cwd).is_dir():
        log.error("skill directory does not exist: %s", cwd)
        return Result(False, "", error="missing")
    cmd = agent_command(exe, prompt, resume=resume, allowed=allowed, denied=denied, model=model)
    log.info("agent in %s: %s", cwd, shlex.join(cmd[1:]))
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
    for denial in data.get("permission_denials") or []:
        log.warning("denied: %s", denial.get("tool_input"))
    ok = proc.returncode == 0 and not data.get("is_error")
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
