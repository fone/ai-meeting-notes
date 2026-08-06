# AI Meeting Notes

A Linux meeting recorder and notetaker that captures microphone and system audio, transcribes locally with **faster-whisper Turbo**, then turns the transcript and your live notes into a structured Markdown meeting note.

This fork is built for reliable real meetings: recording preflight, live audio meters, durable live-note ledgers, timestamped transcripts, configurable AI providers, and Obsidian-ready output.

> **Privacy:** audio transcription happens locally. If you select a cloud AI provider, the transcript and typed meeting context are sent to that provider for summarization.

## What you get

- Mic + system-audio recording through PipeWire or PulseAudio
- A **READY TO RECORD** preflight with live mic/system meters and routing warnings
- Local Turbo transcription using faster-whisper's distilled `large-v3` model
- Crash-safe live notes, plus timestamped entries and optional `@Speaker` anchors
- AI summaries from Ollama Cloud, OpenAI-compatible services, local Ollama, or no AI
- Markdown notes with decisions, action items, questions, tags, and Obsidian frontmatter
- Pause/resume that excludes paused time from transcript offsets

## Supported platform

Linux with Python 3.10+ and PipeWire or PulseAudio. Ubuntu/Debian and Arch are supported by the bootstrap script.

GPU acceleration is optional. The production default is **Turbo on CPU** because it is reliable on normal workstations and avoids CUDA setup failures. Select CUDA in Settings only after confirming that your PyTorch/CUDA stack works.

Turbo is the supported out-of-box path. If you deliberately switch to a legacy Whisper model such as `base` or `large`, install its heavy PyTorch dependency first:

```bash
./venv/bin/pip install -e ".[legacy-whisper]"
```

## Install

Clone the repository and run the one-command bootstrap:

```bash
git clone https://github.com/fone/ai-meeting-notes.git
cd ai-meeting-notes
chmod +x setup.sh
./setup.sh
```

The bootstrap will:

1. Install required Linux packages when needed.
2. Create `./venv` and install Python dependencies.
3. Verify `ffmpeg`, `pactl`, and an audio recorder (`pw-record` or `parec`).
4. Initialize a safe no-provider configuration.
5. Offer to download the Turbo model now, so your first meeting does not wait on a model download.

The model download can take a few minutes and needs internet access. It is stored in the normal faster-whisper cache, not in the repository.

### Required Linux packages

If you prefer to install prerequisites yourself:

```bash
# Ubuntu / Debian
sudo apt install python3 python3-venv python3-pip \
  ffmpeg pulseaudio-utils pipewire-bin

# Arch Linux
sudo pacman -S python python-pip ffmpeg pulseaudio pipewire
```

Why these matter:

| Command | Used for | Ubuntu/Debian package |
| --- | --- | --- |
| `ffmpeg` | Mixes mic and system WAVs into the final recording | `ffmpeg` |
| `pactl` | Finds audio devices and detects meeting-app routing | `pulseaudio-utils` |
| `pw-record` | Preferred PipeWire capture tool | `pipewire-bin` |
| `parec` | PulseAudio capture fallback and monitor capture | `pulseaudio-utils` |

If system packages are already present, the bootstrap does not reinstall them. For automated installs:

```bash
./setup.sh --yes
```

To defer the Turbo download until the first transcription:

```bash
./setup.sh --skip-model-download
```

## First-run checklist

Start the app:

```bash
./venv/bin/python run.py
```

1. Press **`,`** and open **AI Models**.
2. Choose your summarization provider, model, and API key. Select **No AI** if you want local recording and transcription only.
3. In **Audio Settings**, leave devices on auto-detect or select your microphone and the output sink where the meeting plays.
4. Join a real meeting call before recording.
5. Press **`r`**. The app enters **READY TO RECORD**. Confirm that both **MIC** and **SYS** meters move.
6. If the system meter is quiet, select the output sink carrying your meeting audio in Settings and repeat preflight.
7. Click **Start Recording** or press **`s`** from preflight.

Do not skip preflight. A moving mic meter with a silent system meter usually means the meeting app is routed to a different output sink.

## AI provider setup

Provider configuration lives in the app, not in shell startup files. API keys are saved in local app configuration at:

```text
~/.config/meeting-notes/config.yaml
```

The settings screen supports:

| Provider | What you need |
| --- | --- |
| Ollama Cloud | Endpoint, model ID, and API key |
| OpenAI-compatible | Complete `/v1` base URL, model ID, and optional API key |
| Local Ollama | A running Ollama service and a local model |
| No AI | No credential. Records and transcribes but does not generate an AI summary. |

For local Ollama, install Ollama through its official installer, pull the model you want, start its service, then select it in Settings. The recorder and Turbo transcription do **not** depend on Ollama.

### Long meetings and Kimi

Kimi-based Ollama Cloud summaries use an 8,192-token output budget for normal meetings and automatically use 16,384 tokens for transcripts over 6,000 words. This avoids the failure mode where hidden reasoning consumes the whole output budget and returns an empty visible summary.

## During a meeting

| Action | Shortcut |
| --- | --- |
| Start preflight | `r` |
| Start recording from preflight | `s` |
| Pause/resume | `p` |
| Stop and process | `s` |
| Discard recording | `x` |
| Edit meeting context | `e` |
| Clear input focus | `Esc` |

The live-note composer is durable:

- **Enter** commits an entry at the current meeting timestamp.
- **Shift+Enter** adds a newline to the entry.
- Start an entry with `@Name` to attach a time-bounded speaker anchor.
- The app offers roster completion with **Tab**. A bare `@Name` in the middle of a note is only a normal mention.

## Output and storage

By default, project-relative paths are used:

```text
notes/          Generated Markdown notes
recordings/     WAV recordings and durable note sidecars
transcripts/    Timestamped exported transcripts
```

Set an Obsidian vault path in Settings to write notes into your vault. Meeting notes include YAML frontmatter for Dataview and ordinary Markdown sections for summary, decisions, action items, questions, live notes, and transcript references.

The app retains recordings for 30 days by default. Temporary diagnostic WAVs have separate 72-hour and 20 GiB retention safeguards.

## Troubleshooting

### No system audio in the recording

Join the call, then run preflight. If **SYS** stays quiet:

```bash
pactl list sink-inputs short
pactl list sinks short
```

Select the meeting application's actual output sink in Settings, then run preflight again. Do not change the selected sink mid-recording because that would create a capture gap.

### Commands are missing

```bash
command -v pactl pw-record parec ffmpeg
```

You need `pactl`, `ffmpeg`, and at least one of `pw-record` or `parec`. See the prerequisite table above.

### Turbo model download failed

Confirm internet access, then rerun setup to retry only the model initialization:

```bash
./setup.sh --skip-system-packages
```

### Summary says no overview or empty content

That means the AI provider failed to return a usable visible response. Your WAV, transcript, and live-note sidecar are still preserved. Check the provider credential/model in Settings, then rerun the summary from the saved transcript rather than recording the meeting again.

## Development

```bash
./venv/bin/python -m pytest
./venv/bin/python -m ruff check meeting_notes/ tests/
```

The CI workflow intentionally runs a lightweight subset. Run the full suite locally before changing recording, transcription, or Textual UI behavior.

## License

MIT License. See [LICENSE](LICENSE).

## Credits

Originally created by [James Pember](https://github.com/jamespember/meeting-notes-tui-linux). This fork adds production audio-routing safeguards, configurable provider settings, durable live context, and Obsidian workflow integration.
