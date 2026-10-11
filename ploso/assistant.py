"""The brain between ears and mouth: text in, spoken lines out. No audio in here.

State is one optional agent session (so "approve two" reaches the review that is open)
and one optional utterance waiting for a spoken "confirm". Both are saved to disk, so
typed `ploso text` calls and a restarted daemon carry on where they were.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import dispatch, router as router_mod
from .config import resolve
from . import events, skills as skills_mod
from .skills import FALLBACK, Skill, match, normalize
from .speakable import speakable

log = logging.getLogger(__name__)

Say = Callable[[str], None]

CONFIRM = {"confirm", "confirmed", "yes confirm", "i confirm"}
END_SESSION = {"stop", "cancel", "never mind", "nevermind", "that's all", "that is all", "done"}
FAILURES = {
    "timeout": "That took too long, so I stopped it.",
    "missing": "I can't run that here. Check the log.",
    "failed": "That failed. Check the log.",
}


class Assistant:
    def __init__(
        self,
        skills: dict[str, Skill],
        cfg: dict,
        *,
        state_dir: Path | None = None,
        run_agent=dispatch.run_agent,
        run_script=dispatch.run_script,
        clock: Callable[[], float] = time.time,
        route=router_mod.route,
        emit=events.emit,
    ):
        self.skills = {n: s for n, s in skills.items() if n != FALLBACK}
        self.fallback = skills.get(FALLBACK)
        self.cfg = cfg["agent"]
        self.router_cfg = cfg.get("router", {})
        self._route = route
        self.emit = emit
        self.registry = router_mod.Registry(state_dir / "sessions.json" if state_dir else None)
        self.state_dir = state_dir
        self._run_agent = run_agent
        self._run_script = run_script
        self._clock = clock
        self.session: dict | None = None  # {"skill", "id", "expires"}
        self.pending: str | None = None
        self._load()

    # -- state -----------------------------------------------------------------

    @property
    def awaiting_confirmation(self) -> bool:
        return self.pending is not None

    def cancel_pending(self) -> None:
        self.pending = None
        self._save()

    def _load(self) -> None:
        if not self.state_dir:
            return
        try:
            data = json.loads((self.state_dir / "state.json").read_text())
        except (OSError, ValueError):
            return
        self.session, self.pending = data.get("session"), data.get("pending")

    def _save(self) -> None:
        if not self.state_dir:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        state = {"session": self.session, "pending": self.pending}
        (self.state_dir / "state.json").write_text(json.dumps(state))

    def _active(self) -> Skill | None:
        if not self.session:
            return None
        skill = self.skills.get(self.session["skill"]) or (
            self.fallback if self.session["skill"] == FALLBACK else None
        )
        if not skill or self._clock() > self.session["expires"]:
            self.session = self.pending = None
            return None
        return skill

    def _record(self, skill: Skill, heard: str, reply: str) -> None:
        """Full, unshortened replies go to a file: the spoken version drops tables."""
        if not self.state_dir:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.state_dir / f"{skill.name}.md", "a") as f:
            f.write(f"\n\n---\n## {stamp} heard: {heard}\n\n{reply}\n")

    # -- turns -----------------------------------------------------------------

    def handle(self, text: str, say: Say, *, acknowledge: bool = False) -> None:
        said = normalize(text)
        if not said:
            return
        log.info("heard: %s", text)
        self.emit("heard", text.strip())
        if acknowledge:
            say(f"Sure — I'll take care of {text.strip()}.")
        try:
            self._handle(text, said, say)
        finally:
            self._save()

    def _handle(self, text: str, said: str, say: Say) -> None:
        active = self._active()

        if self.pending is not None:
            pending, self.pending = self.pending, None
            if said in CONFIRM and active:
                self._turn(active, pending, say, confirmed=True)
            else:
                say("Cancelled.")
            return

        if said in END_SESSION:
            self.session = None
            say("Okay.")
            return

        if self.router_cfg.get("enabled"):
            self._routed(text, say)
            return

        skill = match(text, self.skills)
        if skill:
            self._start(skill, text, say)
        elif active:
            if self._needs_confirmation(active, said):
                self.pending = text
                say(f"I heard: {text.strip()} Say confirm to do it.")
            else:
                self._turn(active, text, say, confirmed=False)
        elif self.fallback:
            self._start(self.fallback, text, say)
        else:
            say("I don't have a skill for that.")

    @staticmethod
    def _needs_confirmation(skill: Skill, said: str) -> bool:
        words = said.split()
        return any(w.startswith(c.lower()) for c in skill.confirm_words for w in words)

    def _agent(self, skill: Skill, prompt: str, *, resume: str | None, confirmed: bool):
        return self._run_agent(
            prompt,
            skill.cwd,
            resume=resume,
            allowed=skill.allowed_tools,
            denied=[] if confirmed else skill.gated_tools,
            model=self.cfg["model"],
            claude=self.cfg["claude"],
            timeout=skill.timeout or self.cfg["timeout"],
        )

    def _speak_reply(self, skill: Skill, reply: str, say: Say) -> None:
        limit = skill.max_speak_chars
        say(speakable(reply, self.cfg["max_speak_chars"] if limit is None else limit) or "Done.")

    def _start(self, skill: Skill, text: str, say: Say) -> None:
        self.session = None
        if skill.ack:
            say(skill.ack)

        if skill.kind == "script":
            result = self._run_script(skill.run, timeout=skill.timeout or 120)
            if result.text:
                self._speak_reply(skill, result.text, say)
            else:
                say("Done." if result.ok else FAILURES[result.error])
            return

        # The fallback agent has no fixed prompt: it answers whatever was said.
        result = self._agent(skill, skill.prompt or text, resume=None, confirmed=False)
        if not result.ok:
            say(FAILURES[result.error])
            return
        self._record(skill, text, result.text)
        self._open_session(skill, result.session_id)
        reply = result.text
        if skill.speak_prompt:
            spoken = self._agent(skill, skill.speak_prompt, resume=result.session_id, confirmed=False)
            if spoken.ok:
                reply = spoken.text
        self._speak_reply(skill, reply, say)

    def _turn(self, skill: Skill, text: str, say: Say, *, confirmed: bool) -> None:
        assert self.session is not None
        result = self._agent(
            skill, text + skill.followup_suffix, resume=self.session["id"], confirmed=confirmed
        )
        if not result.ok:
            say(FAILURES[result.error])
            return
        self._record(skill, text, result.text)
        self._open_session(skill, result.session_id)
        self._speak_reply(skill, result.text, say)

    def _open_session(self, skill: Skill, session_id: str | None) -> None:
        if not session_id:
            self.session = None
            return
        expires = self._clock() + 60 * self.cfg["session_minutes"]
        self.session = {"skill": skill.name, "id": session_id, "expires": expires}
        log.info("session %s open for %s (claude --resume %s)", skill.name, skill.cwd, session_id)

    # -- router ----------------------------------------------------------------

    def _routed(self, text: str, say: Say) -> None:
        rc = self.router_cfg
        repos = router_mod.discover_repos([resolve(r) for r in rc["repo_roots"]])
        decision = self._route(
            text, repos, self.registry, now=self._clock(), claude=self.cfg["claude"],
            model=rc["model"], cwd=self.fallback.cwd if self.fallback else Path.home(),
        )  # fmt: skip
        if not decision:
            self.emit("error", "The router gave no usable answer.")
            say("I couldn't work out where to send that.")
            return
        if decision.action == "answer":
            self.emit("reply", decision.reply)
            say(speakable(decision.reply, self.cfg["max_speak_chars"]) or "Done.")
            return
        cwd = repos.get(decision.repo, Path.home())
        label = decision.repo or "home"
        self.emit("route", f"{decision.action} session in {label} ({cwd}) with {decision.model}: {decision.task}")
        log.info("route: %s in %s with %s", decision.action, cwd, decision.model)
        result = self._run_agent(
            decision.task + skills_mod.DEFAULT_FOLLOWUP_SUFFIX,
            cwd,
            resume=decision.session_id or None,
            model=router_mod.MODELS[decision.model],
            claude=self.cfg["claude"],
            timeout=rc["timeout"],
            permission_mode=rc["permission_mode"],
            on_event=self.emit,
        )
        if not result.ok:
            self.emit("error", FAILURES[result.error])
            say(FAILURES[result.error])
            return
        self.emit("reply", result.text)
        if result.session_id:
            self.registry.record(result.session_id, decision.repo, decision.model, decision.task, self._clock())
        self._speak_reply(self.fallback or Skill("router", "agent"), result.text, say)
