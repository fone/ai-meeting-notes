import pytest

pytest.importorskip("whisper", reason="requires Textual meeting-notes dependencies")
pytest.importorskip("textual", reason="requires Textual meeting-notes dependencies")

from meeting_notes import app as meeting_app
from meeting_notes import recorder as recorder_module
from meeting_notes.app import MeetingNotesApp, RecordingView


@pytest.mark.asyncio
async def test_preflight_renders_routing_warning(tmp_path, monkeypatch):
    """Preflight must expose the same routing warning before capture starts."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    app = MeetingNotesApp()

    class FakeRecorder:
        resolved_system_sink = "fake-sink"

        def is_paused(self):
            return False

    app.recorder = FakeRecorder()
    app.is_preflighting = True
    monkeypatch.setattr(meeting_app, "list_active_sink_inputs", lambda **_: [])
    monkeypatch.setattr(recorder_module, "_sink_index_to_name", lambda: {})

    async with app.run_test() as pilot:
        await app.mount(RecordingView())
        app.update_audio_sources_panel()
        await pilot.pause()
        routing = app.query_one(RecordingView).query_one("#audio-sources-list")
        assert routing.display
        assert "Nothing routing" in str(routing.render())
        app.exit()
