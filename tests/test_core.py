"""Core routing and speech clean-up tests. No audio, network, or Claude required."""

from pathlib import Path

from ploso import brief, config, dispatch, router, skills as skills_mod, status
from ploso.assistant import Assistant
from ploso.dispatch import Result
from ploso.speakable import speakable

SKILLS = skills_mod.load()


def test_shipped_configuration_has_only_a_safe_fallback():
    assert list(SKILLS) == ["fallback"]
    assert SKILLS["fallback"].cwd == config.ROOT / "agent"


def test_speakable_drops_tables_code_and_marks():
    text = "## Batch\n\n| # | Name |\n|---|---|\n| 1 | Smith |\n\n**Two** items. See `x`.\n```\nrm -rf\n```\n- [link](http://a.b) item"
    assert speakable(text) == "Batch. Two items. See x. link item."


def test_agent_command_keeps_prompt_before_tool_flags():
    cmd = dispatch.agent_command("claude", "hi", resume="sid", allowed=["A", "B"], denied=["C"])
    assert cmd[:3] == ["claude", "-p", "hi"]
    assert cmd[cmd.index("--allowedTools") + 1 : cmd.index("--disallowedTools")] == ["A", "B"]
    assert cmd[-2:] == ["--disallowedTools", "C"]


def test_brief_tail_is_cut():
    text = "Brief of Saturday.\n\nTODAY\nDo the thing.\n\nBACKGROUND\nnoise\n\nSUPPRESSED\nads"
    assert brief.cut_quiet_tail(text) == "Brief of Saturday.\n\nTODAY\nDo the thing."
    assert brief.cut_quiet_tail("no tail\n") == "no tail"


def no_router():
    cfg = config.load()
    cfg["router"]["enabled"] = False
    return cfg


class Fake:
    def __init__(self):
        self.calls = []

    def run_agent(self, prompt, cwd, **kw):
        self.calls.append({"prompt": prompt, "cwd": cwd, **kw})
        return Result(True, "short reply", session_id="sid-1")

    def run_script(self, command, **kw):
        self.calls.append({"script": command})
        return Result(True, "script reply")


def test_status_enable_setting_is_durable_and_heartbeat_is_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "STATE_DIR", Path(tmp_path))
    monkeypatch.setattr(status, "STATUS_FILE", Path(tmp_path) / "status.json")
    status.set_enabled(False)
    assert status.snapshot()["enabled"] is False
    status.heartbeat()
    assert status.snapshot()["enabled"] is False
    assert status.healthy(status.snapshot())


def test_voice_command_is_acknowledged_before_processing(tmp_path):
    fake, spoken = Fake(), []
    assistant = Assistant(
        SKILLS,
        no_router(),
        state_dir=Path(tmp_path),
        run_agent=fake.run_agent,
        run_script=fake.run_script,
        emit=lambda *a: None,
    )
    assistant.handle("what is the weather", spoken.append, acknowledge=True)
    assert spoken[0] == "Sure — I'll take care of what is the weather."
    assert spoken[-1] == "short reply."


def test_unmatched_text_uses_the_safe_fallback(tmp_path):
    fake, spoken = Fake(), []
    assistant = Assistant(
        SKILLS,
        no_router(),
        state_dir=Path(tmp_path),
        run_agent=fake.run_agent,
        run_script=fake.run_script,
        emit=lambda *a: None,
    )
    assistant.handle("what is the weather", spoken.append)
    assert fake.calls[0]["cwd"] == config.ROOT / "agent"
    assert spoken[-1] == "short reply."
    assert "short reply" in (Path(tmp_path) / "fallback.md").read_text()


def make_router_assistant(tmp_path, decision_json):
    repo = Path(tmp_path) / "repos" / "pulsor"
    (repo / ".git").mkdir(parents=True)
    cfg = config.load()
    cfg["router"]["repo_roots"] = [str(repo.parent)]
    fake, spoken = Fake(), []
    seen = {}

    def fake_route(text, repos, registry, **kw):
        seen["repos"] = repos
        return router.parse(decision_json, repos, registry)

    a = Assistant(SKILLS, cfg, state_dir=Path(tmp_path), run_agent=fake.run_agent, route=fake_route, emit=lambda *a: None)
    return a, fake, spoken, repo


def test_router_starts_new_session_in_repo_with_chosen_model(tmp_path):
    a, fake, spoken, repo = make_router_assistant(
        tmp_path, 'x {"action":"new","repo":"pulsor","model":"opus","task":"fix the bug"} y'
    )
    a.handle("fix the bug in pulsor", spoken.append)
    call = fake.calls[0]
    assert call["cwd"] == repo and call["model"] == "claude-opus-5-5"
    assert call["resume"] is None and call["permission_mode"] == "bypassPermissions"
    assert a.registry.get("sid-1")["repo"] == "pulsor"


def test_router_resumes_known_session_and_drops_unknown_repo(tmp_path):
    a, fake, spoken, repo = make_router_assistant(
        tmp_path, '{"action":"resume","session_id":"sid-1","model":"haiku","task":"and tests"}'
    )
    a.registry.record("sid-1", "pulsor", "sonnet", "fix the bug", 0)
    a.handle("and tests", spoken.append)
    assert fake.calls[0]["resume"] == "sid-1" and fake.calls[0]["cwd"] == repo
    repos = {"pulsor": repo}
    assert router.parse('{"action":"new","repo":"nope","task":"x"}', repos, a.registry) is None


def test_router_answer_runs_no_session(tmp_path):
    a, fake, spoken, _ = make_router_assistant(
        tmp_path, '{"action":"answer","reply":"It is a mutex."}'
    )
    a.handle("what is a mutex", spoken.append)
    assert spoken == ["It is a mutex."] and fake.calls == []


def test_wake_signal_shows_prompt_briefly(tmp_path, monkeypatch):
    monkeypatch.setattr(status, "STATE_DIR", Path(tmp_path))
    monkeypatch.setattr(status, "STATUS_FILE", Path(tmp_path) / "status.json")
    assert not status.prompt_visible(status.snapshot())
    status.signal_wake()
    state = status.snapshot()
    assert status.prompt_visible(state)
    assert not status.prompt_visible(state, now=state["woke"] + status.PROMPT_SECONDS + 1)
    status.heartbeat()
    assert status.snapshot()["woke"] == state["woke"]


def test_strip_wake_removes_misheard_wake_phrase_only():
    strip = skills_mod.strip_wake
    assert strip("Hey Ploso, open a terminal and print hello") == "open a terminal and print hello"
    assert strip("Hey, Plosso. What time is it?") == "What time is it?"
    assert strip("Hey Polso open the pulsor folder") == "open the pulsor folder"
    assert strip("Ploso fix the tests") == "fix the tests"
    assert strip("Hey Ploso.") == ""
    assert strip("open a terminal and print hello") == "open a terminal and print hello"
    assert strip("hey open the file") == "hey open the file"


def test_announce_reports_tools_and_text_from_stream():
    seen = []
    ev = {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "Opening it."},
        {"type": "tool_use", "name": "Bash", "input": {"command": "echo hello"}},
    ]}}
    dispatch.announce(ev, lambda k, t: seen.append((k, t)))
    dispatch.announce({"type": "user"}, lambda k, t: seen.append(("x", "x")))
    assert seen == [("claude", "Opening it."), ("tool", "Bash: echo hello")]


def test_events_are_read_incrementally(tmp_path, monkeypatch):
    from ploso import events
    monkeypatch.setattr(events, "EVENTS_FILE", Path(tmp_path) / "events.jsonl")
    events.emit("heard", "one")
    first, off = events.read_new(0)
    events.emit("reply", "two")
    second, _ = events.read_new(off)
    assert [e["text"] for e in first] == ["one"] and [e["text"] for e in second] == ["two"]
