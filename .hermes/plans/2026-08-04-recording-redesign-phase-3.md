# Recording View Redesign — Phase 3

## Goal
Make notes typed during a recording durable before transcription begins, and keep their lifecycle bound to the WAV they describe.

## Scope
1. Store an adjacent Markdown sidecar at `<recording-stem>.notes.md` as soon as recording starts.
2. Persist title and notes atomically on every user edit, with recording filename and timestamps in the sidecar header.
3. On Stop, flush the final title/notes before processing; pass the sidecar's note body into the existing summarizer/note-maker path.
4. On Discard, delete the sidecar after the recorder cancel succeeds.
5. Extend normal and diagnostic retention cleanup so deleting a WAV deletes its paired sidecar only. Unrelated Markdown files remain untouched.
6. Add pure sidecar/cleanup tests and Textual smoke coverage for live persistence.

## Non-goals
- Do not change recording capture, transcription, AI prompt format, final meeting-note output, or retention policy knobs.
- Do not add structured action/question/tag schemas. That is output-format work for Phase 4.

## Verification
- Targeted tests before implementation, then full pytest, Ruff, compileall, and capture-path diff check.
- Stop and report at the Phase 3 boundary.
