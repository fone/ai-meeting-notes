# Recording Preflight Workflow

## Goal
Pressing `r` opens a safe preflight screen where mic/system meters and routing can be checked before any meeting WAV, sidecar, timer, or recording status begins. A deliberate Start action begins the existing capture lifecycle.

## State model

- `preflight`: RecordingView mounted; meters/routing active; `is_recording=False`; recorder process not started; no sidecar; no timer.
- `recording`: Existing active capture behavior.
- `paused`: Existing SIGSTOP/SIGCONT behavior. Meters remain stopped while paused.
- `confirming_discard`: Existing active-recording discard guard only.

`preflight` is not `paused`: no audio is being recorded, and its meters must continue updating.

## Tasks

1. **RED tests — `tests/test_textual_smoke.py`**
   - `r`/`action_start_recording()` mounts a `preflight` RecordingView without calling `AudioRecorder.start_recording()`.
   - Preflight starts level-meter/routing refresh but no timer, WAV, or `.notes.md` sidecar.
   - Start control transitions to recording, creates the sidecar only then, starts timer, and preserves the existing stop/process path.
   - Back exits preflight without calling recorder cancellation or creating/deleting recording files.
   - Existing pause/discard behavior remains recording-only.

2. **View and command surface — `meeting_notes/app.py`**
   - Add `preflight` state styling and status copy (`READY TO RECORD`), and a Start/Back ActionBar mode.
   - Route Start and Back buttons/keys to non-destructive app actions.
   - Suppress note-sidecar persistence in preflight by retaining `is_recording=False`.

3. **Lifecycle split — `meeting_notes/app.py`**
   - Split current `action_start_recording()` into preflight entry plus `action_begin_recording()`.
   - Enter preflight: hide main panels, mount view, populate device information, start diagnostics only, and write idle status.
   - Begin recording: call the existing recorder start path, create sidecar, start timer, reset warnings, refresh routing, and change view state to recording.
   - Exit preflight: stop diagnostics/refresh, remove view, restore main panels, leave recorder and persisted recording state untouched.

4. **System-meter target correctness**
   - Use the recorder's normal sink-resolution path for preflight diagnostics where available, but resolve again at actual start so the recorder captures the current active meeting sink.
   - Do not alter audio capture commands, device selection policy, or buffer settings.

5. **Verify**
   - Targeted Textual lifecycle tests, all tests, Ruff, compileall, `git diff --check`.
   - Confirm no recorder/sidecar module diff except app lifecycle integration.
   - Capture 80×24 preflight and paused screenshots with fake recorder; confirm Start/Back controls, meter visibility, footer, and no clipping.

## Acceptance

- `r` never starts an audio capture process or creates a WAV/sidecar.
- Mic/system diagnostic meters and routing panel run in preflight.
- `Start Recording` begins the same capture and persistence lifecycle previously triggered by `r`.
- `Back` leaves no recording artifacts and restores the main screen.
- Paused behavior remains a real paused recording, distinct from preflight.
