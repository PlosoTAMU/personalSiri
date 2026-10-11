"""Check a trained model the way the daemon uses it: a two-second window sliding
over a continuous stream, scored every 160 ms.

The tool's own eval scores one aligned two-second clip at a time, so it cannot see a
model that fires on what comes before a clip. This puts different lead-ins in front of
clean test clips. A sound model detects positives and ignores negatives for every
lead-in, exact digital silence included.

Run from this directory with the tool's interpreter:
    "$(uv tool dir)/livekit-wakeword/bin/python" check_stream.py output/ploso/ploso.onnx
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from livekit.wakeword import WakeWordModel

RATE = 16000
WINDOW = 2 * RATE
STRIDE = 2560
LEAD, TAIL = int(1.5 * RATE), int(0.75 * RATE)
PER_SET = 60
THRESHOLD = 0.5


def load(path: Path) -> np.ndarray:
    audio, _ = sf.read(str(path), dtype="float32")
    return audio[:, 0] if audio.ndim > 1 else audio


def main() -> None:
    model_path = Path(sys.argv[1])
    clips = model_path.parent
    model = WakeWordModel(models=[str(model_path)])
    random.seed(1)
    rng = np.random.default_rng(1)
    backgrounds = [load(p) for p in sorted(clips.glob("background_test/clip_??????.wav"))]

    def fill(kind: str, n: int) -> np.ndarray:
        if kind == "zeros":
            return np.zeros(n, dtype=np.float32)
        if kind.startswith("noise"):
            return rng.normal(0.0, float(kind[5:]) / 32768, n).astype(np.float32)
        bg = random.choice(backgrounds)
        bg = np.tile(bg, n // len(bg) + 1)[:n]
        return (bg * 0.02 / (np.sqrt(np.mean(bg**2)) + 1e-9)).astype(np.float32)

    def peak(audio: np.ndarray) -> float:
        return max(
            max(model.predict(audio[end - WINDOW : end]).values())
            for end in range(WINDOW, len(audio) + 1, STRIDE)
        )

    sets = {}
    for name in ("positive_test", "negative_test", "background_test"):
        files = sorted(clips.glob(f"{name}/clip_??????.wav"))
        sets[name] = [load(p) for p in random.sample(files, min(PER_SET, len(files)))]

    print(f"model {model_path}, threshold {THRESHOLD}, {PER_SET} clean clips per set")
    print(f"{'lead-in':10s}" + "".join(f"{n:>24s}" for n in sets))
    for kind in ("zeros", "noise30", "noise300", "room"):
        row = f"{kind:10s}"
        for clips_ in sets.values():
            scores = np.array(
                [peak(np.concatenate([fill(kind, LEAD), c, fill(kind, TAIL)])) for c in clips_]
            )
            row += f"{(scores >= THRESHOLD).mean():>10.0%} med {np.median(scores):.2f}    "
        print(row, flush=True)


if __name__ == "__main__":
    main()
