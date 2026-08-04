# Recording View Redesign — Phase 1

## Goal
Replace the two-column recording view with a single-column, height-aware layout and one command surface. Do not change audio capture, meter sampling, Whisper, or processing flow.

## Scope
- `meeting_notes/app.py`: introduce a screen-local reactive state (`recording`, `paused`, `confirming_discard`), `ActionBar`, one-column `RecordingView`, inline CSS token block, contextual footer action guard, and inline discard confirmation.
- `tests/test_textual_smoke.py`: RED/GREEN tests for the action bar, discard confirmation, state classes, and hidden library bindings while recording.

## Tasks
1. Add failing Textual tests for `ActionBar` labels/state and single-click discard confirmation.
2. Implement `ActionBar` and refactor `RecordingView` to header, title strip, flexible notes region, and docked action bar. Remove duplicate hints.
3. Replace direct button handling with ActionBar events. Require a second explicit confirmation for discard, keeping the view/meter display mounted.
4. Use the recording view's reactive state only for screen presentation. Continue using existing `AudioRecorder` pause and app-level lifecycle logic.
5. Extend `MeetingNotesApp.check_action()` to suppress library actions while recording.
6. Verify targeted tests, required legacy subset, ruff, 80x24 and 200x60 fake-recorder PTY UI rehearsal, full suite, compile, and `git diff --check`.

## Non-goals
- Do not modify `recorder.py`, `level_meter.py`, `audio_test_screen.py`, transcription, or provider/settings code.
- Do not add dBFS, device names, telemetry, silence UI, JSONL notes, tags, or transcript output changes. Those are later phases.
