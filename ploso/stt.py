"""Speech to text with faster-whisper."""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class STT:
    def __init__(self, model: str = "small.en", device: str = "auto", vocabulary: str = ""):
        from faster_whisper import WhisperModel

        self._prompt = vocabulary or None
        self._model = None
        if device in ("auto", "cuda"):
            try:
                gpu = WhisperModel(model, device="cuda", compute_type="float16")
                # Missing CUDA libraries only show up on first use, so use it once now.
                list(gpu.transcribe(np.zeros(16000, dtype=np.float32), language="en")[0])
                self._model = gpu
                log.info("whisper %s on GPU", model)
            except Exception as exc:  # noqa: BLE001 - any GPU problem means CPU
                if device == "cuda":
                    raise
                log.info("no usable GPU for whisper (%s), using CPU", exc)
        if self._model is None:
            self._model = WhisperModel(model, device="cpu", compute_type="int8")
            log.info("whisper %s on CPU", model)

    def transcribe(self, samples: np.ndarray) -> str:
        """int16 16 kHz mono in, text out. Empty when the clip holds no speech."""
        audio = samples.astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            audio,
            language="en",
            initial_prompt=self._prompt,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
