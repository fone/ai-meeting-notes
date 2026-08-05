from meeting_notes.ai_summarizer import BaseSummarizer
from meeting_notes.summarizer import OllamaSummarizer


def test_prompt_and_parser_distinguish_names_mentioned_from_attendees():
    summarizer = BaseSummarizer()
    prompt = summarizer._build_prompt("Pete will send the update.")
    assert "NAMES MENTIONED" in prompt
    assert "NOT an attendance roster" in prompt
    assert "explicitly stated" in prompt
    assert "Do NOT infer, complete, guess, or assign identities" in prompt

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
NAMES MENTIONED:
Pete, Adam
"""
    )
    assert summary.participants == ["Pete", "Adam"]


def test_local_ollama_prompt_uses_the_same_explicit_names_contract():
    prompt = OllamaSummarizer()._build_prompt("Pete will send the update.")
    assert "NAMES MENTIONED" in prompt
    assert "NOT an attendance roster" in prompt
    assert "explicitly stated" in prompt
    assert "Do NOT infer, complete, guess, or assign identities" in prompt
    assert "PARTICIPANTS:" not in prompt