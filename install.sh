#!/usr/bin/env bash
# Set Ploso up on a Debian machine. Safe to run again.
#   ./install.sh          CPU speech recognition
#   ./install.sh --gpu    also install the CUDA libraries for an NVIDIA GPU
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "== system packages"
sudo apt-get update
sudo apt-get install -y curl ca-certificates libportaudio2 \
    pipewire pipewire-alsa pipewire-pulse wireplumber

echo "== uv"
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "== python environment"
if [[ "${1:-}" == "--gpu" ]]; then uv sync --extra gpu; else uv sync; fi

echo "== speech voice"
if [[ ! -f models/en_US-lessac-medium.onnx ]]; then
    .venv/bin/python -m piper.download_voices en_US-lessac-medium --download-dir models
fi

echo "== service"
mkdir -p "$HOME/.config/ploso" "$HOME/.config/systemd/user"
sed "s|@ROOT@|$ROOT|g" systemd/plosod.service > "$HOME/.config/systemd/user/plosod.service"
systemctl --user daemon-reload
systemctl --user enable pipewire wireplumber >/dev/null 2>&1 || true
# Lets the service start at boot with nobody logged in.
sudo loginctl enable-linger "$USER"

cat <<MSG

Installed. Still to do, see README.md:
  1. claude            log in once, if this machine has not yet
  2. train the wake word and copy it to models/ploso.onnx   (train/README.md)
  3. .venv/bin/ploso gmail-auth                             (daily brief)
  4. .venv/bin/ploso doctor                                 (everything should say ok)
  5. systemctl --user enable --now plosod
MSG
