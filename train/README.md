# Training the "hey ploso" wake phrase

The daemon needs `models/ploso.onnx`. It is trained with
[livekit-wakeword](https://github.com/livekit/livekit-wakeword) from synthetic speech:
no recordings needed. Training tools are not part of this project's environment.

Measured on an RTX 3050 with 4 GB (livekit-wakeword 0.3.0): setup downloads 17 GB,
generate takes 30 minutes, augment and feature extraction 7 minutes, training 35 minutes.

```bash
sudo apt install espeak-ng libsndfile1 ffmpeg sox portaudio19-dev
uv tool install 'livekit-wakeword[train,eval,export]'
PY="$(uv tool dir)/livekit-wakeword/bin/python"

cd train
livekit-wakeword setup --config ploso.yaml    # downloads TTS voices and noise data
livekit-wakeword generate ploso.yaml          # synthetic clips, resumes if interrupted
"$PY" augment.py ploso.yaml                   # NOT `livekit-wakeword augment`, see below
livekit-wakeword train ploso.yaml
livekit-wakeword export ploso.yaml
livekit-wakeword eval ploso.yaml
"$PY" check_stream.py output/ploso/ploso.onnx
```

After `generate`, listen to a few clips under `output/ploso/positive_train/` and check
that they say "HAY PLOH-soh". `espeak-ng -q -x "hey ploso"` prints the phonemes the
voices are given. If the made-up word is misread, change `target_phrases` in
`ploso.yaml`, delete `output/ploso/`, and generate again.

Then:

```bash
cp output/ploso/ploso.onnx ../models/ploso.onnx
cd .. && .venv/bin/ploso doctor
```

## Why not `livekit-wakeword augment` or `run`

Two problems in version 0.3.0, both handled by `augment.py`:

- The tool pads each clip to two seconds with exact digital silence, in front of
  positives and around negatives. The first model trained here learned "silence, then a
  sound" in place of the phrase. Its eval reported 99% recall and no false wakes, and it
  then fired on every near-miss phrase that followed silence. `augment.py` lays noise
  over the whole window and ends half of the negatives where the positives end.
- The CLI calls `run_extraction(config)` without a required argument, so `augment` and
  `run` crash after augmentation.

## Reading the results

`eval` scores one aligned clip at a time and cannot see a model that reacts to what
comes before a clip. `check_stream.py` slides the window the way the daemon does, with
four different lead-ins in front of clean test clips. Positives should score high and
negatives low in every row, the `zeros` row included. Rows that differ a lot mean the
model is reacting to the lead-in.

## Tuning

- Run `ploso -v daemon` and say the phrase 20 times from where you normally sit. The log
  prints each `wake word, score ...`.
- Leave it running for a day with the TV or music on. Each false wake also logs a score.
- Set `[wake] threshold` in `config.toml` between the two groups.

If no threshold separates the groups, add near-miss phrases that triggered it to
`custom_negative_phrases` and retrain, or raise `n_samples`, `steps` or `model_size`.

## Without a trained model

`ploso ptt` uses the Enter key in place of the wake word and needs no model. Use it to
check the microphone, recognition and speech first.
