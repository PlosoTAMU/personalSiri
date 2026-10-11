"""Microphone frames, end-of-speech capture and playback, through PortAudio."""

from __future__ import annotations

import logging
import queue
import shlex
import subprocess

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

RATE = 16000
FRAME = 1280  # 80 ms, the frame size the wake word model is built around
FRAME_MS = 1000 * FRAME // RATE


def apply_mixer(card: str, settings: list[str]) -> None:
    """Re-assert hardware mixer levels, e.g. "Capture 40". Some laptops reset them to maximum
    (suspend, login), which clips the mic so hard that speech is never detected."""
    for setting in settings:
        try:
            control, _, value = setting.rpartition(" ")
            subprocess.run(["amixer", "-c", card, "sset", control, value], capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("mixer %s: %s", shlex.quote(setting), exc)


def rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))


class Mic:
    """16 kHz mono int16 frames from the input device, queued by the audio thread."""

    def __init__(self, device: str | int | None = None):
        # About 30 s. While an agent works nobody reads the queue, so old audio is dropped.
        self._frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=375)
        self._stream = sd.InputStream(
            samplerate=RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME,
            device=device or None,
            callback=self._on_audio,
        )
        # Slow-rising, fast-falling estimate of the room's background level.
        self.noise = 100.0

    def _on_audio(self, indata, frames, time, status) -> None:
        if status:
            log.debug("input status: %s", status)
        try:
            self._frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass

    def __enter__(self) -> "Mic":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stream.stop()
        self._stream.close()

    def read(self, timeout: float = 2.0) -> np.ndarray:
        """Next frame. Raises queue.Empty if the device stopped delivering audio."""
        return self._frames.get(timeout=timeout)

    def flush(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def track_noise(self, frame: np.ndarray) -> None:
        level = rms(frame)
        rate = 0.1 if level < self.noise else 0.005
        self.noise += rate * (level - self.noise)


CHIME_FRAMES = 3  # frames kept but not judged, so the chime is not taken for speech


def capture(
    mic: Mic,
    listen: dict,
    *,
    start_timeout: float,
    preroll: list | None = None,
    chime_frames: int = CHIME_FRAMES,
    speaking: bool = False,
):
    """Record one utterance: wait for speech, stop after a pause. None if nobody spoke.

    speaking=True means the preroll already holds speech (the wake phrase and whatever was
    said with it), so recording starts at once and ends at the first pause.
    """
    threshold = max(listen["min_rms"], 2.5 * mic.noise)
    max_frames = int(listen["max_seconds"] * 1000 / FRAME_MS)
    silence_frames = max(1, listen["silence_ms"] // FRAME_MS)
    wait_frames = int(start_timeout * 1000 / FRAME_MS)

    recent = list(preroll or []) + [mic.read() for _ in range(chime_frames)]
    if not speaking:
        for _ in range(wait_frames):
            frame = mic.read()
            recent = (recent + [frame])[-8:]
            if rms(frame) > threshold:
                break
        else:
            return None

    frames, quiet = recent, 0
    while len(frames) < max_frames and quiet < silence_frames:
        frame = mic.read()
        frames.append(frame)
        quiet = quiet + 1 if rms(frame) <= threshold else 0
    return np.concatenate(frames)


def play(samples: np.ndarray, rate: int, device: str | int | None = None, wait: bool = True) -> None:
    sd.play(samples, rate, device=device or None)
    if wait:
        sd.wait()


def chime(device: str | int | None = None, freq: float = 880.0, ms: int = 120) -> None:
    """Short tone that says "listening". Does not block: the command may already be starting."""
    t = np.arange(int(RATE * ms / 1000)) / RATE
    tone = np.sin(2 * np.pi * freq * t) * np.hanning(t.size) * 0.25
    play((tone * 32767).astype(np.int16), RATE, device, wait=False)
