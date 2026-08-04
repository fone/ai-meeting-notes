# Recording View Redesign — Phase 2

## Goal
Improve recording-view interpretation only. Preserve the existing dual `MicLevelMeter` readers, their subprocess selection, 8 kHz / 100 ms capture, and independent ~12.5 Hz render throttles.

## Scope
1. Add pure meter rendering helpers in `meeting_notes/app.py`: normalized peak to dBFS, `-∞` below -60 dBFS, hold marker with ~1.5 s decay, green/amber/red bands, and a 3-second clip latch.
2. Keep a small per-stream rendering state in `MeetingNotesApp` for mic and system hold, clip, and silence watchdog values.
3. Promote continuous silence to a one-time in-app warning after 15 seconds for either active meter. Preserve logging. Do not add a new capture timer or alter meter process lifecycle.
4. Create `meeting_notes/device_names.py` to resolve Pulse/PipeWire internal source/sink names to human-readable `pactl` descriptions, with a safe fallback. Use it only in the RecordingView device line.
5. Add tests for dBFS/formatting, hold/clip/watchdog behavior, device-name parsing/fallback, and pause timer regression.

## Non-goals
- No change to `level_meter.py`, `recorder.py`, `parec`/`pw-record` selection, sample rate, chunk size, or capture routing.
- No notes sidecar, structured notes, persistence, or output format work.

## Verification
- Targeted unit and Textual tests first, then full pytest, Ruff, compileall, diff check.
- Confirm `git diff HEAD -- meeting_notes/level_meter.py meeting_notes/recorder.py` is empty.
- Stop and report at the Phase 2 boundary.
