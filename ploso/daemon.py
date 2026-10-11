"""The listening loop: wake word, capture, transcribe, hand to the assistant, speak."""

from __future__ import annotations

import logging
import time

from . import audio, skills as skills_mod, status
from .assistant import Assistant
from .config import STATE_DIR, resolve
from .stt import STT
from .tts import TTS

log = logging.getLogger(__name__)


class Voice:
    """Mic, recogniser, synthesiser and assistant wired together."""

    def __init__(self, cfg: dict, mic: audio.Mic):
        skills = skills_mod.load()
        vocabulary = ", ".join(p for s in skills.values() for p in s.phrases)
        words = sorted({w for s in skills.values() for w in s.confirm_words})
        self.cfg = cfg
        self.mic = mic
        self.out = cfg["audio"]["output_device"]
        self.stt = STT(
            cfg["stt"]["model"],
            cfg["stt"]["device"],
            vocabulary=f"Ploso. {vocabulary}. {', '.join(words)}. Confirm. Cancel.",
        )
        self.tts = TTS(resolve(cfg["tts"]["voice"]), self.out)
        self.assistant = Assistant(skills, cfg, state_dir=STATE_DIR)

    def say(self, text: str) -> None:
        log.info("say: %s", text)
        self.tts.speak(text)
        # The mic heard our own voice. Drop it so it is not taken for the next command.
        self.mic.flush()

    def take_command(self, start_timeout: float, preroll: list | None = None) -> bool:
        """Capture and act on one utterance. False if nothing intelligible was said."""
        clip = audio.capture(self.mic, self.cfg["listen"], start_timeout=start_timeout, preroll=preroll)
        text = self.stt.transcribe(clip) if clip is not None else ""
        if not text:
            return False
        self.assistant.handle(text, self.say, acknowledge=True)
        return True

    def converse(self, preroll: list | None = None) -> None:
        """One wake-up: a command, then spoken confirmations for as long as one is pending."""
        listen = self.cfg["listen"]
        if not self.take_command(listen["start_timeout"], preroll):
            log.info("woke, but heard no command")
        while self.assistant.awaiting_confirmation:
            audio.chime(self.out)
            if not self.take_command(listen["confirm_timeout"]):
                self.assistant.cancel_pending()
                self.say("Cancelled.")


def run(cfg: dict) -> None:
    """Keep the audio engine alive; the persisted control decides whether it listens."""
    from .wake import Wake

    wake = Wake(resolve(cfg["wake"]["model"]), cfg["wake"]["threshold"], cfg["wake"]["stride_frames"])
    with audio.Mic(cfg["audio"]["input_device"]) as mic:
        voice = Voice(cfg, mic)
        log.info("audio engine started")
        recent: list = []
        enabled: bool | None = None
        while True:
            state = status.snapshot()
            status.heartbeat()
            if state["enabled"] != enabled:
                enabled = state["enabled"]
                wake.reset()
                mic.flush()
                recent = []
                log.info("listening %s", "enabled" if enabled else "disabled")
            if not enabled:
                time.sleep(0.25)
                continue
            try:
                frame = mic.read(timeout=10)
                recent = (recent + [frame])[-2:]
                score = wake.feed(frame)
                if score < wake.threshold:
                    mic.track_noise(frame)
                    continue
                log.info("wake word, score %.2f", score)
                audio.chime(voice.out)
                voice.converse(preroll=recent)
                mic.flush()
                wake.reset()
                recent = []
            except Exception as exc:  # noqa: BLE001 - service watchdog recovers the process
                status.heartbeat(error=f"{type(exc).__name__}: {exc}")
                log.exception("audio loop failed; retrying")
                time.sleep(2)


def push_to_talk(cfg: dict) -> None:
    """Same pipeline with the Enter key in place of the wake word. For testing audio."""
    with audio.Mic(cfg["audio"]["input_device"]) as mic:
        voice = Voice(cfg, mic)
        while True:
            try:
                input("Enter, then speak (Ctrl-C quits) > ")
            except (EOFError, KeyboardInterrupt):
                print()
                return
            mic.flush()
            audio.chime(voice.out)
            voice.converse()
