# Smart Titles and Recording Controls

## Goal
Give untitled meetings a meaningful AI-generated name and make RecordingView operable without memorizing hidden keys.

## Decisions
- An empty title currently becomes `Meeting YYYY-MM-DD HH:MM`; this is not AI-generated. Fix it by adding a `TITLE:` field to the existing single summary response. Do not make a second LLM call or add latency/cost.
- Pause must pause the real capture child processes with `SIGSTOP`/`SIGCONT`, not merely freeze the timer. Resume before graceful stop so WAV writers flush headers normally.
- Keep keyboard actions, but add visible buttons: **Pause / Resume**, **Stop & Process**, and **Discard**. Buttons are controls, not replacement documentation.
- Pause excludes time from displayed and persisted meeting duration. Level meters and routing updates stop while paused to avoid showing capture activity that is not being recorded.

## Tasks
1. **Title TDD:** Add tests for an AI suggested title, an explicit user title winning, and timestamp fallback if AI is unavailable. Extend both cloud and local summary contracts with a parsed `TITLE:` field. Make NoteMaker select the final title only after summarization.
2. **Recorder TDD:** Add fake-process tests for pause, resume, stop-from-paused, cancel-from-paused, and invalid state behavior. Add `AudioRecorder.pause_recording()` / `resume_recording()` with clear state and signal handling.
3. **TUI controls:** Add state-aware buttons and `p` shortcut. Update status, timer accounting, Waybar status, meters, and routing refresh during pause/resume. Keep inputs from swallowing global shortcuts.
4. **Verification:** Run focused unit/Textual tests, the full suite, lint/compile, and a real PTY TUI launch with controls visible. Do not create a real recording as part of UI smoke.
