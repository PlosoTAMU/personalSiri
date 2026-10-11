# Resume: wake-word training handoff

Status as of 2026-10-10. Nothing has been trained. No `models/ploso.onnx` exists yet.

## Why this was moved
The first machine has 8 CPUs, 7GB RAM and no GPU. `ploso.yaml` asks for 50,000 steps and
10,000 samples, which is probably impractical on CPU. Speedup on GPU is unmeasured.

## What was done on the first machine
- `uv tool install 'livekit-wakeword[train,eval,export]'` succeeded (about 6GB of
  dependencies, slow download).
- `livekit-wakeword setup --config ploso.yaml` reported "Setup complete" but the network
  was flaky: the **ACAV100M features download failed** and the **validation features
  download failed** (DNS errors). `train/data/` (gitignored, not transferred) is
  therefore incomplete. On the new machine, rerun setup and check that the log has no
  "Failed to download" warnings. Setting `HF_TOKEN` avoids HF rate limits.
- Generation, augmentation, training, export and eval have not been run.

## Steps on the GPU machine
```bash
git pull
nvidia-smi                      # confirm the driver sees the GPU
sudo apt install espeak-ng libsndfile1 ffmpeg sox portaudio19-dev
uv tool install 'livekit-wakeword[train,eval,export]'
cd train
livekit-wakeword setup --config ploso.yaml      # rerun; verify no download failures
livekit-wakeword generate ploso.yaml            # then LISTEN to clips in data/ for "PLOH-soh"
livekit-wakeword run ploso.yaml                 # or run stages: augment, train, export, eval
```
Before the full run, time a short run (fewer steps) to get a real CPU-vs-GPU figure.
If `generate` clips misread "ploso", change `target_phrases` first.

## Bringing the model back
Copy the exported file (path is at the end of the run output, under `train/output/`) to
`models/ploso.onnx` on the machine that runs the daemon, then `.venv/bin/ploso doctor`.
`plosod.service` restarts in a loop until that file exists.

See `README.md` here for threshold tuning.
