"""Tests for Claude Code subscription-backed meeting summarization."""
import json
import subprocess
from types import SimpleNamespace

import pytest
from textual.app import App

from meeting_notes.ai_summarizer import ClaudeCodeSubscriptionSummarizer
from meeting_notes.config import AppConfig, validate_config
from meeting_notes.note_maker import NoteMaker
from meeting_notes.settings import SettingsScreen


VALID_RESPONSE = """TITLE:
Weekly Infrastructure Review
OVERVIEW:
The team reviewed the maintenance plan.
KEY POINTS:
- Patches are ready
ACTION ITEMS:
- Adam to schedule the reboot
DECISIONS:
- Deploy after business hours
OWNERS:
Adam
"""


def _cli_payload(result=VALID_RESPONSE, subtype="success"):
    return json.dumps({"type": "result", "subtype": subtype, "result": result})


def test_claude_code_adapter_uses_safe_stdin_only_contract():
    calls = []

    def fake_runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=_cli_payload(), stderr="")

    summary = ClaudeCodeSubscriptionSummarizer(
        cli_path="/usr/bin/claude", runner=fake_runner,
    ).summarize("Meeting transcript", attendees="Adam")

    command, kwargs = calls[0]
    assert command == [
        "/usr/bin/claude", "-p", "--model", "haiku", "--output-format", "json",
        "--no-session-persistence", "--safe-mode", "--tools", "",
    ]
    assert "Meeting transcript" in kwargs["input"]
    assert "Meeting transcript" not in " ".join(command)
    assert kwargs["text"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 180
    assert kwargs["check"] is False
    assert summary.title == "Weekly Infrastructure Review"
    assert summary.action_items == ["Adam to schedule the reboot"]


def test_claude_code_adapter_rejects_empty_or_failed_results():
    def failed_runner(command, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="authentication expired")

    with pytest.raises(RuntimeError, match="authentication expired"):
        ClaudeCodeSubscriptionSummarizer(cli_path="claude", runner=failed_runner).summarize("text")

    def empty_runner(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=_cli_payload(result=""), stderr="")

    with pytest.raises(RuntimeError, match="no visible summary content"):
        ClaudeCodeSubscriptionSummarizer(cli_path="claude", runner=empty_runner).summarize("text")


def test_claude_code_adapter_handles_timeout_and_prompt_ceiling():
    def timeout_runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 180)

    adapter = ClaudeCodeSubscriptionSummarizer(cli_path="claude", runner=timeout_runner)
    with pytest.raises(RuntimeError, match="timed out"):
        adapter.summarize("text")

    with pytest.raises(RuntimeError, match="too large"):
        adapter.summarize("x" * (adapter.MAX_PROMPT_BYTES + 1))


def test_claude_code_provider_config_requires_haiku_and_installed_cli(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/claude")
    ok, error = validate_config(AppConfig(ai_provider="claude_code_subscription", ai_model="haiku"))
    assert ok, error

    ok, error = validate_config(AppConfig(ai_provider="claude_code_subscription", ai_model="sonnet"))
    assert not ok
    assert error is not None
    assert "Haiku" in error

    monkeypatch.setattr("shutil.which", lambda name: None)
    ok, error = validate_config(AppConfig(ai_provider="claude_code_subscription", ai_model="haiku"))
    assert not ok
    assert error is not None
    assert "CLI not found" in error


def test_note_maker_constructs_claude_code_provider_without_api_key(monkeypatch, tmp_path):
    class FakeSummarizer:
        pass

    monkeypatch.setattr("meeting_notes.note_maker.ClaudeCodeSubscriptionSummarizer", FakeSummarizer)
    maker = NoteMaker(
        output_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        ai_provider="claude_code_subscription",
        ai_model="haiku",
        api_key=None,
    )
    assert isinstance(maker.summarizer, FakeSummarizer)
    assert maker.ai_provider == "claude_code_subscription"


class SettingsHarness(App):
    pass


@pytest.mark.asyncio
async def test_claude_code_provider_screen_is_credential_free():
    app = SettingsHarness()
    async with app.run_test(size=(100, 32)):
        await app.push_screen(SettingsScreen(AppConfig(
            ai_provider="claude_code_subscription", ai_model="haiku",
        )))
        screen = app.screen
        text = "\n".join(str(widget.render()) for widget in screen.query("Static"))
        assert "Claude Code Subscription" in text
        assert "No API key" in text
