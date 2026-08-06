# AI Meeting Notes

A privacy-first, keyboard-driven meeting notetaker for Linux. Record meetings, transcribe locally with Whisper, and summarize with your choice of cloud or local LLM.

**Forked from [meeting-notes-tui-linux](https://github.com/jamespember/meeting-notes-tui-linux) by James Pember.** This fork adds recording reliability improvements, configurable AI providers, preflight diagnostics, and Obsidian integration.

## Features

- **Keyboard-driven TUI** - Lazygit-inspired interface, no mouse required
- **Audio recording** - Mic + system audio via PipeWire/PulseAudio
- **Recording preflight** - Verify audio routing and device health before you start recording
- **Live meters** - Real-time dBFS peak meters with peak-hold markers during recording
- **Silence detection** - Automatic mic silence warnings with hysteresis
- **Pause/resume** - Pause recording without losing context; paused time excluded from duration
- **Local transcription** - faster-whisper (large-v3-turbo) on CPU, privacy-first
- **AI summaries** - Any OpenAI-compatible provider (OpenAI, Anthropic, Ollama, Ollama Cloud, OpenRouter, or custom endpoints)
- **AI-generated titles** - Summarizer suggests meeting titles automatically
- **User notes** - Write your own notes during recording for AI context
- **Structured output** - Notes include attendees, key terms, and action items extracted by AI
- **Recording note sidecars** - Live notes persisted as atomic sidecars, crash-safe
- **Obsidian integration** - Output to Obsidian vault with frontmatter and Dataview-compatible queries
- **Settings UI** - Configure AI providers, models, API keys, audio devices, and themes from within the app

## Quick Start

### Prerequisites

- Linux with PipeWire or PulseAudio
- Python 3.10+
- ffmpeg

```bash
# Ubuntu / Debian
sudo apt install python3 python3-pip python3-venv ffmpeg portaudio19-dev

# Arch Linux
sudo pacman -S python python-pip ffmpeg portaudio
```

### Install

```bash
git clone https://github.com/fone/ai-meeting-notes.git
cd ai-meeting-notes

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
python run.py
```

Press `,` to open settings and configure your audio devices and AI provider.

### Dev mode

```bash
python run.py --dev
```

Preserves temp audio files for debugging.

## AI Provider Setup

Press `,` in the app to configure. Supports any OpenAI-compatible endpoint:

| Provider | Base URL | Notes |
|----------|----------|-------|
| OpenAI | `https://api.openai.com/v1` | GPT-4o, GPT-4o-mini |
| Anthropic | `https://api.anthropic.com/v1` | Claude models via OpenAI-compatible proxy |
| Ollama (local) | `http://localhost:11434/v1` | Free, runs on your machine |
| Ollama Cloud | Your cloud endpoint | Remote Ollama instance |
| OpenRouter | `https://openrouter.ai/api/v1` | Multi-model gateway |
| Custom | Any OpenAI-compatible URL | Bring your own |

API keys are stored locally in `~/.config/meeting-notes/config.yaml` and are never committed to the repo.

## Audio Configuration

The app auto-detects PipeWire/PulseAudio devices. Press `,` to pick specific mic and system audio devices.

**Recording modes:**
- `combined` - Mic + system audio (default, best for meetings)
- `mic` - Microphone only
- `system` - System audio only (captures whatever your meeting app plays)

**Audio test** (press `A` from main view):
- Live peak meters for both mic and system audio
- 5-second test recording with verdict (PASS/WARN/FAIL)
- Diagnoses per-app routing issues with Zoom, Teams, Meet, etc.

## Keyboard Shortcuts

**Main view:**
| Key | Action |
|-----|--------|
| `r` | Start recording (opens preflight) |
| `o` | Open note in editor |
| `e` | Edit title |
| `t` | View transcript |
| `T` | Manage tags |
| `d` | Delete note |
| `A` | Audio test |
| `,` | Settings |
| `q` | Quit |
| `j/k` or `↑/↓` | Navigate |

**Recording:**
| Key | Action |
|-----|--------|
| `r` | Start recording (from preflight) |
| `p` | Pause/resume |
| `s` | Stop and process |
| `x` | Cancel and discard |
| `Esc` | Unfocus input |

## Output

Notes are saved as markdown with YAML frontmatter:

```markdown
---
title: "Weekly Standup"
date: 2026-08-06
time: "09:00"
duration_seconds: 1800
word_count: 1200
tags: [meeting]
attendees: [Alice, Bob, Charlie]
terms: [Q3 roadmap, deployment pipeline]
---

# Weekly Standup

## Summary
The team reviewed Q3 priorities and deployment timeline...

### Key Points
- Deployment pipeline targeting August 15
- Budget review needed before sprint planning

### Action Items
- Alice: Finalize deployment checklist
- Bob: Schedule budget review meeting
```

## Obsidian Integration

Set your Obsidian vault path in settings. Notes are written with frontmatter that works with Dataview queries:

```dataview
TABLE Meeting, Start
FROM "Meetings"
WHERE file.cday >= date(today) - dur(7 days)
SORT file.cday DESC
```

## Testing

```bash
# Unit tests (no audio hardware needed)
pytest tests/test_config.py tests/test_paths_and_fallbacks.py \
       tests/test_recording_retention.py tests/test_summarizers.py \
       tests/test_smart_titles.py tests/test_preflight_workflow.py
ruff check meeting_notes/ tests/

# Full suite (needs audio devices and full env)
pip install -e ".[all,dev]"
pytest
```

## License

MIT License - See LICENSE file for details.

## Credits

Originally created by [James Pember](https://github.com/jamespember/meeting-notes-tui-linux). This fork extends it with recording reliability, configurable AI providers, and workflow improvements.
