#!/usr/bin/env python3
"""Regenerate the 2026-08-06 13:59 Security Review note safely.

The existing transcript is the verified Turbo output. This only reruns the
summary using the repaired long-meeting Kimi budget, then replaces the fallback
note after writing a dated backup and atomically swapping a candidate file.
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

from meeting_notes.config import load_config
from meeting_notes.note_maker import NoteMaker
from meeting_notes.recording_notes import read_recording_notes

ROOT = Path("/home/adam/meeting-notes")
WAV = ROOT / "recordings/2026-08-06-135947.wav"
SIDECAR = ROOT / "recordings/2026-08-06-135947.notes.md"
TRANSCRIPT = ROOT / "transcripts/2026-08-06-Thursday-Meeting-1359.txt"
NOTE = Path("/home/adam/Documents/Obsidian/likeasir/Meetings/2026-08-06-Thursday-Meeting-1359.md")
BACKUPS = ROOT / "backups"
START = datetime(2026, 8, 6, 13, 59)
DURATION_S = 4095.0


def transcript_views(path: Path) -> tuple[str, str]:
    raw = path.read_text()
    body = raw.split("\n────────────────────────────────────────────────────────────\n\n", 1)[1]
    prompt = re.sub(r"^\*\*\[([^]]+)\]\*\*", r"[\1]", body, flags=re.MULTILINE)
    prompt = "\n".join(line for line in prompt.splitlines() if line.strip())
    plain = re.sub(r"^\[[^]]+\]\s*", "", prompt, flags=re.MULTILINE)
    return plain, prompt


def main() -> None:
    for source in (WAV, SIDECAR, TRANSCRIPT, NOTE):
        if not source.is_file() or not source.stat().st_size:
            raise RuntimeError(f"Required source missing or empty: {source}")

    snapshot = read_recording_notes(WAV)
    plain, prompt = transcript_views(TRANSCRIPT)
    config = load_config()
    maker = NoteMaker(
        output_dir="/home/adam/Documents/Obsidian/likeasir/Meetings",
        transcripts_dir=str(ROOT / "transcripts"),
        ai_provider="ollama_cloud",
        ai_model="kimi-k2.6",
        api_key=config.ollama_cloud_api_key,
    )
    if maker.summarizer is None:
        raise RuntimeError("Ollama Cloud summarizer was not initialized")

    # Existing freeform notes are context, not Phase 6 anchors: no fabricated offsets.
    ai_summary = maker.summarizer.summarize(
        prompt,
        user_notes=snapshot.notes,
        attendees=snapshot.attendees,
        glossary=snapshot.glossary,
    )
    summary = {"word_count": len(plain.split()), "ai_summary": ai_summary, "keywords": [], "questions": []}
    candidate = maker._generate_note_file(
        title=snapshot.title or "Security Review Meeting",
        date=START,
        duration=DURATION_S,
        summary=summary,
        transcript_filename=TRANSCRIPT.name,
        recording_file=WAV.name,
        metadata={"attendees": snapshot.attendees, "glossary": snapshot.glossary},
        user_notes=snapshot.notes,
    )
    if "Unable to extract key points" in candidate or "No overview generated" in candidate:
        raise RuntimeError("Refusing to replace note with fallback summary")

    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = BACKUPS / f"{NOTE.stem}.before-rerun-{datetime.now():%Y%m%d-%H%M%S}.md"
    candidate_path = NOTE.with_suffix(".rerun.tmp")
    candidate_path.write_text(candidate)
    shutil.copy2(NOTE, backup)
    candidate_path.replace(NOTE)
    print({
        "words": len(plain.split()),
        "title": ai_summary.title,
        "key_points": len(ai_summary.key_points),
        "action_items": len(ai_summary.action_items),
        "decisions": len(ai_summary.decisions),
        "open_questions": len(ai_summary.open_questions),
        "note": str(NOTE),
        "backup": str(backup),
    })


if __name__ == "__main__":
    main()
