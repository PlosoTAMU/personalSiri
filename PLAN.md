# Ploso voice assistant: plan

Always-listening assistant on a native Debian host. Wake word "ploso" (PLOH-soh), then
a spoken command. The command goes to a headless Claude Code agent (or a local script)
and the result is spoken back. In short: an audio front end bolted onto `claude -p`.

Status: built on 2026-10-10. README.md describes the program as it is and says what has
been tested. This file is the design record. Where the two differ, README.md is right:

- No terminal or tmux hand-off. Full replies are appended to
  `~/.local/state/ploso/<skill>.md`, and the log prints the `claude --resume` id.
- The approval read-back repeats the words that were heard ("I heard: Approve two.").
  It does not look up the letter. The approve command is denied by Claude Code on every
  unconfirmed turn.
- Wake-word-free follow-up exists only while a confirmation is pending. Other follow-ups
  need the wake word and reach the open session for 30 minutes.
- End of speech is detected by audio level, not Silero VAD. Whisper's own VAD filter
  discards clips with no speech.

Items marked UNVERIFIED were not tested.

## 1. Does this already exist?

Partly. Several projects join a wake word to Claude Code. None of them does the whole
job (custom wake word, native Debian, headless dispatch into a named project, spoken
reply), and the close ones are one-person repos.

| Project | What it does | Why not use it as is |
|---|---|---|
| [mbailey/voicemode](https://github.com/mbailey/voicemode) | MCP server giving Claude Code a `converse` tool. Local whisper.cpp + Kokoro. Debian apt instructions. MIT, about 1.4k stars, about 2,300 commits | Mature, but no wake word or always-on mode found in its README. Claude must already be running and call the tool |
| [Eumaios1212/voice-to-claude](https://github.com/Eumaios1212/voice-to-claude) | systemd user daemon: openWakeWord "OK Claude", Silero VAD, whisper.cpp, then `ydotool` types into the focused window. MIT | Input only, no spoken reply. Types into whatever window has focus. Custom wake word not documented. 7 commits, 1 star |
| [jjacke13/claude-talk](https://github.com/jjacke13/claude-talk) | whisper.cpp in, Piper out, Stop hook speaks replies. Has `bin/wake-train`: trains a custom openWakeWord model from Piper samples in about 20 min on CPU | Wake-word setup is built around Nix. Feeds an already-open interactive session through a development channel flag, does not dispatch. 0 stars |
| [EmmN/claude-voice](https://github.com/EmmN/claude-voice) | openWakeWord or Whisper-spotted phrase, GPU Whisper, Piper, routes speech to named Claude sessions ("tell X ...") | Closest in shape, but written for WSL: mic and playback run through PowerShell and the Windows user folder. Native Linux untested. 6 commits, 0 stars |
| [OHF-Voice/linux-voice-assistant](https://github.com/OHF-Voice/linux-voice-assistant) | Home Assistant voice satellite with local wake word | Needs a Home Assistant server as the brain. Too much machinery for this |

**Recommendation: write a small daemon of our own (a few hundred lines of Python) on
maintained components, and borrow three ideas from the projects above.**

- From claude-talk: speaking rules. Skip code blocks and tables, cut long replies at a
  sentence boundary (it uses 1,200 characters).
- From voice-to-claude: Whisper `prompt` plus a `replacements` table to fix words
  Whisper gets wrong every time.
- From claude-voice: fixed phrases first, model only as fallback.

### Wake word engine

| Engine | State | Verdict |
|---|---|---|
| [livekit-wakeword](https://github.com/livekit/livekit-wakeword) | Apache-2.0, active. One YAML config and one command generates synthetic samples, augments, trains, exports ONNX. Built on openWakeWord and loads its models. Debian apt packages listed in its README | **Use this** |
| [openWakeWord](https://github.com/dscripka/openWakeWord) | Works, but last tagged release was 2024. Training is a Colab notebook | Fallback runtime. Same model family |
| Picovoice Porcupine | Free tier keys were disabled on 2026-06-30 and no non-commercial tier is planned ([source](https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744)) | Ruled out |
| Whisper phrase spotting | No training, any phrase | Ruled out as the main trigger: Whisper does not know "ploso", and every sound in the room would go through STT |

Training config for the name:

```yaml
model_name: ploso
target_phrases:
  - "ploso"
  - "ploh so"        # phonetic spelling so the TTS says it right
n_samples: 10000
model:
  model_type: conv_attention
  model_size: small
steps: 50000
target_fp_per_hour: 0.2
```

```bash
sudo apt install espeak-ng libsndfile1 ffmpeg sox portaudio19-dev
uv tool install 'livekit-wakeword[train,eval,export]'
livekit-wakeword setup --config ploso.yaml
livekit-wakeword run ploso.yaml
```

The README gives no GPU, VRAM or time figure. UNVERIFIED whether a 4 GB card is enough.
If not, train once on a rented or Colab GPU, or use the claude-talk approach (small MLP
on openWakeWord features, CPU only, about 20 minutes).

"Ploso" is two syllables, which raises false accepts. Listen to the generated samples
before training to check the pronunciation, tune the threshold on recorded room audio,
and add real recordings of your voice if recall is poor.

## 2. Architecture

```
mic ──> wake word ──> capture until silence ──> STT ──> router ──┬─> script skill ──┐
        livekit-       Silero VAD               faster-whisper   │                  ├─> Piper ──> speaker
        wakeword                                                 └─> claude -p ─────┘
        "ploso"                                                      in the skill's cwd
```

One Python process, `plosod`, run as a systemd user service. PipeWire (Debian's default
desktop audio) through `sounddevice`.

- **Capture:** chime on trigger, record until about 800 ms of silence, 15 s cap.
- **STT:** faster-whisper `small.en`, GPU if present, CPU `int8` otherwise. `initial_prompt`
  lists skill vocabulary.
- **Router:** `skills.toml`. Fuzzy match on listed phrases. No match means the utterance
  goes to a general agent that runs in this project's directory with a narrow allowlist.
- **Dispatch:** `claude -p "<prompt>" --output-format stream-json --verbose` with `cwd`
  set to the skill's project, so that project's `CLAUDE.md` and permission allowlist
  apply. Headless mode cannot answer permission prompts, so anything outside the
  allowlist is denied.
- **Follow-ups:** keep the `session_id`. For about 60 s after the assistant speaks, the
  next utterance needs no wake word and is sent with `--resume <session_id>`.
- **Speech out:** Piper, sentence by sentence. Immediate acknowledgement ("Reviewing
  letters") because agent runs take tens of seconds to minutes.

```toml
[review_mil_letters]
kind    = "agent"
phrases = ["review military letters", "review mil letters", "check letters"]
cwd     = "~/military-letter-sync"
prompt  = "review mil letters"
display = "terminal"     # also open a terminal on the same session for the full table

[daily_brief]
kind    = "script"
phrases = ["give my daily brief", "read my brief", "daily brief"]
run     = "skills/daily_brief.py"
```

## 3. The two example commands

### "Ploso, review military letters"

1. Match `review_mil_letters`, speak "Reviewing letters".
2. `claude -p "review mil letters"` in `military-letter-sync`. Its `AGENTS.md` already
   defines the whole flow and its `.claude/settings.local.json` already allows
   `letter-sync review` and `letter-sync approve *`.
3. Resume the session once more for a spoken summary: counts, then one line per letter.
4. Open a terminal on `claude --resume <session_id>` for the full batch.
5. "Approve two" within the follow-up window resumes the same session.

Safety rules for this skill:

- **Approval is irreversible** (it POSTs `AcceptMilitaryLetter`) and STT can mishear a
  number. The daemon intercepts any follow-up containing "approve", reads back
  "Approve letter 2, Smith, sick, Tuesday. Say confirm.", and forwards only after
  "confirm". This check is daemon code, so the model cannot skip it.
- **Medical details are not read aloud.** Spoken summary gives the category only.
- CC sheet writes still happen without confirmation, as `AGENTS.md` rule 3 says today.

### "Ploso, give my daily brief"

1. Match `daily_brief`, a script skill with no LLM.
2. Gmail query `from:me subject:"Daily brief —" newer_than:2d`, newest hit, `text/plain`
   part. (Subject format from `plosoAssistant/pipeline/deliver_email.py:100`.)
3. Drop the `## Background` and `## Suppressed` tail and speak the rest.
4. If today's brief is missing, say so and offer yesterday's.

## 4. Host requirements (Debian)

- Debian 12 or 13 with PipeWire, a working mic and speakers, systemd user session with
  lingering enabled so the service runs without a login shell.
- Python 3.12 venv through `uv`. Debian 13 ships 3.13, and audio/ML wheels should be
  checked against whatever is installed.
- `claude` installed and logged in as the service user.
- The dispatch targets present on the host: `military-letter-sync` with its `.venv`,
  `.env`, `~/.config/letter-sync/sheets-sa.json`, and its `.claude/settings.local.json`.
  These live in WSL on the current laptop and must be copied or cloned.
- GPU optional. CPU-only works with `base.en` or `small.en`. If the GPU is NVIDIA,
  install the proprietary driver and CUDA libraries from Debian `non-free` and check
  `nvidia-smi` in phase 0. Other GPUs: treat the box as CPU-only.

Always-on laptop settings:

- Lid close must not suspend: `HandleLidSwitch=ignore` and
  `HandleLidSwitchExternalPower=ignore` in `/etc/systemd/logind.conf`, and mask
  `sleep.target suspend.target hibernate.target`.
- `loginctl enable-linger <user>` so `plosod` starts at boot without a login.
- A headless boot has no desktop session, so PipeWire must run as a user service under
  lingering (`systemctl --user enable pipewire wireplumber`). UNVERIFIED on this box.
- `display = "terminal"` needs a screen. On a headless box the full table goes to a
  `tmux` session (`tmux new -d -s ploso-mil 'claude --resume <id>'`) to attach over ssh.
- Built-in laptop mics pick up fan and speaker noise, and a closed lid can muffle the
  mic. Phase 3 measures recall with the lid in its real position. A USB conference mic
  is the fix if recall is under target.

Gmail OAuth for the brief script:

- Google Cloud project with the Gmail API, an OAuth client of type "Desktop app", scope
  `https://www.googleapis.com/auth/gmail.readonly` only.
- The consent flow needs a browser once. Run it on a machine with a browser and copy the
  token, or use `ssh -L` port forwarding to the box.
- Token at `~/.config/ploso/gmail-token.json`, mode 600. A read-only scope means a
  stolen token cannot send or delete mail.
- If the Cloud project stays in "Testing" status, Google expires the refresh token after
  7 days. Set the app to "In production" (no review needed for personal use of your own
  account) or the brief breaks weekly. For a tamu.edu account, the university's
  Workspace admin may block third-party OAuth clients. UNVERIFIED. The existing
  `plosoAssistant` pipeline already authorises this account, so its Cloud project can
  issue a second, read-only client.

## 5. Phases

| # | Build | Done when |
|---|---|---|
| 0 | Host check on the Debian machine: record and play back through PipeWire, `claude -p "say ok"` works, target project runs `letter-sync review` | All three pass |
| 1 | Typed core: `ploso "review military letters"` runs router and dispatch, prints the result. `skills.toml`, session resume, approve confirmation | Both example commands work typed. Tests cover routing and the confirmation check. Mil skill tested with `review` only |
| 2 | Push-to-talk: VAD capture, faster-whisper, Piper | Spoken command after a keypress gives a spoken answer. 20 recorded commands transcribe correctly |
| 3 | Train and integrate the "ploso" model | Under 1 false accept per 8 h of room audio, over 90% recall in 50 trials at 1 to 3 m |
| 4 | Daemon: systemd user service, follow-up window, terminal hand-off, trigger log | Survives suspend and resume. Runs a day without restart |
| 5 | Barge-in ("ploso stop"), mute hotkey, more skills | As needed |

## 6. Decisions (settled 2026-10-10)

1. **Host:** a laptop reinstalled with Debian, left on all the time, using its built-in
   mic. It has some GPU; model and VRAM are not known yet.
2. **Gmail access for the brief:** local read-only Gmail OAuth token and a short script.
3. **Voice approvals:** allowed. "Approve N" goes through after the spoken read-back and
   "confirm".

## 7. Risks

| Risk | Handling |
|---|---|
| False wake triggers a real action | Irreversible verbs need spoken confirmation. Every trigger logged with its audio clip for tuning |
| Always-on mic privacy | Wake word, STT and TTS are local. Only the post-wake transcript reaches Claude. Mute hotkey. Clips kept 7 days |
| Speech from a video or another person | Same checks as a false wake |
| Stale session context | A wake word outside the follow-up window always starts a fresh session |
| Headless agent hangs | Per-skill timeout, spoken notice, process killed at the hard limit |
| Unmatched command reaches a general agent | That agent runs with a read-only allowlist and no access to the mil project |

## 8. Layout

```
personalSiri/
  PLAN.md  NOTES.md  pyproject.toml  skills.toml  ploso.yaml
  ploso/
    audio.py      capture, playback, chime
    wake.py       livekit-wakeword wrapper
    stt.py        VAD capture + faster-whisper
    router.py     phrase match
    dispatch.py   claude -p runner, sessions, confirmation check
    tts.py        Piper
    daemon.py     states: idle, listening, working, speaking, follow-up
    cli.py        `ploso "<text>"` for typed testing
  skills/         script skills (daily_brief.py)
  models/         ploso.onnx, Piper voice (git-ignored)
  systemd/        plosod.service
  tests/
```
