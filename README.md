# Ploso

Ploso is an always-listening voice front end for Claude Code on Debian. A wake word
starts a spoken command; Ploso routes it to a configured local script or headless Claude
Code session and reads the answer aloud.

```
mic > wake word > record until pause > speech-to-text > skill router > agent or script > speech
```

Audio processing and speech recognition run locally. Only the resulting command is sent
to Claude Code when an agent skill is selected.

## Status

The project has unit-tested routing, confirmation, session handling, and text-to-speech
formatting. Audio devices, wake-word training, provider authentication, and deployment
must be tested on the target machine.

## Install

On a Debian machine:

```bash
git clone https://github.com/PlosoTAMU/personalSiri.git ~/personalSiri
cd ~/personalSiri
./install.sh             # add --gpu for an NVIDIA system
```

Then:

1. Install Claude Code and log in once.
2. Train or provide a wake-word model in `models/`; see `train/README.md`.
3. Define local skills and any account integrations outside the repository.
4. Run `.venv/bin/ploso doctor`, then `.venv/bin/ploso ptt`.
5. Start the listener and persistent desktop control: `systemctl --user enable --now plosod ploso-status`.

## Desktop enable control and reliability

`ploso-status` displays an always-visible control in the top-left of the graphical
session. It says **Ploso Siri is enabled** (and whether the listener is healthy) or
**Ploso Siri is disabled**. Click **Enable** or **Disable** at any time. The choice is
atomically saved in `~/.local/state/ploso/status.json`, so it survives service restarts
and reboots. While disabled, the daemon stays running but never reads the microphone or
reacts to a wake word; only the button or `ploso enable` can turn listening back on.

The listening and desktop services are configured with `Restart=always`, and the daemon
updates a heartbeat that the desktop control checks each second. This recovers from a
crashed assistant process once Linux/systemd is still running. No ordinary user-space
program can continue executing during a whole-computer/kernel freeze; the machine must
recover or reboot before systemd can restart it.

After changing service templates, re-run `./install.sh`, then start them:

```bash
systemctl --user enable --now plosod ploso-status
```

Logs:

```bash
journalctl --user -u plosod -f
```

## Commands

| Command | Description |
|---|---|
| `ploso daemon` | Run the resilient wake-word audio engine. |
| `ploso status` | Show the persistent top-left enable/disable control. |
| `ploso enable` / `ploso disable` | Persistently change listening state without the control. |
| `ploso ptt` | Push to talk for testing audio and recognition. |
| `ploso text <command>` | Submit typed text without using audio. |
| `ploso doctor` | Check models, devices, and configured skills. |

## Skills

`skills.toml` provides the safe fallback agent only. Keep project-specific skills,
paths, account details, approval flows, and tool permissions in local configuration
outside Git. A skill can run a script or invoke Claude Code in a chosen working
directory.

```toml
[example]
kind = "script"
phrases = ["say hello"]
run = "printf 'Hello'"
```

Restart the service after local configuration changes:

```bash
systemctl --user restart plosod
```

## Layout

```
ploso/       application package
agent/       fallback agent instructions
train/       wake-word training configuration and notes
models/      downloaded or trained models; ignored by Git
systemd/     user service template
tests/       unit tests
```

## Security

Do not commit credentials, OAuth clients or tokens, personal skill definitions, generated
transcripts, audio recordings, downloaded models, or deployment-specific configuration.
The supplied `.gitignore` excludes these local artifacts.
