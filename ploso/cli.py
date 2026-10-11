"""Command line entry point for listening, desktop control, and diagnostics."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config, dispatch, skills as skills_mod


def _text(args, cfg) -> int:
    """Typed commands through the same assistant the daemon uses. No audio needed."""
    from .assistant import Assistant

    assistant = Assistant(skills_mod.load(), cfg, state_dir=config.STATE_DIR)

    def say(line: str) -> None:
        print(f"ploso: {line}")

    if args.words:
        assistant.handle(" ".join(args.words), say)
        return 0
    while True:
        try:
            assistant.handle(input("you: "), say)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0


def _doctor(cfg) -> int:
    """Check everything the daemon needs. Exit status 1 if anything is missing."""
    failed = False

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failed
        failed |= not ok
        print(f"[{'ok' if ok else 'FAIL'}] {label}{': ' + detail if detail else ''}")

    claude = dispatch.find_claude(cfg["agent"]["claude"])
    check("claude CLI", bool(claude), claude or "not found on PATH or in ~/.local/bin")

    try:
        skills = skills_mod.load()
        check("skills.toml", True, ", ".join(skills))
        for skill in skills.values():
            if skill.kind == "agent":
                check(f"  {skill.name} directory", skill.cwd.is_dir(), str(skill.cwd))
    except Exception as exc:  # noqa: BLE001
        check("skills.toml", False, str(exc))

    wake = config.resolve(cfg["wake"]["model"])
    check("wake word model", wake.is_file(), f"{wake} (train it: train/README.md)")
    voice = config.resolve(cfg["tts"]["voice"])
    check("Piper voice", voice.is_file() and voice.with_suffix(".onnx.json").is_file(), str(voice))

    from .brief import TOKEN

    check("Gmail token", TOKEN.is_file(), f"{TOKEN} (create it: ploso gmail-auth)")

    try:
        import numpy as np
        import sounddevice as sd

        from . import audio

        default_in, default_out = sd.default.device
        print(f"     input device:  {sd.query_devices(cfg['audio']['input_device'] or default_in)['name']}")
        print(f"     output device: {sd.query_devices(cfg['audio']['output_device'] or default_out)['name']}")
        with audio.Mic(cfg["audio"]["input_device"]) as mic:
            levels = [audio.rms(mic.read()) for _ in range(25)]
        level = float(np.median(levels))
        check("microphone", level > 1, f"median level {level:.0f} over 2 s (0 means a dead or muted mic)")
    except Exception as exc:  # noqa: BLE001
        check("microphone", False, f"{type(exc).__name__}: {exc}")

    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ploso", description="Voice front end for Claude Code.")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("daemon", help="listen for the wake word (what the systemd service runs)")
    sub.add_parser("status", help="show the persistent top-left enable/disable control")
    enabled = sub.add_parser("enable", help="persistently enable wake-word listening")
    disabled = sub.add_parser("disable", help="persistently disable wake-word listening")
    sub.add_parser("ptt", help="push to talk: Enter instead of the wake word")
    text = sub.add_parser("text", help="type a command instead of saying it")
    text.add_argument("words", nargs="*", help="the command. Leave empty for a prompt")
    sub.add_parser("doctor", help="check models, devices, skills and credentials")
    sub.add_parser("gmail-auth", help="one-time Gmail sign-in for the daily brief")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    cfg = config.load()

    if args.command == "text":
        return _text(args, cfg)
    if args.command == "doctor":
        return _doctor(cfg)
    if args.command == "gmail-auth":
        from .brief import authorize

        authorize()
        return 0
    if args.command in {"enable", "disable"}:
        from . import status

        status.set_enabled(args.command == "enable")
        print(f"Ploso Siri is {'enabled' if args.command == 'enable' else 'disabled'}.")
        return 0
    if args.command == "status":
        from .status import run_window

        run_window()
        return 0

    from . import daemon

    (daemon.run if args.command == "daemon" else daemon.push_to_talk)(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
