"""Headless Textual smoke tests using App.run_test().

These are intentionally minimal — full UI flows are slow and brittle.
We just want to catch:
  - The app actually starts without raising
  - The settings screen opens
  - Switching providers in settings doesn't crash with the duplicate-ID
    error (the bug PR #9 fixed; this is a regression guard)

These tests transitively import whisper (via meeting_notes.app →
meeting_notes.transcriber), which pulls in torch. CI deliberately skips
this file to keep install time fast — see .github/workflows/ci.yml. To
run locally:

    pip install -e ".[all,dev]"
    pytest tests/test_textual_smoke.py
"""
import pytest

# Skip the entire module if the heavy deps (whisper / textual) aren't
# installed. Avoids confusing import errors for contributors who only
# installed the lightweight test deps.
pytest.importorskip("whisper", reason="run `pip install -e .[all,dev]` to enable Textual smoke tests")
pytest.importorskip("textual", reason="run `pip install -e .[all,dev]` to enable Textual smoke tests")

import meeting_notes.app as meeting_app  # noqa: E402
from meeting_notes.app import MeetingNotesApp, RecordingView  # noqa: E402  (deliberate import-after-skip)
from meeting_notes.config import AppConfig, load_config  # noqa: E402
from textual.widgets import Button, Input  # noqa: E402


@pytest.mark.asyncio
async def test_app_starts_and_exits_cleanly(tmp_path, monkeypatch):
    """The app should mount cleanly in headless mode and respond to ctrl+c-equivalent."""
    # Sandbox config & data dirs so the test doesn't touch real ones
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        # Just let the app stabilise. If anything raises during mount,
        # we'd see it here.
        await pilot.pause()
        assert app.is_running
        # Quit cleanly
        app.exit()


@pytest.mark.asyncio
async def test_recording_view_has_clickable_controls(tmp_path, monkeypatch):
    """The recording screen exposes buttons wired to the three real actions."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    calls = []
    monkeypatch.setattr(app, "action_toggle_pause", lambda: calls.append("pause"))
    monkeypatch.setattr(app, "action_stop_recording", lambda: calls.append("stop"))
    monkeypatch.setattr(app, "action_cancel_recording", lambda: calls.append("discard"))

    async with app.run_test() as pilot:
        view = RecordingView()
        await app.mount(view)
        await pilot.pause()

        assert view.query_one("#pause-button", Button).label == "⏸ Pause"
        assert view.query_one("#stop-button", Button).label == "⏹ Stop & Process"
        assert view.query_one("#discard-button", Button).label == "⏏ Discard"

        await pilot.click("#pause-button")
        await pilot.click("#stop-button")
        await pilot.click("#discard-button")
        assert calls == ["pause", "stop", "discard"]

        view.is_paused = True
        await pilot.pause()
        assert view.query_one("#pause-button", Button).label == "▶ Resume"
        app.exit()


@pytest.mark.asyncio
async def test_settings_screen_opens(tmp_path, monkeypatch):
    """Pressing ',' should open the settings screen without error."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(",")
        await pilot.pause()
        # SettingsScreen should now be on the screen stack.
        # (We don't import it for an isinstance check — its exact import
        # path isn't load-bearing; just confirm the stack changed.)
        assert len(app.screen_stack) >= 2, "settings screen should have been pushed"
        app.exit()


@pytest.mark.asyncio
async def test_audio_settings_exposes_diagnostic_temp_policy(tmp_path, monkeypatch):
    """Audio Settings exposes the bounded diagnostic temp-audio controls."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(",")
        await pilot.pause()
        await pilot.click("#section-audio")
        await pilot.pause()

        retention = app.screen.query_one("#diagnostic-temp-retention-input", Input)
        size_cap = app.screen.query_one("#diagnostic-temp-cap-input", Input)
        assert retention.value == "72"
        assert size_cap.value == "20"
        app.exit()


@pytest.mark.asyncio
async def test_audio_settings_save_persists_diagnostic_temp_policy(tmp_path, monkeypatch):
    """Saving Audio Settings applies and persists the diagnostic policy."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    # The defaults intentionally have no Anthropic key. Use the keyless
    # provider so this test exercises Audio Settings persistence, not AI auth.
    app.config.ai_provider = "none"
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(",")
        await pilot.pause()
        await pilot.click("#section-audio")
        await pilot.pause()

        app.screen.query_one("#diagnostic-temp-retention-input", Input).value = "48"
        app.screen.query_one("#diagnostic-temp-cap-input", Input).value = "8"
        await pilot.click("#save-button")
        await pilot.pause()

        assert app.config.diagnostic_temp_retention_hours == 48
        assert app.config.diagnostic_temp_size_cap_gib == 8
        persisted = load_config()
        assert persisted.diagnostic_temp_retention_hours == 48
        assert persisted.diagnostic_temp_size_cap_gib == 8
        app.exit()


@pytest.mark.asyncio
async def test_saving_settings_preserves_ollama_cloud_key(tmp_path, monkeypatch):
    """Any Settings save must retain the active Ollama Cloud credential."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    note_maker_calls = []

    class FakeNoteMaker:
        def __init__(self, **kwargs):
            note_maker_calls.append(kwargs)

    class FakeWhisperTranscriber:
        def __init__(self, *args, **kwargs):
            pass

    class FakeRecorder:
        def __init__(self, *args, **kwargs):
            pass

        def is_recording(self):
            return False

    monkeypatch.setattr(meeting_app, "NoteMaker", FakeNoteMaker)
    monkeypatch.setattr(meeting_app, "WhisperTranscriber", FakeWhisperTranscriber)
    monkeypatch.setattr(meeting_app, "AudioRecorder", FakeRecorder)

    app = MeetingNotesApp()
    note_maker_calls.clear()  # Ignore construction during app startup.
    new_config = AppConfig(
        ai_provider="ollama_cloud",
        ai_model="kimi-k2.6",
        ollama_cloud_api_key="test-ollama-cloud-key",
        notes_dir=str(tmp_path / "notes"),
        transcripts_dir=str(tmp_path / "transcripts"),
        recordings_dir=str(tmp_path / "recordings"),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_settings_closed(new_config)
        assert note_maker_calls[-1]["ai_provider"] == "ollama_cloud"
        assert note_maker_calls[-1]["api_key"] == "test-ollama-cloud-key"
        app.exit()


@pytest.mark.asyncio
async def test_switching_providers_does_not_duplicate_widget_ids(tmp_path, monkeypatch):
    """Regression test for issue #11 / PR #9.

    Switching AI providers used to crash with `DuplicateIds: provider-openai`
    because remove_children() wasn't awaited before mount(). This test
    rapidly clicks between providers and asserts no exception.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(",")  # open settings
        await pilot.pause()

        # Click each provider button in turn.  If remove_children isn't
        # awaited, the second mount of any provider button will raise
        # DuplicateIds.
        provider_ids = ["provider-openai", "provider-anthropic",
                        "provider-openrouter", "provider-anthropic"]
        for pid in provider_ids:
            try:
                await pilot.click(f"#{pid}")
                await pilot.pause()
            except Exception as e:
                # Surface DuplicateIds clearly if it ever comes back
                if "Duplicate" in type(e).__name__ or "already exists" in str(e):
                    pytest.fail(f"PR #9 regressed — DuplicateIds when clicking {pid}: {e}")
                # Other failures (e.g. button not found because layout
                # changed) shouldn't fail this specific regression test
                # — re-raise to fail loudly so the test gets updated.
                raise

        app.exit()
