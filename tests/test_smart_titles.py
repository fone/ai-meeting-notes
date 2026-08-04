"""Tests for AI-generated meeting titles (Task 1 of smart titles plan).

These tests avoid real network calls by injecting fake summarizers and focus on
the contracts in both local and cloud summarizer modules plus NoteMaker title
selection.
"""

from pathlib import Path

import pytest

from meeting_notes.ai_summarizer import BaseSummarizer
from meeting_notes.note_maker import NoteMaker
from meeting_notes.summarizer import MeetingSummary as LocalMeetingSummary, OllamaSummarizer


def _make_summary(title: str | None = None) -> LocalMeetingSummary:
    """Build a minimal MeetingSummary with a configurable title."""
    return LocalMeetingSummary(
        overview="Overview text",
        key_points=["Point one"],
        action_items=[],
        decisions=[],
        participants=[],
        title=title,
    )


class _FakeSummarizer:
    def __init__(self, title: str | None = None, fail: bool = False):
        self.title = title
        self.fail = fail

    def summarize(self, transcript: str, user_notes: str = "") -> LocalMeetingSummary:
        if self.fail:
            raise RuntimeError("model unavailable")
        return _make_summary(title=self.title)


def test_parser_extracts_title_from_response():
    response = """TITLE:
Sprint Planning Review

OVERVIEW:
Team reviewed sprint goals.

KEY POINTS:
- Velocity improved
- API work scoped

ACTION ITEMS:
- None identified

DECISIONS:
- None identified

PARTICIPANTS:
Alice, Bob
"""
    summary = OllamaSummarizer._parse_response(OllamaSummarizer("dummy"), response)
    assert summary.title == "Sprint Planning Review"
    assert "velocity improved" in [p.lower() for p in summary.key_points]


def test_cloud_parser_extracts_title_from_response():
    response = """TITLE:
Cloud Budget Review

OVERVIEW:
Reviewed this month's budget.

KEY POINTS:
- Spending declined

ACTION ITEMS:
- None identified

DECISIONS:
- None identified

PARTICIPANTS:
Adam
"""
    summary = BaseSummarizer()._parse_response(response)
    assert summary.title == "Cloud Budget Review"
    assert summary.overview == "Reviewed this month's budget."


def test_parser_title_optional_when_missing():
    response = """OVERVIEW:
No title provided.

KEY POINTS:
- One point

ACTION ITEMS:
- None identified

DECISIONS:
- None identified

PARTICIPANTS:
Carol
"""
    summary = OllamaSummarizer._parse_response(OllamaSummarizer("dummy"), response)
    assert summary.title is None
    assert summary.overview == "No title provided."


def test_parser_title_ignores_empty_title():
    response = """TITLE:

OVERVIEW:
Blank title line above.

KEY POINTS:
- One point

ACTION ITEMS:
- None identified

DECISIONS:
- None identified

PARTICIPANTS:
Dave
"""
    summary = OllamaSummarizer._parse_response(OllamaSummarizer("dummy"), response)
    assert summary.title is None


def test_meeting_summary_defaults_to_none_title():
    summary = LocalMeetingSummary(
        overview="o",
        key_points=["k"],
        action_items=["a"],
        decisions=["d"],
        participants=["p"],
    )
    assert summary.title is None


def test_note_maker_uses_ai_title_when_no_user_title(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="local",
    )
    maker.summarizer = _FakeSummarizer(title="AI Generated Title")

    note_path, _, _ = maker.create_note(
        transcript_text="We talked about the roadmap.",
        formatted_transcript="We talked about the roadmap.",
        duration=60.0,
        title=None,
    )

    assert Path(note_path).exists()
    note_text = Path(note_path).read_text()
    assert "# AI Generated Title" in note_text
    assert "ai-generated-title" in note_text or "AI Generated Title" in note_text


def test_note_maker_keeps_explicit_user_title(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="local",
    )
    maker.summarizer = _FakeSummarizer(title="Wrong AI Title")

    note_path, _, _ = maker.create_note(
        transcript_text="We talked about the roadmap.",
        formatted_transcript="We talked about the roadmap.",
        duration=60.0,
        title="My Important Meeting",
    )

    note_text = Path(note_path).read_text()
    assert "# My Important Meeting" in note_text
    assert "Wrong AI Title" not in note_text


def test_whitespace_only_user_title_allows_ai_title(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="local",
    )
    maker.summarizer = _FakeSummarizer(title="Roadmap Decisions")

    note_path, _, _ = maker.create_note(
        transcript_text="We agreed on the product roadmap.",
        formatted_transcript="We agreed on the product roadmap.",
        duration=60.0,
        title="   \n  ",
    )

    assert "# Roadmap Decisions" in Path(note_path).read_text()


def test_ai_title_is_normalized_to_one_line(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="local",
    )
    maker.summarizer = _FakeSummarizer(title="Roadmap\nDecisions")

    note_path, _, _ = maker.create_note(
        transcript_text="We agreed on the product roadmap.",
        formatted_transcript="We agreed on the product roadmap.",
        duration=60.0,
        title=None,
    )

    note_text = Path(note_path).read_text()
    assert 'title: "Roadmap Decisions"' in note_text
    assert "# Roadmap Decisions" in note_text


def test_note_maker_falls_back_to_timestamp_when_ai_disabled(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="none",
    )

    note_path, _, _ = maker.create_note(
        transcript_text="Short chat.",
        formatted_transcript="Short chat.",
        duration=30.0,
        title=None,
    )

    note_text = Path(note_path).read_text()
    assert "# Meeting " in note_text


def test_note_maker_falls_back_to_timestamp_on_ai_failure(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="local",
    )
    maker.summarizer = _FakeSummarizer(fail=True)

    note_path, _, error = maker.create_note(
        transcript_text="Short chat.",
        formatted_transcript="Short chat.",
        duration=30.0,
        title=None,
    )

    assert error is not None
    assert "AI summarization failed" in error
    note_text = Path(note_path).read_text()
    assert "# Meeting " in note_text


def test_ai_title_empty_string_ignored(tmp_path):
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="local",
    )
    maker.summarizer = _FakeSummarizer(title="   ")

    note_path, _, _ = maker.create_note(
        transcript_text="No useful title returned.",
        formatted_transcript="No useful title returned.",
        duration=45.0,
        title=None,
    )

    note_text = Path(note_path).read_text()
    assert "# Meeting " in note_text
