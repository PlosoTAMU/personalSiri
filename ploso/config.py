"""Settings: built-in defaults, then config.toml in the repo, then ~/.config/ploso/config.toml."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "ploso"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "ploso"

DEFAULTS: dict = {
    "wake": {"model": "models/ploso.onnx", "threshold": 0.5, "stride_frames": 2},
    "stt": {"model": "small.en", "device": "auto"},
    "tts": {"voice": "models/en_US-lessac-medium.onnx"},
    "audio": {"input_device": "", "output_device": ""},
    "listen": {
        "silence_ms": 800,
        "max_seconds": 15,
        "start_timeout": 4,
        "confirm_timeout": 8,
        "min_rms": 150,
    },
    "agent": {
        "claude": "claude",
        "model": "",
        "timeout": 600,
        "session_minutes": 30,
        "max_speak_chars": 700,
    },
}


def resolve(path: str | Path) -> Path:
    """Expand ~ and make repo-relative paths absolute."""
    p = Path(path).expanduser()
    return p if p.is_absolute() else ROOT / p


def load(extra: Path | None = None) -> dict:
    cfg = {section: dict(values) for section, values in DEFAULTS.items()}
    for path in (ROOT / "config.toml", CONFIG_DIR / "config.toml", extra):
        if path and path.is_file():
            with open(path, "rb") as f:
                for section, values in tomllib.load(f).items():
                    cfg.setdefault(section, {}).update(values)
    return cfg
