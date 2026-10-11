"""A small Haiku session decides where each spoken request goes.

Haiku sees the repos on disk and the recent sessions Ploso started, and answers with JSON:
answer it directly, start a new session in a repo, or resume an earlier one, with the
model best suited to the work. It has no tools, so it can only choose.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .dispatch import find_claude

log = logging.getLogger(__name__)

MAX_SESSIONS = 15
MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}

SYSTEM = """You are the router for Ploso, a voice assistant. Each request is transcribed \
speech and may contain recognition errors, or begin with the wake phrase "hey ploso" (ignore it) (names like "pulsor" may be misheard).
Choose exactly one action and reply with ONLY a JSON object, no other text:

{"action": "answer" | "new" | "resume",
 "reply": "...",        // answer: the spoken reply, one to three plain sentences
 "repo": "...",         // new/resume: a repo name from the list, or "" for the home folder
 "session_id": "...",   // resume: an id from the session list
 "model": "haiku" | "sonnet" | "opus",
 "task": "..."}         // new/resume: the request, cleaned up, for the coding session

- answer: chit-chat or a general question that needs no files or tools.
- resume: the request continues the work of a listed session (follow-ups like "and the \
other one", "go ahead", or the same repo and topic). Prefer the most recent matching session.
- new: anything else that touches files, code, commands or the machine.
- model: haiku for simple lookups and small edits, sonnet for normal coding, opus for \
hard debugging, design or large changes.
- Never invent a repo or session id. If the request names a project that is not in the list, \
use answer and ask which one they meant."""


@dataclass
class Decision:
    action: str  # "answer", "new", "resume"
    reply: str = ""
    repo: str = ""
    session_id: str = ""
    model: str = "sonnet"
    task: str = ""


MARKERS = (".git", "pyproject.toml", "package.json", "requirements.txt", "Cargo.toml", "go.mod", "Makefile", "pom.xml")


def discover_repos(roots: list[Path]) -> dict[str, Path]:
    """Directories directly under each root that look like projects, keyed by name."""
    repos: dict[str, Path] = {}
    for root in roots:
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and not child.name.startswith(".") and any((child / m).exists() for m in MARKERS):
                repos.setdefault(child.name, child)
    return repos


class Registry:
    """Sessions Ploso started: id, repo, model and a one-line summary, newest last."""

    def __init__(self, path: Path | None):
        self.path = path
        self.items: list[dict] = []
        if path:
            try:
                self.items = json.loads(path.read_text())
            except (OSError, ValueError):
                pass

    def record(self, session_id: str, repo: str, model: str, summary: str, now: float) -> None:
        self.items = [i for i in self.items if i["id"] != session_id]
        self.items.append(
            {"id": session_id, "repo": repo, "model": model, "summary": summary[:120], "ts": now}
        )
        self.items = self.items[-MAX_SESSIONS:]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items))

    def get(self, session_id: str) -> dict | None:
        return next((i for i in self.items if i["id"] == session_id), None)


def build_prompt(text: str, repos: dict[str, Path], sessions: list[dict], now: float) -> str:
    lines = ["Repos: " + (", ".join(sorted(repos)) or "(none)"), "", "Recent sessions, newest first:"]
    for s in reversed(sessions):
        age = int((now - s["ts"]) / 60)
        lines.append(f'- id {s["id"]} repo "{s["repo"]}" model {s["model"]} {age} min ago: {s["summary"]}')
    if not sessions:
        lines.append("(none)")
    lines += ["", f"Request: {text}"]
    return "\n".join(lines)


def parse(raw: str, repos: dict[str, Path], registry: Registry) -> Decision | None:
    """Decision from Haiku's text, or None if it is unusable. Unknown repos and ids are dropped."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return None
    action = data.get("action")
    model = data.get("model") if data.get("model") in MODELS else "sonnet"
    repo = str(data.get("repo") or "")
    task = str(data.get("task") or "").strip()
    if action == "answer" and data.get("reply"):
        return Decision("answer", reply=str(data["reply"]))
    if action == "resume":
        found = registry.get(str(data.get("session_id") or ""))
        if found and task:
            return Decision("resume", repo=found["repo"], session_id=found["id"], model=model, task=task)
        action = "new"  # unknown id: start fresh rather than fail
    if action == "new" and task and (repo == "" or repo in repos):
        return Decision("new", repo=repo, model=model, task=task)
    return None


def route(
    text: str,
    repos: dict[str, Path],
    registry: Registry,
    *,
    now: float,
    claude: str = "claude",
    model: str = MODELS["haiku"],
    cwd: Path,
    timeout: int = 60,
) -> Decision | None:
    exe = find_claude(claude)
    if not exe:
        return None
    cmd = [
        exe, "-p", build_prompt(text, repos, registry.items, now),
        "--output-format", "json", "--model", model, "--tools", "", "--strict-mcp-config",
        "--system-prompt", SYSTEM,
    ]  # fmt: skip
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout
        )
        raw = json.loads(proc.stdout).get("result") or ""
    except (subprocess.TimeoutExpired, ValueError) as e:
        log.error("router failed: %s", e)
        return None
    decision = parse(raw, repos, registry)
    if not decision:
        log.error("router gave no usable decision: %s", raw[:500])
    return decision
