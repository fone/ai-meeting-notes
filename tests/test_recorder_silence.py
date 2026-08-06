"""Regression coverage for post-recording silence verification."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from meeting_notes.recorder import _is_wav_effectively_silent


def _write_stereo_s16_wav(path: Path, *, signal_second: int | None) -> None:
    """Write five seconds with optional signal outside the old 0/2/4s probes."""
    rate = 8_000
    frames = []
    for second in range(5):
        amplitude = 4_000 if second == signal_second else 0
        for _ in range(rate):
            frames.extend((amplitude, amplitude))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(frames)}h", *frames))


def test_silence_check_detects_brief_signal_between_old_probe_points(tmp_path):
    """Do not call a leg silent just because its speech is intermittent."""
    audio = tmp_path / "intermittent.wav"
    _write_stereo_s16_wav(audio, signal_second=1)

    assert not _is_wav_effectively_silent(audio)


def test_silence_check_accepts_a_truly_silent_file(tmp_path):
    audio = tmp_path / "silent.wav"
    _write_stereo_s16_wav(audio, signal_second=None)

    assert _is_wav_effectively_silent(audio)
