from types import SimpleNamespace

import pytest
from meeting_notes.app import MeetingNotesApp
from meeting_notes.config import AppConfig, load_config, save_config


def test_palette_selection_is_saved_for_next_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = object.__new__(MeetingNotesApp)
    app.config = AppConfig(theme="textual-dark")

    app._persist_selected_theme(SimpleNamespace(name="dracula"))

    assert app.config.theme == "dracula"
    assert load_config().theme == "dracula"


def test_palette_save_ignores_duplicate_theme_change(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = object.__new__(MeetingNotesApp)
    app.config = AppConfig(theme="dracula")

    app._persist_selected_theme(SimpleNamespace(name="dracula"))

    # No config file is created for the initial/current theme notification.
    assert not (tmp_path / "meeting-notes" / "config.yaml").exists()


@pytest.mark.asyncio
async def test_saved_theme_is_applied_on_next_app_mount(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config = AppConfig(
        ai_provider="none",
        theme="dracula",
        notes_dir=str(tmp_path / "notes"),
        recordings_dir=str(tmp_path / "recordings"),
        transcripts_dir=str(tmp_path / "transcripts"),
    )
    save_config(config)
    app = MeetingNotesApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == "dracula"
        app.exit()
