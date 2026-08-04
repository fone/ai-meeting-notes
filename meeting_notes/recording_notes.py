"""Durable, human-readable notes sidecars paired with recording WAVs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class RecordingNotes:
    recording_file: str
    title: str
    notes: str
    updated_at: datetime


def sidecar_path_for(audio_path: str | Path) -> Path:
    """Return the Markdown sidecar path paired with a recording WAV."""
    return Path(audio_path).with_suffix(".notes.md")


def write_recording_notes(
    audio_path: str | Path,
    *,
    title: str,
    notes: str,
    now: datetime | None = None,
) -> Path:
    """Atomically persist a recording's title and notes beside its WAV."""
    audio = Path(audio_path)
    sidecar = sidecar_path_for(audio)
    now = now or datetime.now().astimezone()
    content = (
        "---\n"
        f"recording_file: {audio.name}\n"
        f"updated_at: {now.isoformat()}\n"
        f"title: {json.dumps(title)}\n"
        "---\n\n"
        "# Recording Notes\n\n"
        f"{notes.rstrip()}\n"
    )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    temporary = sidecar.with_name(f".{sidecar.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, sidecar)
    return sidecar


def read_recording_notes(audio_path: str | Path) -> RecordingNotes:
    """Read a paired sidecar. Raises FileNotFoundError for absent sidecars."""
    sidecar = sidecar_path_for(audio_path)
    content = sidecar.read_text(encoding="utf-8")
    header, separator, body = content.partition("---\n")
    if not content.startswith("---\n") or not separator:
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}")
    metadata_text, separator, notes_body = body.partition("---\n")
    if not separator:
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}")
    metadata: dict[str, str] = {}
    for line in metadata_text.splitlines():
        key, separator, value = line.partition(": ")
        if not separator:
            continue
        metadata[key] = value
    try:
        title = json.loads(metadata["title"])
        updated_at = datetime.fromisoformat(metadata["updated_at"])
        recording_file = metadata["recording_file"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}") from exc
    notes = notes_body.removeprefix("\n# Recording Notes\n\n").rstrip()
    return RecordingNotes(
        recording_file=recording_file,
        title=title,
        notes=notes,
        updated_at=updated_at,
    )


def remove_recording_notes(audio_path: str | Path) -> bool:
    """Delete only the sidecar paired to ``audio_path`` and report success."""
    sidecar = sidecar_path_for(audio_path)
    try:
        sidecar.unlink()
    except FileNotFoundError:
        return False
    return True
