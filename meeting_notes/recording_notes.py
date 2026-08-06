"""Durable recording-note sidecars and the structured live-note ledger."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_LEDGER_FORMAT = "structured-note-ledger-v1"


@dataclass(frozen=True)
class NoteEntry:
    """One committed live note, positioned on the pause-adjusted recording clock."""

    seq: int
    offset_s: float
    kind: str
    speaker: str | None
    text: str
    tags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "offset_s": self.offset_s,
            "kind": self.kind,
            "speaker": self.speaker,
            "text": self.text,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "NoteEntry":
        kind = str(raw["kind"])
        if kind not in {"note", "action", "question", "marker"}:
            raise ValueError(f"Invalid note entry kind: {kind}")
        speaker = raw.get("speaker")
        if speaker is not None and not isinstance(speaker, str):
            raise ValueError("Note entry speaker must be string or null")
        tags = raw.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Note entry tags must be a string list")
        return cls(
            seq=int(raw["seq"]), offset_s=float(raw["offset_s"]), kind=kind,
            speaker=speaker, text=str(raw.get("text", "")), tags=tags,
        )


@dataclass(frozen=True)
class RecordingNotes:
    recording_file: str
    title: str
    attendees: str
    glossary: str
    notes: str
    updated_at: datetime
    entries: list[NoteEntry] = field(default_factory=list)
    is_legacy: bool = True


def sidecar_path_for(audio_path: str | Path) -> Path:
    """Return the adjacent sidecar path paired with a recording WAV."""
    return Path(audio_path).with_suffix(".notes.md")


def _metadata(*, audio: Path, title: str, attendees: str, glossary: str, now: datetime) -> str:
    return (
        "---\n"
        f"recording_file: {audio.name}\n"
        f"updated_at: {now.isoformat()}\n"
        f"title: {json.dumps(title)}\n"
        f"attendees: {json.dumps(attendees)}\n"
        f"glossary: {json.dumps(glossary)}\n"
    )


def _atomic_write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return path


def write_recording_notes(
    audio_path: str | Path, *, title: str, notes: str, attendees: str = "", glossary: str = "",
    now: datetime | None = None,
) -> Path:
    """Atomically persist a legacy freeform sidecar (read compatibility only)."""
    audio = Path(audio_path)
    now = now or datetime.now().astimezone()
    content = (
        _metadata(audio=audio, title=title, attendees=attendees, glossary=glossary, now=now)
        + "---\n\n# Recording Notes\n\n" + f"{notes.rstrip()}\n"
    )
    return _atomic_write(sidecar_path_for(audio), content)


def start_note_ledger(
    audio_path: str | Path, *, title: str = "", attendees: str = "", glossary: str = "",
    now: datetime | None = None,
) -> Path:
    """Create an empty versioned ledger atomically at recording start."""
    audio = Path(audio_path)
    now = now or datetime.now().astimezone()
    content = (
        _metadata(audio=audio, title=title, attendees=attendees, glossary=glossary, now=now)
        + f"format: {json.dumps(_LEDGER_FORMAT)}\n---\n\n# Structured Note Ledger\n"
    )
    return _atomic_write(sidecar_path_for(audio), content)


def append_note_entry(audio_path: str | Path, entry: NoteEntry) -> None:
    """Append and fsync a committed entry before UI code is allowed to render it."""
    sidecar = sidecar_path_for(audio_path)
    snapshot = read_recording_notes(audio_path)
    if snapshot.is_legacy:
        raise ValueError(f"Cannot append ledger entry to legacy sidecar: {sidecar}")
    if snapshot.entries and entry.seq <= snapshot.entries[-1].seq:
        raise ValueError("Ledger sequence must strictly increase")
    encoded = json.dumps(entry.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
    with sidecar.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def rewrite_note_ledger(
    audio_path: str | Path, *, title: str, attendees: str, glossary: str,
    entries: list[NoteEntry], now: datetime | None = None,
) -> Path:
    """Atomically rewrite metadata and ledger entries for an edit or deletion."""
    audio = Path(audio_path)
    now = now or datetime.now().astimezone()
    lines = [
        _metadata(audio=audio, title=title, attendees=attendees, glossary=glossary, now=now)
        + f"format: {json.dumps(_LEDGER_FORMAT)}\n---\n\n# Structured Note Ledger\n"
    ]
    lines.extend(json.dumps(entry.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n" for entry in entries)
    return _atomic_write(sidecar_path_for(audio), "".join(lines))


def _parse_metadata(content: str, sidecar: Path) -> tuple[dict[str, str], str]:
    if not content.startswith("---\n"):
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}")
    _, separator, body = content.partition("---\n")
    if not separator:
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}")
    metadata_text, separator, remainder = body.partition("---\n")
    if not separator:
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}")
    metadata: dict[str, str] = {}
    for line in metadata_text.splitlines():
        key, separator, value = line.partition(": ")
        if separator:
            metadata[key] = value
    return metadata, remainder


def read_recording_notes(audio_path: str | Path) -> RecordingNotes:
    """Read either a legacy freeform sidecar or a structured ledger."""
    sidecar = sidecar_path_for(audio_path)
    content = sidecar.read_text(encoding="utf-8")
    metadata, remainder = _parse_metadata(content, sidecar)
    try:
        title = json.loads(metadata["title"])
        attendees = json.loads(metadata.get("attendees", '""'))
        glossary = json.loads(metadata.get("glossary", '""'))
        updated_at = datetime.fromisoformat(metadata["updated_at"])
        recording_file = metadata["recording_file"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Malformed recording notes sidecar: {sidecar}") from exc
    if metadata.get("format") != json.dumps(_LEDGER_FORMAT):
        notes = remainder.removeprefix("\n# Recording Notes\n\n").rstrip()
        # This display/recovery entry is deliberately offset 0: legacy bodies
        # never contained a truthful per-entry commit time.
        legacy_entry = NoteEntry(1, 0.0, "note", None, notes, []) if notes else None
        return RecordingNotes(
            recording_file, title, attendees, glossary, notes, updated_at,
            [legacy_entry] if legacy_entry else [], True,
        )

    header, newline, entry_lines = remainder.partition("# Structured Note Ledger\n")
    if not newline:
        raise ValueError(f"Malformed recording ledger: {sidecar}")
    entries: list[NoteEntry] = []
    try:
        for line in entry_lines.splitlines():
            if line.strip():
                entries.append(NoteEntry.from_dict(json.loads(line)))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Malformed recording ledger: {sidecar}") from exc
    if any(right.seq <= left.seq for left, right in zip(entries, entries[1:], strict=False)):
        raise ValueError(f"Malformed recording ledger sequence: {sidecar}")
    return RecordingNotes(recording_file, title, attendees, glossary, "", updated_at, entries, False)


def remove_recording_notes(audio_path: str | Path) -> bool:
    """Delete only the sidecar paired to ``audio_path`` and report success."""
    sidecar = sidecar_path_for(audio_path)
    try:
        sidecar.unlink()
    except FileNotFoundError:
        return False
    return True
