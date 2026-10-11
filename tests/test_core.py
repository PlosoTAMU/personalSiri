"""Core routing and speech clean-up tests. No audio, network, or Claude required."""

from pathlib import Path

from ploso import brief, config, dispatch, skills as skills_mod, status
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
        config.load(),
        state_dir=Path(tmp_path),
        run_agent=fake.run_agent,
        run_script=fake.run_script,
    )
    assistant.handle("what is the weather", spoken.append, acknowledge=True)
    assert spoken[0] == "Sure — I'll take care of what is the weather."
    assert spoken[-1] == "short reply."


def test_unmatched_text_uses_the_safe_fallback(tmp_path):
    fake, spoken = Fake(), []
    assistant = Assistant(
        SKILLS,
        config.load(),
        state_dir=Path(tmp_path),
        run_agent=fake.run_agent,
        run_script=fake.run_script,
    )
    assistant.handle("what is the weather", spoken.append)
    assert fake.calls[0]["cwd"] == config.ROOT / "agent"
    assert spoken[-1] == "short reply."
    assert "short reply" in (Path(tmp_path) / "fallback.md").read_text()
