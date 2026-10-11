"""Augment clips and extract features. Use in place of `livekit-wakeword augment`.

Two reasons this replaces the tool's own stage (livekit-wakeword 0.3.0):

1. The tool mixes background noise into a clip and only then pads it to two seconds
   with exact zeros. Positives are padded at the front, negatives on both sides. A
   model trained on that learns "digital silence, then a sound" in place of the
   phrase. Here every clip is placed in the window first and noise is laid over the
   whole window, and half of the negatives end at the end of the window the way the
   positives do, so position and silence carry no label.
2. The tool's CLI calls run_extraction(config) without the sess_options argument the
   function requires, so `augment` and `run` crash after augmentation.

Run from this directory with the tool's interpreter:
    "$(uv tool dir)/livekit-wakeword/bin/python" augment.py ploso.yaml
"""

from __future__ import annotations

import logging
import random
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from livekit.wakeword.config import load_config
from livekit.wakeword.data.augment import AudioAugmentor
from livekit.wakeword.data.features import run_extraction
from tqdm import tqdm

RATE = 16000
JITTER = 3200  # the phrase ends 0 to 200 ms before the end of the window
SNR_DB = (3.0, 20.0)
FLOOR_DB = (-86.0, -56.0)  # microphone hiss, about 2 to 50 on the int16 scale
SPLITS = [
    "positive_train", "positive_test",
    "negative_train", "negative_test",
    "background_train", "background_test",
]
SOURCE = re.compile(r"^clip_\d{6}\.wav$")
AUGMENTED = re.compile(r"^clip_\d{6}_r\d+\.wav$")

log = logging.getLogger("augment")


def place(audio: np.ndarray, length: int, at_end: bool) -> np.ndarray:
    """Put a clip in a window of `length` samples. Longer clips are cropped."""
    if len(audio) >= length:
        start = len(audio) - length if at_end else random.randint(0, len(audio) - length)
        return audio[start : start + length].copy()
    window = np.zeros(length, dtype=np.float32)
    if at_end:
        start = length - random.randint(0, JITTER) - len(audio)
    else:
        start = random.randint(0, length - len(audio))
    start = max(0, start)
    window[start : start + len(audio)] = audio
    return window


def background(files: list[Path], length: int) -> np.ndarray:
    bg, _ = sf.read(str(random.choice(files)), dtype="float32")
    if bg.ndim > 1:
        bg = bg[:, 0]
    if len(bg) < length:
        bg = np.tile(bg, length // len(bg) + 1)
    start = random.randint(0, len(bg) - length)
    return bg[start : start + length]


def augment_split(clip_dir: Path, augmentor: AudioAugmentor, positive: bool, length: int) -> None:
    for old in [p for p in clip_dir.glob("*.wav") if AUGMENTED.match(p.name)]:
        old.unlink()
    sources = sorted(p for p in clip_dir.glob("*.wav") if SOURCE.match(p.name))
    for path in tqdm(sources, desc=f"Augmenting {clip_dir.name}", unit="clip"):
        audio, _ = sf.read(str(path), dtype="float32")
        if audio.ndim > 1:
            audio = audio[:, 0]
        audio = augmentor.augment_clip(audio)
        audio = augmentor.apply_rir(audio).astype(np.float32)
        power = float(np.mean(audio**2)) + 1e-10  # measured before padding

        window = place(audio, length, at_end=positive or random.random() < 0.5)
        if augmentor.background_files:
            bg = background(augmentor.background_files, length)
            snr = random.uniform(*SNR_DB)
            window = window + bg * np.sqrt(power / ((float(np.mean(bg**2)) + 1e-10) * 10 ** (snr / 10)))
        floor = 10 ** (random.uniform(*FLOOR_DB) / 20)
        window = window + np.random.normal(0.0, floor, length)

        peak = float(np.max(np.abs(window)))
        if peak > 0.99:
            window = window * (0.99 / peak)
        sf.write(str(path.with_name(f"{path.stem}_r0.wav")), window.astype(np.float32), RATE)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(sys.argv[1])
    random.seed(0)
    np.random.seed(0)
    augmentor = AudioAugmentor(
        background_paths=[Path(p) for p in config.augmentation.background_paths],
        rir_paths=[Path(p) for p in config.augmentation.rir_paths],
    )
    if not augmentor.background_files:
        log.warning("no background files found: clips get only the noise floor")
    length = int(config.augmentation.clip_duration * RATE)
    for split in SPLITS:
        clip_dir = config.model_output_dir / split
        if not clip_dir.exists():
            log.warning("skipping %s: not found", split)
            continue
        augment_split(clip_dir, augmentor, "positive" in split, length)
    log.info("augmentation complete, extracting features")
    run_extraction(config, None)
    log.info("feature extraction complete")


if __name__ == "__main__":
    main()
