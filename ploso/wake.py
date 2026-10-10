"""Wake word scoring over a sliding two-second window."""

from __future__ import annotations

from collections import deque
from pathlib import Path

import numpy as np

WINDOW_FRAMES = 25  # 25 x 80 ms = the ~2 s window the model expects


class Wake:
    def __init__(self, model_path: Path, threshold: float, stride_frames: int = 2):
        from livekit.wakeword import WakeWordModel

        if not Path(model_path).is_file():
            raise FileNotFoundError(
                f"wake word model not found: {model_path}. Train it first, see train/README.md"
            )
        self._model = WakeWordModel(models=[str(model_path)])
        self.threshold = threshold
        self._stride = max(1, stride_frames)
        self._frames: deque[np.ndarray] = deque(maxlen=WINDOW_FRAMES)
        self._since = 0

    def feed(self, frame: np.ndarray) -> float:
        """Add one 80 ms frame. Returns the newest score, or 0.0 between scoring strides."""
        self._frames.append(frame)
        self._since += 1
        if len(self._frames) < WINDOW_FRAMES or self._since < self._stride:
            return 0.0
        self._since = 0
        scores = self._model.predict(np.concatenate(self._frames))
        return max(scores.values(), default=0.0)

    def reset(self) -> None:
        """Forget buffered audio so one utterance cannot trigger twice."""
        self._frames.clear()
        self._since = 0
