from meeting_notes.ai_summarizer import BaseSummarizer
from meeting_notes.summarizer import OllamaSummarizer


def test_prompt_and_parser_support_people_with_attendee_fallback():
    summarizer = BaseSummarizer()
    prompt = summarizer._build_prompt("Pete will send the update.")
    assert "OWNERS:" in prompt
    assert "no speaker labels" in prompt
    assert "infer ownership from" in prompt

    summary = summarizer._parse_response(
        """TITLE:
Test
OVERVIEW:
Update.
KEY POINTS:
- One point
ACTION ITEMS:
None identified
DECISIONS:
None identified
OPEN QUESTIONS:
- Who owns this?
OWNERS:
Pete, Adam
"""
    )
    assert summary.participants == ["Pete", "Adam"]
    assert summary.open_questions == ["Who owns this?"]


def test_local_ollama_uses_prompt_v3_and_people_contract():
    prompt = OllamaSummarizer()._build_prompt("Pete will send the update.")
    assert "OWNERS:" in prompt
    assert "<transcript>" in prompt
    assert "PARTICIPANTS:" not in prompt
    assert "ATTENDEES:" in prompt
    assert "ENRICHMENT" in prompt
    assert "UNASSIGNED" in prompt
