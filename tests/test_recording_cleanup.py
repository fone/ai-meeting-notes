"""Tests for the pure recording_cleanup module.

These cover the approved diagnostic temp-audio policy:
* normal recordings keep the existing 30-day retention,
* temp-*.wav files are diagnostic and use a separate retention rule,
* temp files have a size cap with oldest-first eviction,
* 0 disables the respective automatic cleanup/cap,
* non-WAV files are ignored.
"""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from meeting_notes.recording_cleanup import (
    CleanupPolicy,
    cleanup_recordings,
    _is_temp_wav,
)


def _set_mtime(path: Path, when: datetime) -> None:
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def _write_sized_file(path: Path, size_bytes: int) -> None:
    """Create a sparse file with a logical size, without consuming disk."""
    with path.open("wb") as handle:
        handle.truncate(size_bytes)


def _hours_ago(hours: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now()) - timedelta(hours=hours)


def _days_ago(days: int, now: datetime | None = None) -> datetime:
    return (now or datetime.now()) - timedelta(days=days)


def test_normal_retention_deletes_old_completed_wavs(tmp_path):
    now = datetime.now()
    old = tmp_path / "2026-08-01-120000.wav"
    new = tmp_path / "2026-08-04-120000.wav"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    _set_mtime(old, _days_ago(35, now))
    _set_mtime(new, _days_ago(5, now))

    policy = CleanupPolicy(normal_retention_days=30)
    removed = cleanup_recordings(tmp_path, policy, now=now)

    assert old.name in removed
    assert not old.exists()
    assert new.exists()


def test_wav_cleanup_removes_only_its_paired_notes_sidecar(tmp_path):
    now = datetime.now()
    old = tmp_path / "2026-08-01-120000.wav"
    sidecar = tmp_path / "2026-08-01-120000.notes.md"
    unrelated = tmp_path / "unrelated.md"
    for path in (old, sidecar, unrelated):
        path.write_text("x")
    _set_mtime(old, _days_ago(35, now))

    cleanup_recordings(tmp_path, CleanupPolicy(normal_retention_days=30), now=now)

    assert not old.exists()
    assert not sidecar.exists()
    assert unrelated.exists()


def test_normal_retention_zero_disables_age_cleanup(tmp_path):
    now = datetime.now()
    normal = tmp_path / "2025-01-01-120000.wav"
    normal.write_bytes(b"x")
    _set_mtime(normal, _days_ago(365, now))

    removed = cleanup_recordings(tmp_path, CleanupPolicy(normal_retention_days=0), now=now)

    assert removed == []
    assert normal.exists()


def test_temp_retention_deletes_old_diagnostic_files(tmp_path):
    now = datetime.now()
    old_temp = tmp_path / "temp-mic-2026-08-01-120000.wav"
    new_temp = tmp_path / "temp-system-2026-08-04-120000.wav"
    old_normal = tmp_path / "2026-08-01-120000.wav"
    for p in (old_temp, new_temp, old_normal):
        p.write_bytes(b"x")
    _set_mtime(old_temp, _hours_ago(96, now))
    _set_mtime(new_temp, _hours_ago(12, now))
    _set_mtime(old_normal, _hours_ago(96, now))

    policy = CleanupPolicy(temp_retention_hours=72)
    removed = cleanup_recordings(tmp_path, policy, now=now)

    assert old_temp.name in removed
    assert old_normal.name not in removed  # normal retention not triggered here
    assert not old_temp.exists()
    assert new_temp.exists()
    assert old_normal.exists()


def test_temp_retention_zero_disables_age_cleanup(tmp_path):
    now = datetime.now()
    ancient_temp = tmp_path / "temp-mic-2025-01-01-120000.wav"
    ancient_temp.write_bytes(b"x")
    _set_mtime(ancient_temp, _days_ago(365, now))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(normal_retention_days=0, temp_retention_hours=0),
        now=now,
    )

    assert removed == []
    assert ancient_temp.exists()


def test_temp_size_cap_evicts_oldest_first(tmp_path):
    now = datetime.now()
    oldest = tmp_path / "temp-mic-2026-08-01-120000.wav"
    middle = tmp_path / "temp-system-2026-08-02-120000.wav"
    newest = tmp_path / "temp-mic-2026-08-04-120000.wav"
    # 2 GiB each, 4 GiB cap: the newest two files should survive.
    for idx, p in enumerate((oldest, middle, newest)):
        _write_sized_file(p, 2 * 1024 * 1024 * 1024)
        _set_mtime(p, now - timedelta(days=3 - idx))

    policy = CleanupPolicy(
        normal_retention_days=0,
        temp_retention_hours=0,
        temp_size_cap_gib=4,
    )
    removed = cleanup_recordings(tmp_path, policy, now=now)

    assert oldest.name in removed
    assert middle.exists()
    assert newest.exists()


def test_temp_size_cap_zero_disables_eviction(tmp_path):
    now = datetime.now()
    temp = tmp_path / "temp-mic-2026-08-01-120000.wav"
    _write_sized_file(temp, 5 * 1024 * 1024 * 1024)
    _set_mtime(temp, _hours_ago(1, now))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(temp_retention_hours=0, temp_size_cap_gib=0),
        now=now,
    )

    assert removed == []
    assert temp.exists()


def test_size_cap_only_considers_temp_files(tmp_path):
    now = datetime.now()
    big_normal = tmp_path / "2026-08-01-120000.wav"
    temp = tmp_path / "temp-mic-2026-08-01-120000.wav"
    _write_sized_file(big_normal, 3 * 1024 * 1024 * 1024)
    temp.write_bytes(b"x")
    _set_mtime(temp, _hours_ago(1, now))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(normal_retention_days=0, temp_retention_hours=0, temp_size_cap_gib=1),
        now=now,
    )

    assert removed == []  # temp is tiny, cap is not breached
    assert big_normal.exists()
    assert temp.exists()


def test_ignored_non_wav_files(tmp_path):
    now = datetime.now()
    old_txt = tmp_path / "temp-mic-2026-08-01-120000.txt"
    old_md = tmp_path / "old.md"
    old_log = tmp_path / "temp.log"
    for p in (old_txt, old_md, old_log):
        p.write_bytes(b"x")
        _set_mtime(p, _days_ago(365, now))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(normal_retention_days=30, temp_retention_hours=72),
        now=now,
    )

    assert removed == []
    assert old_txt.exists()
    assert old_md.exists()
    assert old_log.exists()


def test_is_temp_wav_recognition():
    assert _is_temp_wav(Path("temp-mic-2026-08-04-120000.wav"))
    assert _is_temp_wav(Path("TEMP-MIC.wav"))
    assert not _is_temp_wav(Path("2026-08-04-120000.wav"))
    assert not _is_temp_wav(Path("temporary.wav"))
    assert not _is_temp_wav(Path("temp.txt"))


def test_negative_policy_values_are_rejected():
    with pytest.raises(ValueError, match="normal_retention_days"):
        CleanupPolicy(normal_retention_days=-1)
    with pytest.raises(ValueError, match="temp_retention_hours"):
        CleanupPolicy(temp_retention_hours=-1)
    with pytest.raises(ValueError, match="temp_size_cap_gib"):
        CleanupPolicy(temp_size_cap_gib=-1)


def test_missing_directory_is_noop(tmp_path):
    missing = tmp_path / "does-not-exist"
    removed = cleanup_recordings(
        missing,
        CleanupPolicy(normal_retention_days=30, temp_retention_hours=72),
    )
    assert removed == []


def test_normal_and_temp_policies_run_independently(tmp_path):
    now = datetime.now()
    old_normal = tmp_path / "2026-07-01-120000.wav"
    old_temp = tmp_path / "temp-mic-2026-07-01-120000.wav"
    fresh_temp = tmp_path / "temp-system-2026-08-04-120000.wav"
    for p in (old_normal, old_temp, fresh_temp):
        p.write_bytes(b"x")
    _set_mtime(old_normal, _days_ago(60, now))
    _set_mtime(old_temp, _hours_ago(96, now))
    _set_mtime(fresh_temp, _hours_ago(12, now))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(normal_retention_days=30, temp_retention_hours=72),
        now=now,
    )

    assert old_normal.name in removed
    assert old_temp.name in removed
    assert fresh_temp.exists()
    assert fresh_temp.name not in removed


def test_size_cap_with_no_temp_files_is_noop(tmp_path):
    now = datetime.now()
    normal = tmp_path / "2026-08-04-120000.wav"
    _write_sized_file(normal, 10 * 1024 * 1024 * 1024)
    _set_mtime(normal, _days_ago(1, now))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(normal_retention_days=0, temp_retention_hours=0, temp_size_cap_gib=1),
        now=now,
    )
    assert removed == []
    assert normal.exists()


def test_exact_boundary_files_are_kept(tmp_path):
    now = datetime.now()
    normal = tmp_path / "2026-08-01-120000.wav"
    normal.write_bytes(b"x")
    _set_mtime(normal, now - timedelta(days=30))

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(normal_retention_days=30),
        now=now,
    )
    assert removed == []
    assert normal.exists()


def test_unlink_failure_is_logged_but_not_raised(tmp_path, monkeypatch, caplog):
    now = datetime.now()
    caplog.set_level("WARNING", logger="meeting_notes.recording_cleanup")
    temp = tmp_path / "temp-mic-2026-08-01-120000.wav"
    temp.write_bytes(b"x")
    _set_mtime(temp, _hours_ago(96, now))

    original_unlink = Path.unlink

    def broken_unlink(self, missing_ok=False):
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "unlink", broken_unlink)

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(temp_retention_hours=72),
        now=now,
    )

    assert removed == []
    assert "Failed to remove" in caplog.text
    monkeypatch.setattr(Path, "unlink", original_unlink)


def test_size_cap_stops_if_unlink_fails(tmp_path, monkeypatch, caplog):
    now = datetime.now()
    caplog.set_level("INFO", logger="meeting_notes.recording_cleanup")
    a = tmp_path / "temp-a.wav"
    b = tmp_path / "temp-b.wav"
    for p, days in ((a, 2), (b, 1)):
        _write_sized_file(p, 2 * 1024 * 1024 * 1024)
        _set_mtime(p, now - timedelta(days=days))

    call_count = 0
    original_unlink = Path.unlink

    def flaky_unlink(self, missing_ok=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise PermissionError("nope")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    removed = cleanup_recordings(
        tmp_path,
        CleanupPolicy(temp_retention_hours=0, temp_size_cap_gib=1),
        now=now,
    )

    assert a.name not in removed  # first unlink failed
    assert b.name not in removed  # we stop after first failure
    monkeypatch.undo()
