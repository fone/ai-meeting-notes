import pytest

pytest.importorskip("whisper", reason="requires Textual meeting-notes dependencies")
pytest.importorskip("textual", reason="requires Textual meeting-notes dependencies")

from meeting_notes.app import ActionBar, MeetingNotesApp, RecordingView
from textual.widgets import Button


@pytest.mark.asyncio
async def test_preflight_checks_meters_before_starting_recorder(tmp_path, monkeypatch):
    """`r` opens diagnostics only; Start owns all real recording side effects."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()

    class FakeRecorder:
        resolved_system_sink = None

        def __init__(self):
            self.running = False
            self.started = 0
            self.current_file = tmp_path / "recordings" / "preflight.wav"
            self.resolved_system_sink = None

        def is_recording(self):
            return self.running

        def is_paused(self):
            return False

        def start_recording(self):
            self.started += 1
            self.running = True

        def _resolve_system_sink(self):
            self.resolved_system_sink = "preflight-sink"
            return self.resolved_system_sink

        def get_audio_device_info(self):
            return {"mode": "combined", "mic_device": "fake-mic", "system_device": "fake-sink"}

    fake = FakeRecorder()
    meter_starts = []
    routing_refreshes = []
    async with app.run_test(size=(80, 24)) as pilot:
        app.recorder = fake
        monkeypatch.setattr(app, "_start_level_meter", lambda: meter_starts.append(True))
        monkeypatch.setattr(app, "_stop_level_meter", lambda: None)
        monkeypatch.setattr(app, "update_audio_sources_panel", lambda: routing_refreshes.append(True))

        await app.action_start_recording()
        await pilot.pause()

        view = app.query_one(RecordingView)
        bar = view.query_one(ActionBar)
        assert view.state == "preflight"
        assert not app.is_recording
        assert fake.started == 0
        assert fake.resolved_system_sink == "preflight-sink"
        assert meter_starts == [True]
        assert routing_refreshes == [True]
        assert app.timer_interval is None
        assert not fake.current_file.with_suffix(".notes.md").exists()
        assert bar.query_one("#action-begin", Button).display
        assert bar.query_one("#action-back", Button).display

        await pilot.click("#action-begin")
        await pilot.pause()
        assert fake.started == 1
        assert app.is_recording
        assert view.state == "recording"
        assert app.timer_interval is not None
        assert fake.current_file.with_suffix(".notes.md").exists()
        app.exit()


@pytest.mark.asyncio
async def test_preflight_back_restores_main_screen_without_recording_artifacts(tmp_path, monkeypatch):
    """Back ends diagnostics only; it never asks the recorder to cancel output."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()

    class FakeRecorder:
        resolved_system_sink = None

        def __init__(self):
            self.cancelled = False

        def is_recording(self):
            return False

        def _resolve_system_sink(self):
            return None

        def get_audio_device_info(self):
            return {"mode": "mic", "mic_device": "fake-mic"}

        def cancel_recording(self):
            self.cancelled = True

    fake = FakeRecorder()
    async with app.run_test() as pilot:
        app.recorder = fake
        monkeypatch.setattr(app, "_start_level_meter", lambda: None)
        monkeypatch.setattr(app, "_stop_level_meter", lambda: None)
        monkeypatch.setattr(app, "update_audio_sources_panel", lambda: None)
        await app.action_start_recording()
        await pilot.pause()

        await pilot.press("x")
        await pilot.pause()
        assert not app.is_recording
        assert not fake.cancelled
        assert not list(app.query(RecordingView))
        assert app.query_one("#main-panels").display
        app.exit()
