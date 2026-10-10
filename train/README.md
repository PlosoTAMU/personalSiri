# Training the "ploso" wake word

The daemon needs `models/ploso.onnx`. It is trained with
[livekit-wakeword](https://github.com/livekit/livekit-wakeword) from synthetic speech:
no recordings needed. This has not been run yet, so treat times and hardware needs as
unknown. The tool's README gives no GPU or duration figures.

Train on any machine with a GPU (or a rented one) and copy the one file over. Training
tools are not part of this project's environment.

```bash
sudo apt install espeak-ng libsndfile1 ffmpeg sox portaudio19-dev
uv tool install 'livekit-wakeword[train,eval,export]'

cd train
livekit-wakeword setup --config ploso.yaml    # downloads TTS voices and noise data
livekit-wakeword run ploso.yaml               # generate, augment, train, export, eval
```

The stages can be run one at a time: `generate`, `augment`, `train`, `export`, `eval`.
After `generate`, listen to a few of the generated clips under `data/` and check that
they say "PLOH-soh". If the made-up word is misread, change `target_phrases` in
`ploso.yaml` to a spelling the voices pronounce correctly and generate again.

Then:

```bash
cp output/**/ploso.onnx ../models/ploso.onnx    # exact folder: see the end of the run's output
cd .. && .venv/bin/ploso doctor
```

## Tuning

- Run `ploso -v daemon` and say the word 20 times from where you normally sit. The log
  prints each `wake word, score ...`.
- Leave it running for a day with the TV or music on. Each false wake also logs a score.
- Set `[wake] threshold` in `config.toml` between the two groups.

"Ploso" has two syllables, which makes false wakes more likely than with a longer
phrase. If no threshold separates the groups, add near-miss words that triggered it to
`custom_negative_phrases` and retrain, or raise `n_samples` and `steps`.

## Without a trained model

`ploso ptt` uses the Enter key in place of the wake word and needs no model. Use it to
check the microphone, recognition and speech first.
