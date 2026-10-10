"""Text to speech with Piper."""

from __future__ import annotations

from pathlib import Path

from . import audio


class TTS:
    def __init__(self, voice_path: Path, device: str | int | None = None):
        from piper import PiperVoice

        if not Path(voice_path).is_file():
            raise FileNotFoundError(f"Piper voice not found: {voice_path}. Run ./install.sh")
        self._voice = PiperVoice.load(str(voice_path))
        self._device = device

    def speak(self, text: str) -> None:
        """Blocks until the text has been played. Piper yields one chunk per sentence."""
        for chunk in self._voice.synthesize(text):
            audio.play(chunk.audio_int16_array, chunk.sample_rate, self._device)
