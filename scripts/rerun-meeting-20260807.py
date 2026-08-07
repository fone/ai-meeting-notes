#!/usr/bin/env python3
"""Rerun AI summarization for a failed meeting using current code."""

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, "/home/adam/meeting-notes")

import yaml
from meeting_notes.config import load_config
from meeting_notes.note_maker import NoteMaker
from meeting_notes.live_notes import entries_for_prompt
from meeting_notes.recording_notes import NoteEntry

config = load_config()

# Paths
stem = "2026-08-07-Friday-Meeting-1001"
transcript_path = Path("/home/adam/meeting-notes/transcripts") / f"{stem}.txt"
sidecar_path = Path("/home/adam/meeting-notes/recordings/2026-08-07-100151.notes.md")

# Read transcript
transcript_text = transcript_path.read_text()

# Parse sidecar YAML frontmatter
content = sidecar_path.read_text()
parts = content.split("---", 2)
fm = yaml.safe_load(parts[1])
body = parts[2].strip()

# Build metadata
metadata = {
    "attendees": fm.get("attendees", ""),
    "glossary": fm.get("glossary", ""),
    "title": fm.get("title", ""),
}

# Parse entries from sidecar JSON lines into NoteEntry dataclass
entries = []
for line in body.splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    try:
        d = json.loads(line)
        entries.append(NoteEntry(
            seq=d["seq"],
            offset_s=d["offset_s"],
            kind=d["kind"],
            speaker=d.get("speaker"),
            text=d["text"],
            tags=d.get("tags", []),
        ))
    except (json.JSONDecodeError, KeyError, TypeError):
        continue

# Create note maker with current config
note_maker = NoteMaker(
    output_dir=str(config.notes_dir),
    transcripts_dir=str(config.transcripts_dir),
    ai_provider=config.ai_provider,
    ai_model=config.ai_model,
    api_key=config.ollama_cloud_api_key,
    api_base_url=config.custom_base_url,
    provider_name=config.custom_provider_name,
)

print(f"Transcript: {len(transcript_text.split())} words")
print(f"Entries: {len(entries)}")
print(f"Attendees: {metadata['attendees']}")

# Rerun create_note with existing data
print("\nRerunning AI summarization with fixed budget...")

note_path_out, _, error = note_maker.create_note(
    transcript_text=transcript_text,
    formatted_transcript=transcript_text,
    duration=1078.0,
    title=metadata.get("title"),
    metadata=metadata,
    user_notes=entries_for_prompt(entries) if entries else "",
    meeting_start=datetime(2026, 8, 7, 10, 1, 51),
    prompt_transcript=transcript_text,
    entries=entries,
)

if error:
    print(f"ERROR: {error}")
else:
    print(f"Note written: {note_path_out}")
