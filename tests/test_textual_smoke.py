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
from meeting_notes.app import (  # noqa: E402  (deliberate import-after-skip)
    ActionBar,
    ConfirmDeleteScreen,
    MeetingNotesApp,
    RecordingView,
)
from meeting_notes.config import AppConfig, load_config  # noqa: E402
from textual.widgets import Button, Footer, Input, Static, TextArea  # noqa: E402


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
async def test_delete_confirmation_keeps_thick_border_off_narrow_terminal_edges():
    """The confirmation frame needs breathing room at the common 60-column size."""
    app = MeetingNotesApp()
    async with app.run_test(size=(60, 28)) as pilot:
        app.ansi_color = True
        app.push_screen(ConfirmDeleteScreen("Meeting 2026-08-04 14:09"))
        await pilot.pause()
        dialog = app.screen.query_one("#confirm-dialog")
        assert dialog.region.x > 0
        assert dialog.region.right < 60
        assert app.screen.styles.background.a == 1.0
        app.exit()


@pytest.mark.asyncio
async def test_recording_view_action_bar_requires_discard_confirmation(tmp_path, monkeypatch):
    """Recording commands have one visible surface and discard takes two choices."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    calls = []
    monkeypatch.setattr(app, "action_toggle_pause", lambda: calls.append("pause"))
    monkeypatch.setattr(app, "action_stop_recording", lambda: calls.append("stop"))
    monkeypatch.setattr(app, "action_cancel_recording", lambda: calls.append("discard"))

    async with app.run_test(size=(80, 24)) as pilot:
        view = RecordingView()
        await app.mount(view)
        view.state = "recording"
        await pilot.pause()

        action_bar = view.query_one(ActionBar)
        assert action_bar.region.height > 0
        assert view.query_one("#action-toggle", Button).label == "⏸  Pause  ·  p"
        assert view.query_one("#action-stop", Button).label == "⏹  Stop & Process  ·  s"
        assert view.query_one("#action-discard", Button).label == "⏏  Discard  ·  x"
        assert not list(view.query("#recording-controls"))
        assert not list(view.query("#stop-hint"))
        assert not list(view.query("#esc-hint"))

        await pilot.click("#action-toggle")
        await pilot.click("#action-stop")
        await pilot.click("#action-discard")
        await pilot.pause()
        assert calls == ["pause", "stop"]
        assert view.state == "confirming_discard"
        assert view.query_one("#confirm-discard-yes", Button).display
        assert view.query_one("#level-meter-bar", Static).display

        await pilot.click("#confirm-discard-no")
        await pilot.pause()
        assert calls == ["pause", "stop"]
        assert view.state == "recording"

        app.is_recording = True
        view.screen.set_focus(None)
        await pilot.press("x")
        await pilot.pause()
        assert view.state == "confirming_discard"
        await pilot.press("n")
        await pilot.pause()
        assert view.state == "recording"

        await pilot.click("#action-discard")
        await pilot.click("#confirm-discard-yes")
        assert calls == ["pause", "stop", "discard"]

        view.state = "paused"
        await pilot.pause()
        assert view.query_one("#action-toggle", Button).label == "▶  Resume  ·  p"
        app.exit()



@pytest.mark.asyncio
async def test_recording_view_expands_notes_without_hiding_action_bar(tmp_path, monkeypatch):
    """The flexible notes region grows at desktop size while controls stay visible."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()

    async with app.run_test(size=(200, 60)) as pilot:
        view = RecordingView()
        await app.mount(view)
        await pilot.pause()

        title_strip = view.query_one("#recording-title-strip")
        notes = view.query_one("#recording-notes-region")
        action_bar = view.query_one(ActionBar)
        assert title_strip.region.height > 0
        assert notes.region.height > title_strip.region.height
        assert action_bar.region.height > 0
        assert notes.region.bottom <= action_bar.region.y
        app.exit()


@pytest.mark.asyncio
async def test_recording_view_reserves_footer_and_aligns_action_bar(tmp_path, monkeypatch):
    """Recording content uses the screen flex row; it never consumes the Footer."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for size in ((80, 24), (200, 60)):
        app = MeetingNotesApp()
        async with app.run_test(size=size) as pilot:
            view = RecordingView()
            await app.mount(view)
            view.state = "recording"
            await pilot.pause()

            footer = app.query_one(Footer)
            notes_input = view.query_one("#user-notes-input", TextArea)
            action_bar = view.query_one(ActionBar)
            discard = view.query_one("#action-discard", Button)
            assert footer.region.height > 0
            assert action_bar.region.height == 4
            assert action_bar.region.bottom <= footer.region.y
            assert action_bar.region.x == notes_input.region.x
            assert action_bar.region.right == notes_input.region.right
            assert discard.region.right == notes_input.region.right

            view.state = "paused"
            await pilot.pause()
            assert footer.region.height > 0
            assert action_bar.region.bottom <= footer.region.y
            app.exit()


@pytest.mark.asyncio
async def test_meter_silence_label_presentation_clears_on_signal_return(tmp_path, monkeypatch):
    """The existing silence latch must visibly update and then immediately clear labels."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        view = RecordingView()
        await app.mount(view)
        await pilot.pause()

        _, warned, silent = app._format_level_bar(0.0, "mic", now=100.0)
        assert not warned
        assert not silent
        _, warned, silent = app._format_level_bar(0.0, "mic", now=115.0)
        assert warned
        assert silent
        app._set_meter_label("mic", silent=silent)
        label = view.query_one("#level-meter-label", Static)
        assert str(label.render()) == "MIC QUIET 15s"
        assert label.has_class("silence-warning")

        _, warned, silent = app._format_level_bar(0.1, "mic", now=115.1)
        assert not warned
        assert not silent
        app._set_meter_label("mic", silent=silent)
        assert str(label.render()) == "MIC"
        assert not label.has_class("silence-warning")
        app.exit()


@pytest.mark.asyncio
async def test_routing_block_collapses_when_healthy(tmp_path, monkeypatch):
    """Healthy routing uses no header rows; warnings expand the dedicated block."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        view = RecordingView()
        await app.mount(view)
        await pilot.pause()
        routing = view.query_one("#audio-sources-list", Static)

        app._render_routing_block(routing, [])
        await pilot.pause()
        assert not routing.display

        app._render_routing_block(routing, ["[yellow]⚠ Nothing routing to the captured sink right now[/yellow]"])
        await pilot.pause()
        assert routing.display
        assert "Nothing routing" in str(routing.render())
        app.exit()


@pytest.mark.asyncio
async def test_routing_warning_waits_for_stable_health_before_collapsing(tmp_path, monkeypatch):
    """A flapping route keeps the warning row in place until health is stable."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        view = RecordingView()
        await app.mount(view)
        await pilot.pause()
        routing = view.query_one("#audio-sources-list", Static)
        warning = ["[yellow]⚠ Nothing routing to the captured sink right now[/yellow]"]

        app._render_routing_block(routing, warning)
        monkeypatch.setattr(meeting_app.time, "monotonic", lambda: 100.0)
        app._render_routing_block(routing, [])
        assert routing.display
        app._render_routing_block(routing, warning)
        monkeypatch.setattr(meeting_app.time, "monotonic", lambda: 101.0)
        app._render_routing_block(routing, [])
        assert routing.display
        monkeypatch.setattr(meeting_app.time, "monotonic", lambda: 107.0)
        app._render_routing_block(routing, [])
        assert not routing.display
        app.exit()


@pytest.mark.asyncio
async def test_routing_block_uses_existing_detection_but_hides_healthy_copy(tmp_path, monkeypatch):
    """The routing check remains intact; only its healthy presentation collapses."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()

    class FakeRecorder:
        resolved_system_sink = "captured-sink"

        def is_paused(self):
            return False

        def is_recording(self):
            return False

    async with app.run_test() as pilot:
        app.is_recording = True
        app.recorder = FakeRecorder()
        view = RecordingView()
        await app.mount(view)
        await pilot.pause()
        routing = view.query_one("#audio-sources-list", Static)
        input_on_target = type("SinkInput", (), {"sink": "42", "application": "Zoom", "media_name": ""})()
        monkeypatch.setattr(meeting_app, "list_active_sink_inputs", lambda **_: [input_on_target])
        monkeypatch.setattr("meeting_notes.recorder._sink_index_to_name", lambda: {"42": "captured-sink"})

        app.update_audio_sources_panel()
        await pilot.pause()
        assert not routing.display

        monkeypatch.setattr(meeting_app, "list_active_sink_inputs", lambda **_: [])
        app.update_audio_sources_panel()
        await pilot.pause()
        assert routing.display
        assert "Nothing routing" in str(routing.render())
        app.exit()


@pytest.mark.asyncio
async def test_fake_recorder_starts_and_stops_without_capture_processes(tmp_path, monkeypatch):
    """Recording lifecycle can mount and tear down the redesigned view safely."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()

    class FakeRecorder:
        resolved_system_sink = None
        last_system_silent = False
        last_mic_silent = False
        last_temp_files = []

        def __init__(self):
            self.running = False
            self.started = False
            self.stopped = False
            self.current_file = tmp_path / "recordings" / "fake-recording.wav"

        def is_recording(self):
            return self.running

        def is_paused(self):
            return False

        def get_paused_duration(self):
            return 0.0

        def start_recording(self):
            self.started = True
            self.running = True

        def stop_recording(self):
            self.stopped = True
            self.running = False
            return "fake-recording.wav"

        def _resolve_system_sink(self):
            return None

        def get_audio_device_info(self):
            return {"mode": "mic", "mic_device": "fake-mic"}

    fake = FakeRecorder()
    processed = []
    async with app.run_test(size=(80, 24)) as pilot:
        app.recorder = fake
        monkeypatch.setattr(app, "_start_level_meter", lambda: None)
        monkeypatch.setattr(app, "_stop_level_meter", lambda: None)
        monkeypatch.setattr(app, "update_audio_sources_panel", lambda: None)
        monkeypatch.setattr(app, "process_recording", lambda *args: processed.append(args))
        await app.action_start_recording()
        await pilot.pause()
        assert not fake.started
        assert app.is_preflighting
        app.action_begin_recording()
        await pilot.pause()
        assert fake.started
        assert app.is_recording
        recording_view = app.query_one(RecordingView)
        footer = app.query_one(Footer)
        action_bar = recording_view.query_one(ActionBar)
        notes_input = recording_view.query_one("#user-notes-input", TextArea)
        discard = recording_view.query_one("#action-discard", Button)
        assert footer.region.height > 0
        assert action_bar.region.height == 4
        assert action_bar.region.bottom <= footer.region.y
        assert discard.region.right == notes_input.region.right
        recording_view.query_one("#meeting-title-input", Input).value = "Fake meeting"
        recording_view.query_one("#user-notes-input", TextArea).text = "- durable note"
        await pilot.pause()
        sidecar = fake.current_file.with_suffix(".notes.md")
        assert sidecar.exists()

        app.action_stop_recording()
        await pilot.pause()
        assert fake.stopped
        assert not app.is_recording
        assert not list(app.query(RecordingView))
        assert sidecar.exists()
        assert processed[0][:3] == ("fake-recording.wav", "Fake meeting", "- durable note")
        assert processed[0][3] is not None
        app.exit()


def test_recording_timer_excludes_paused_seconds(tmp_path, monkeypatch):
    """The recording redesign must not regress pause-adjusted elapsed time."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    statuses = []

    class FakeRecorder:
        def get_paused_duration(self):
            return 5.0

        def is_paused(self):
            return True

    app.recorder = FakeRecorder()
    app.is_recording = True
    app.recording_start_time = 100.0
    monkeypatch.setattr(meeting_app.time, "time", lambda: 120.0)
    monkeypatch.setattr(
        app,
        "_write_status_file",
        lambda *args, **kwargs: statuses.append((args, kwargs)),
    )

    app.update_recording_timer()

    assert statuses == [(("paused",), {"duration": "00:15"})]


def test_recording_context_hides_library_actions(tmp_path, monkeypatch):
    """The recording footer keeps Settings/Quit but hides inert library actions."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()
    app.is_recording = True

    for action in (
        "open_in_editor", "copy_to_clipboard", "copy_path", "show_in_folder",
        "delete_meeting", "edit_title", "view_transcript", "manage_tags",
    ):
        assert app.check_action(action, ()) is False
    assert app.check_action("open_settings", ()) is True
    assert app.check_action("quit", ()) is True


@pytest.mark.asyncio
async def test_recording_notes_persist_to_sidecar_while_typing(tmp_path, monkeypatch):
    """A crash after typing notes must not lose the current recording context."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    audio_path = tmp_path / "recordings" / "2026-08-04-120000.wav"
    app.is_recording = True
    app._active_recording_path = audio_path
    async with app.run_test() as pilot:
        await app.mount(RecordingView())
        view = app.query_one(RecordingView)
        view.query_one("#meeting-title-input", Input).value = "Client kickoff"
        view.query_one("#user-notes-input", TextArea).text = "- Ask about timeline"
        await pilot.pause()

        sidecar = audio_path.with_suffix(".notes.md")
        assert sidecar.exists()
        content = sidecar.read_text()
        assert "Client kickoff" in content
        assert "- Ask about timeline" in content
        app.exit()

@pytest.mark.asyncio
async def test_escape_leaves_live_notes_and_e_reopens_context(tmp_path, monkeypatch):
    """Esc must reach the app even when TextArea has consumed normal key events."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        await app.mount(RecordingView())
        view = app.query_one(RecordingView)
        view.state = "recording"
        notes = view.query_one("#user-notes-input", TextArea)
        notes.focus()
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is None
        assert not view.has_class("context-editing")

        await pilot.press("e")
        await pilot.pause()
        assert view.has_class("context-editing")
        assert view.query_one("#meeting-title-input", Input).has_focus
        app.exit()


@pytest.mark.asyncio
async def test_processing_banner_persists_phase_and_hides_after_completion(tmp_path, monkeypatch):
    """The main screen must show durable processing state beyond a toast."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        banner = app.query_one("#processing-banner")
        status = app.query_one("#processing-status", Static)
        assert not banner.display

        app._set_processing_status("Transcribing audio…", "Daily Stand-Up")
        await pilot.pause()
        assert banner.display
        assert "Daily Stand-Up" in str(status.render())
        assert "Transcribing audio" in str(status.render())

        app._clear_processing_status()
        await pilot.pause()
        assert not banner.display
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
