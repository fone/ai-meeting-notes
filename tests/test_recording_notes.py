from datetime import datetime

from meeting_notes.recording_notes import (
    read_recording_notes,
    remove_recording_notes,
    sidecar_path_for,
    write_recording_notes,
)


def test_sidecar_path_is_adjacent_to_its_wav(tmp_path):
    audio = tmp_path / "2026-08-04-120000.wav"
    assert sidecar_path_for(audio) == tmp_path / "2026-08-04-120000.notes.md"


def test_sidecar_round_trips_title_notes_and_recording_name_atomically(tmp_path):
    audio = tmp_path / "2026-08-04-120000.wav"
    updated = datetime(2026, 8, 4, 12, 30, 0)

    sidecar = write_recording_notes(audio, title="Client kickoff", notes="- Ask about timeline", now=updated)

    assert sidecar.exists()
    assert not list(tmp_path.glob(".*.tmp"))
    snapshot = read_recording_notes(audio)
    assert snapshot.recording_file == audio.name
    assert snapshot.title == "Client kickoff"
    assert snapshot.notes == "- Ask about timeline"
    assert snapshot.updated_at == updated


def test_sidecar_removal_only_removes_the_paired_notes_file(tmp_path):
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"wav")
    sidecar = write_recording_notes(audio, title="", notes="keep this safe")
    unrelated = tmp_path / "other.md"
    unrelated.write_text("leave me")

    assert remove_recording_notes(audio)
    assert not sidecar.exists()
    assert audio.exists()
    assert unrelated.exists()
