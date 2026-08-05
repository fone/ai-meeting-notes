import asyncio
from datetime import datetime

from meeting_notes.ai_summarizer import BaseSummarizer
from meeting_notes.app import AttendeeSuggester
from meeting_notes.meeting_context import MeetingContext, merge_name_index
from meeting_notes.note_maker import NoteMaker
from meeting_notes.recording_notes import read_recording_notes, write_recording_notes


def test_context_sidecar_round_trips_at_record_start(tmp_path):
    audio = tmp_path / "meeting.wav"
    write_recording_notes(
        audio, title="NE&O Weekly", attendees="Russ, Pete", glossary="FileBound, CDG",
        notes="[ ] ? #tag [00:00]", now=datetime(2026, 8, 5, 9, 0),
    )
    snapshot = read_recording_notes(audio)
    assert snapshot.attendees == "Russ, Pete"
    assert snapshot.glossary == "FileBound, CDG"
    assert snapshot.notes == "[ ] ? #tag [00:00]"


def test_prompt_uses_discrete_context_blocks_and_omits_empty_ones():
    prompt = BaseSummarizer()._build_prompt(
        "Paulo owns AppFront", user_notes="[ ] ? #tag [00:00]",
        attendees="Paula", glossary="FileBound",
    )
    assert "<attendees>\nPaula\n</attendees>" in prompt
    assert "<glossary>\nFileBound\n</glossary>" in prompt
    assert "<user_notes>\n[ ] ? #tag [00:00]\n</user_notes>" in prompt
    assert prompt.index("<attendees>") < prompt.index("<glossary>") < prompt.index("<user_notes>")
    empty = BaseSummarizer()._build_prompt("hello")
    assert "<attendees>\n" not in empty
    assert "<glossary>\n" not in empty
    assert "<user_notes>\n" not in empty


def test_attendee_roster_is_authoritative_frontmatter_not_marker_parser(tmp_path):
    maker = NoteMaker(str(tmp_path / "notes"), str(tmp_path / "transcripts"), ai_provider="none")
    content = maker._generate_note_file(
        title="Test", date=datetime(2026, 8, 5, 9), duration=1,
        summary={"word_count": 1, "keywords": [], "questions": []}, transcript_filename="x.txt",
        recording_file="x.wav", metadata={"attendees": "Paula [ ] ? #tag [00:00]", "glossary": "Nimble (v7.2?)"},
        user_notes="ordinary note",
    )
    assert 'people: ["Paula [ ] ? #tag [00:00]"]' in content
    assert "tags: [meeting, auto-generated]" in content
    assert 'glossary: "Nimble (v7.2?)"' in content


def test_context_summary_and_name_index_preserve_typed_values():
    assert MeetingContext(title="NE&O", attendees="Russ, Pete", glossary="FileBound").summary() == "NE&O · 2 attendees · 1 term"
    assert merge_name_index(["Russ"], "Pete, Russ") == ["Russ", "Pete"]


def test_attendee_suggester_uses_only_typed_name_index():
    suggester = AttendeeSuggester(["Russ", "Pete"])
    assert asyncio.run(suggester.get_suggestion("Pe")) == "Pete"
    assert asyncio.run(suggester.get_suggestion("Russ, Pe")) == "Russ, Pete"
