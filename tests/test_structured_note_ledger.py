from datetime import datetime
from pathlib import Path

from meeting_notes.live_notes import entries_for_prompt, format_note_entries, parse_note_entry
from meeting_notes.note_maker import NoteMaker
from meeting_notes.recording_notes import (
    NoteEntry,
    append_note_entry,
    read_recording_notes,
    rewrite_note_ledger,
    start_note_ledger,
    write_recording_notes,
)
from meeting_notes.summary_prompt import build_prompt
from meeting_notes.summarizer import MeetingSummary
from meeting_notes.transcriber import TranscriptResult, TranscriptSegment, WhisperTranscriber


def test_commit_parser_supports_markers_any_order_relative_offsets_and_tags():
    action = parse_note_entry("[ ] [-2m] ship TPM #security", offset_s=574, seq=1)
    question = parse_note_entry("? [08:12] does this affect DMZ", offset_s=700, seq=2)
    clamped = parse_note_entry("[-20m] [ ] overdue item", offset_s=574, seq=3)

    assert (action.kind, action.offset_s, action.text, action.tags, action.speaker) == (
        "action", 454, "ship TPM #security", ["security"], None,
    )
    assert (question.kind, question.offset_s, question.text) == ("question", 492, "does this affect DMZ")
    assert (clamped.kind, clamped.offset_s) == ("action", 0)


def test_unrecognized_bracket_text_stays_literal_and_multiline_is_one_entry():
    entry = parse_note_entry("[see ticket 4471]\nhttps://example.test/cve", offset_s=12.4, seq=1)
    assert entry.kind == "note"
    assert entry.text == "[see ticket 4471]\nhttps://example.test/cve"


def test_ledger_append_rewrite_and_legacy_reading(tmp_path):
    audio = tmp_path / "meeting.wav"
    start_note_ledger(audio, title="Review", attendees="Pete", glossary="CDG")
    first = NoteEntry(1, 12.5, "note", None, "One", [])
    second = NoteEntry(2, 18, "action", None, "Ship update", ["security"])
    append_note_entry(audio, first)
    append_note_entry(audio, second)

    snapshot = read_recording_notes(audio)
    assert not snapshot.is_legacy
    assert snapshot.entries == [first, second]

    rewrite_note_ledger(audio, title="Edited", attendees="Pete, Russ", glossary="CDG", entries=[second])
    edited = read_recording_notes(audio)
    assert edited.title == "Edited"
    assert edited.entries == [second]
    assert not list(tmp_path.glob(".*.tmp"))

    legacy_audio = tmp_path / "legacy.wav"
    write_recording_notes(legacy_audio, title="Old", notes="- [ ] Keep legacy", now=datetime(2026, 8, 1))
    legacy = read_recording_notes(legacy_audio)
    assert legacy.is_legacy
    assert legacy.notes == "- [ ] Keep legacy"


def test_ledger_entries_render_and_feed_summary_without_legacy_parser(tmp_path):
    entries = [
        NoteEntry(1, 12, "note", None, "Discuss Q1", []),
        NoteEntry(2, 19, "action", None, "Send update #security", ["security"]),
        NoteEntry(3, 22, "question", None, "Who owns it?", []),
        NoteEntry(4, 25, "marker", None, "", []),
    ]
    rendered = format_note_entries(entries)
    assert "**[00:12]** • Discuss Q1" in rendered
    assert "**[00:19]** [ ] Send update #security" in rendered
    assert "**[00:25]** ◆" in rendered
    assert entries_for_prompt(entries).splitlines()[1] == "[00:19] [ ] Send update #security"

    maker = NoteMaker(str(tmp_path / "notes"), str(tmp_path / "transcripts"), ai_provider="none")
    note = maker._generate_note_file(
        title="Ledger", date=datetime(2026, 8, 6, 9), duration=30,
        summary={"word_count": 3, "keywords": [], "questions": []}, transcript_filename="x.txt",
        recording_file="x.wav", metadata={}, entries=entries,
    )
    assert "tags: [meeting, auto-generated, security]" in note
    assert "## Live Notes" in note


def test_legacy_sidecar_can_regenerate_summary_note(tmp_path):
    audio = tmp_path / "legacy.wav"
    write_recording_notes(audio, title="Old", notes="- [ ] Keep legacy")
    snapshot = read_recording_notes(audio)
    maker = NoteMaker(str(tmp_path / "notes"), str(tmp_path / "transcripts"), ai_provider="none")
    note = maker._generate_note_file(
        title=snapshot.title, date=datetime(2026, 8, 6, 9), duration=1,
        summary={"word_count": 1, "keywords": [], "questions": []}, transcript_filename="x.txt",
        recording_file="legacy.wav", metadata={}, user_notes=snapshot.notes,
    )
    assert "- [ ] Keep legacy" in note


def test_note_maker_sends_timestamped_transcript_to_actual_summarizer(tmp_path):
    class CapturingSummarizer:
        def __init__(self):
            self.transcript = ""

        def summarize(self, transcript, user_notes="", attendees="", glossary=""):
            self.transcript = transcript
            return MeetingSummary("ok", [], [], [], [])

    maker = NoteMaker(str(tmp_path / "notes"), str(tmp_path / "transcripts"), ai_provider="none")
    capture = CapturingSummarizer()
    maker.ai_provider = "test"
    maker.summarizer = capture
    maker.create_note(
        transcript_text="plain flattened text",
        prompt_transcript="[00:12] segment one\n[00:19] segment two",
        formatted_transcript="**[00:12]** segment one\n\n**[00:19]** segment two",
        duration=20,
        meeting_start=datetime(2026, 8, 6, 9),
    )
    assert capture.transcript == "[00:12] segment one\n[00:19] segment two"


def test_timestamped_prompt_transcript_is_segment_granular_and_export_format_unchanged():
    result = TranscriptResult(
        text="Good morning Update complete", language="en", duration=31,
        segments=[TranscriptSegment(12.2, 18, "Good morning"), TranscriptSegment(19, 31, "Update complete")],
    )
    transcriber = WhisperTranscriber()
    prompt_transcript = transcriber.format_transcript_for_prompt(result)
    exported = transcriber.format_transcript_with_timestamps(result)
    prompt = build_prompt(prompt_transcript)

    assert prompt_transcript == "[00:12] Good morning\n[00:19] Update complete"
    assert "**[00:12]** Good morning" in exported
    assert "Each transcript line begins with [MM:SS]" in prompt
    assert "<transcript>\n[00:12] Good morning\n[00:19] Update complete\n</transcript>" in prompt
