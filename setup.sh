#!/usr/bin/env bash
# One-command bootstrap for the production Linux path.
# Installs audio tools, Python dependencies, and optionally prefetches the
# faster-whisper Turbo model so the first meeting does not pause for a download.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/venv"
ASSUME_YES=false
SKIP_SYSTEM=false
SKIP_MODEL=false

usage() {
    cat <<'EOF'
Usage: ./setup.sh [--yes] [--skip-system-packages] [--skip-model-download]

  --yes                    Accept install and Turbo-download prompts.
  --skip-system-packages   Do not install missing Linux packages.
  --skip-model-download    Install the app but defer the Turbo model download.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes) ASSUME_YES=true ;;
        --skip-system-packages) SKIP_SYSTEM=true ;;
        --skip-model-download) SKIP_MODEL=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

require_command() {
    command -v "$1" >/dev/null 2>&1
}

confirm() {
    local prompt="$1"
    if "$ASSUME_YES"; then
        return 0
    fi
    if [[ ! -t 0 ]]; then
        return 1
    fi
    local answer
    read -r -p "$prompt [Y/n] " answer
    [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]
}

detect_installer() {
    if require_command apt-get; then
        INSTALLER="apt"
        PACKAGES=(python3 python3-venv python3-pip ffmpeg pulseaudio-utils pipewire-bin)
    elif require_command pacman; then
        INSTALLER="pacman"
        PACKAGES=(python python-pip ffmpeg pulseaudio pipewire)
    else
        echo "Unsupported package manager. Install Python 3.10+, ffmpeg, pactl, and pw-record or parec manually." >&2
        exit 1
    fi
}

install_system_packages() {
    local missing=()
    require_command python3 || missing+=(python3)
    require_command ffmpeg || missing+=(ffmpeg)
    require_command pactl || missing+=(pactl)
    if ! require_command pw-record && ! require_command parec; then
        missing+=(pw-record-or-parec)
    fi

    if [[ ${#missing[@]} -eq 0 ]]; then
        echo "✓ System recording dependencies are present."
        return
    fi

    echo "Missing runtime commands: ${missing[*]}"
    if "$SKIP_SYSTEM"; then
        echo "Refusing to continue without required audio dependencies." >&2
        exit 1
    fi

    detect_installer
    echo "This will install: ${PACKAGES[*]}"
    if ! confirm "Install missing system dependencies with sudo?"; then
        echo "Install cancelled. Required commands: python3, ffmpeg, pactl, and pw-record or parec." >&2
        exit 1
    fi

    if [[ "$INSTALLER" == "apt" ]]; then
        sudo apt-get update
        sudo apt-get install -y "${PACKAGES[@]}"
    else
        sudo pacman -S --needed --noconfirm "${PACKAGES[@]}"
    fi
}

prefetch_turbo() {
    if "$SKIP_MODEL"; then
        echo "Skipping Turbo model download. It will download on first transcription."
        return
    fi
    if ! confirm "Download the production faster-whisper Turbo model now?"; then
        echo "Skipping Turbo model download. It will download on first transcription."
        return
    fi

    echo "Downloading and loading faster-whisper Turbo on CPU. This may take several minutes."
    "$VENV/bin/python" - <<'PY'
from meeting_notes.transcriber import WhisperTranscriber

transcriber = WhisperTranscriber(model_name="turbo", device="cpu")
transcriber.load_model()
assert transcriber.backend == "faster_whisper"
print("✓ Turbo model is ready for the first meeting.")
PY
}

main() {
    echo "== AI Meeting Notes production setup =="
    install_system_packages

    if ! require_command python3; then
        echo "python3 is required after package installation." >&2
        exit 1
    fi

    if [[ ! -x "$VENV/bin/python" ]]; then
        echo "Creating virtual environment at $VENV"
        python3 -m venv "$VENV"
    fi

    echo "Installing Python dependencies"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"

    "$VENV/bin/python" - <<'PY'
from faster_whisper import WhisperModel  # noqa: F401
from meeting_notes.config import load_config

config = load_config()
assert config.whisper_model == "turbo"
print("✓ Python dependencies installed. Default transcription model: turbo.")
PY

    prefetch_turbo

    cat <<'EOF'

Setup complete.

1. Start the app:       ./venv/bin/python run.py
2. Press , and choose an AI provider. Choose “No AI” if you want transcription-only.
3. Join a real call, press r, and confirm both MIC and SYS meters move in READY TO RECORD.
4. Click Start Recording. Your first recorded meeting now uses Turbo locally on CPU.

If meeting audio is routed to a different output, select that output in Settings before recording.
EOF
}

main "$@"
