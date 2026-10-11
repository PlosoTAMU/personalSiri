# personalSiri NOTES

GOAL: always-listening voice assistant on native Debian, wake word "ploso", audio front end on `claude -p`. Full design in PLAN.md.

DECISIONS:
- 2026-10-10 target host = native Debian (user). WSL/Windows audio path dropped.
- 2026-10-10 build own small daemon, not adopt an existing project. Why: none covers custom wake word + native Debian + headless dispatch + spoken reply; close ones are 0-1 star solo repos (survey in PLAN.md section 1).
- 2026-10-11 (user) wake phrase changed from "ploso" to "hey ploso".
- 2026-10-11 train/augment.py replaces `livekit-wakeword augment`. Why: tool pads clips with exact zeros (positives in front), model learned silence-then-sound; see train/README.md.
- 2026-10-10 wake word = livekit-wakeword (Apache-2.0, one-command training, openWakeWord-compatible). openWakeWord runtime as fallback.
- 2026-10-10 dispatch via `claude -p` subprocess in target project cwd. Why: reuses login + target's CLAUDE.md and allowlist.
- 2026-10-10 skills.toml, kinds `script` and `agent`. No match = general agent with read-only allowlist.
- 2026-10-10 approve confirmation check lives in daemon code, not in prompt.
- 2026-10-10 build order: typed core, then audio, then wake word.

- 2026-10-10 (user) host = reinstalled Debian laptop, always on, built-in mic, some GPU.
- 2026-10-10 (user) brief via local read-only Gmail OAuth script.
- 2026-10-10 (user) voice approvals allowed, behind read-back + "confirm".
- 2026-10-10 approve gate = `--disallowedTools` on every unconfirmed turn + daemon read-back. Why: tested, Claude Code enforces it; prompt rules alone do not.
- 2026-10-10 mil skill adds allowed_tools for `sheet mark`, `cc done`, `cc skip`. Why: project allowlist only has dry runs, headless run would be denied. NOT yet confirmed by user.
- 2026-10-10 no tmux hand-off; full replies to ~/.local/state/ploso/<skill>.md. Why: two writers on one session.
- 2026-10-10 end-of-speech by audio level, no Silero. Why: no torch dependency.

ASSUMPTIONS:
- confirmed: claude 2.1.296 `-p` works on current machine; mil project has AGENTS.md + allowlist incl. `letter-sync review` and `approve *`; brief subject `Daily brief — YYYY-MM-DD` self-to-self.
- unconfirmed: which machine is the Debian host and its GPU; PipeWire mic works there; wheels on host Python; claude.ai connectors in headless `claude -p`.

DONE:
- 2026-10-10 Assess/Research/Plan, prior-art search. PLAN.md written.
- 2026-10-10 built: ploso/ package, skills.toml, config.toml, install.sh, systemd unit, train/ploso.yaml, README.md, tests (21 pass).
- 2026-10-10 verified: `claude -p --output-format json` keys (result, session_id, permission_denials), `--resume`, leading-wildcard deny rule `Bash(*x approve*)`; typed end-to-end on dummy project (denied without confirm, approved after); Piper -> Whisper small.en round trip on CPU ~1.2 s; systemd unit verifies.
- 2026-10-10 wake model trained on WSL box (RTX 3050 4 GB), livekit-wakeword 0.3.0: setup, generate, augment, extract, train (60k steps, 33 min), export, eval. Model at train/output/ploso/ploso.onnx, copied to models/ploso.onnx. Tool eval: recall 99.3%, FPPH 0.00 at threshold 0.5.
- 2026-10-10 training fixes: `tts_batch_size: 16` in ploso.yaml (default 50 gave CUDA OOM on negatives); 0.3.0 CLI bug `run_extraction() missing sess_options` breaks `augment` and `run`, worked around by calling `run_extraction(config, None)` from a script.
- NOT verified: mic capture, playback, wake loop (dev box had no audio device); wake model (untrained); brief against Gmail; real mil skill (writes to sheet); GPU path; install.sh on Debian.

OPEN:
- Host GPU model/VRAM unknown; headless PipeWire under lingering untested; tamu.edu Workspace may block a new OAuth client.
- Wake model relies on a training artifact: augmented positives start with ~1 s of exact digital silence, negatives do not. Sliding-window test: any clip after digital zeros scores ~0.98 (negatives 100% trigger); with a noise floor (rms 30 to 300) negatives trigger 0 to 15%, but clean positives drop to ~55%. Real-mic recall and false wakes untested. Human listening check of generated clips also not done.
- 2026-10-11 v2 model "hey ploso" trained and installed at models/ploso.onnx (v1 kept as models/ploso_v1.onnx, train/output/ploso_v1). Silence artifact gone: train/check_stream.py gives the same result for zeros, noise and room lead-ins (clean positives 75-80% at 0.5, near-miss negatives 3%, background 0%). But the model is weak: tool eval recall 39% at threshold 0.5, 72% at 0.2 (0.12 false wakes/h on general speech), 85% at 0.1 (0.36/h). config.toml threshold still 0.5, likely needs 0.1-0.2. Real mic untested. User has not confirmed listening to clips.
- 2026-10-11 model_size medium trained on same features, installed at models/ploso.onnx (small kept as models/ploso_v2_small.onnx). Noisy test clips: recall 88% at threshold 0.5 with 0.06 false wakes/h general speech; near-miss phrases trigger 3.4%. ploso.yaml now medium. Other untested levers: milder SNR_DB in train/augment.py (now 3-20 dB), fewer near-identical negatives ("hey polo", "hey paulo"), more samples.
- Next on the Debian box: ./install.sh, `ploso doctor`, `ploso ptt`, train wake model, gmail-auth, then enable service.

RULED OUT:
- Porcupine: free tier keys disabled 2026-06-30, no non-commercial tier.
- Whisper phrase spotting as main trigger: does not know "ploso", sends all room audio through STT.
- EmmN/claude-voice as base: WSL/PowerShell audio path. jjacke13/claude-talk as base: Nix-bound, no dispatch. voice-to-claude: input only, types into focused window. VoiceMode: no wake word found.
