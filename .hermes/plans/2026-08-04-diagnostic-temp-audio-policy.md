# Diagnostic Temp-Audio Policy

## Goal
Stop failed or silent combined-mode captures from leaving unbounded `temp-*.wav` files while preserving short-term diagnostic recovery.

## Architecture
- Add a small, pure `recording_cleanup` module so cleanup policy is tested directly instead of duplicated in tests.
- Keep normal completed recording retention separate from diagnostic temp retention.
- Treat `temp-*.wav` as diagnostic artifacts.
- Default policy: retain diagnostic temps for 72 hours and cap them at 20 GiB, deleting oldest artifacts first when over cap.
- Expose both values in Audio Settings. `0` disables the respective automatic cleanup/cap.

## Tasks
1. **Tests first**: cover normal retention, temp age retention, size-cap eviction, disabled policies, and ignored non-WAV files.
2. **Implementation**: add config fields, validate non-negative values, invoke cleanup at app start, and log all removals.
3. **TUI**: add labeled numeric inputs in Audio Settings; persist and validate the values on Save.
4. **Verification**: run focused tests and full fast suite, compile source, launch/quit the Textual TUI in a PTY, then remove Adam-approved existing test WAVs only after no capture process remains.

## Follow-up required for current runtime
The active profile uses Ollama Cloud. Saving any Audio Setting rebuilds `NoteMaker`, so that callback must forward `ollama_cloud_api_key` (or `OLLAMA_API_KEY`) exactly like the other cloud providers. This is a narrow compatibility fix, not provider-profile work. Add a regression test before changing the callback.

## Out of scope
- Provider-profile UI work, recording provenance/reprocessing, and public-release cleanup.
