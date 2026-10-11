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

PREROLL_FRAMES = 25  # 2 s: the wake phrase plus what was said with it


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

    def take_command(self, preroll: list) -> bool:
        """Capture and act on one utterance, "hey ploso ..." said in one breath or in two.

        The preroll holds the last two seconds, which include the wake phrase and anything
        said right after it. If that is only the wake phrase, wait for the command.
        """
        listen = self.cfg["listen"]
        clip = audio.capture(self.mic, listen, start_timeout=0, preroll=preroll, chime_frames=0, speaking=True)
        text = skills_mod.strip_wake(self.stt.transcribe(clip)) if clip is not None else ""
        if not text:
            clip = audio.capture(self.mic, listen, start_timeout=listen["start_timeout"], chime_frames=0)
            text = skills_mod.strip_wake(self.stt.transcribe(clip)) if clip is not None else ""
        if not text:
            return False
        self.assistant.handle(text, self.say, acknowledge=True)
        return True

    def converse(self, preroll: list) -> None:
        if not self.take_command(preroll):
            log.info("woke, but heard no command")


def run(cfg: dict) -> None:
    """Keep the audio engine alive; the persisted control decides whether it listens."""
    from .wake import Wake

    wake = Wake(resolve(cfg["wake"]["model"]), cfg["wake"]["threshold"], cfg["wake"]["stride_frames"])
    with audio.Mic(cfg["audio"]["input_device"]) as mic:
        voice = Voice(cfg, mic)
        log.info("audio engine started")
        recent: list = []
        enabled: bool | None = None
        state, last_beat, last_mixer = status.snapshot(), 0.0, 0.0
        while True:
            # The heartbeat fsyncs (~100 ms), longer than one 80 ms frame: once a second only,
            # or the loop falls behind the mic and drops audio.
            if cfg["audio"]["mixer"] and time.monotonic() - last_mixer >= 30:
                audio.apply_mixer(cfg["audio"]["mixer_card"], cfg["audio"]["mixer"])
                last_mixer = time.monotonic()
            if time.monotonic() - last_beat >= 1.0:
                state, last_beat = status.snapshot(), time.monotonic()
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
                recent = (recent + [frame])[-PREROLL_FRAMES:]
                score = wake.feed(frame)
                if score < wake.threshold:
                    mic.track_noise(frame)
                    continue
                log.info("wake word, score %.2f", score)
                status.signal_wake()
                voice.converse(recent)
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
            clip = audio.capture(mic, voice.cfg["listen"], start_timeout=voice.cfg["listen"]["start_timeout"])
            text = skills_mod.strip_wake(voice.stt.transcribe(clip)) if clip is not None else ""
            if text:
                voice.assistant.handle(text, voice.say, acknowledge=True)
