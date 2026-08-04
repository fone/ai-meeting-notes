# Custom AI Provider Settings

## Goal
Make the AI Settings screen production-ready for public sharing. Surface the existing Ollama Cloud backend as a first-class preset, and add one generic OpenAI-compatible custom provider so users can configure their own endpoint, optional API key, and exact model identifier without source edits.

## Scope
- Add `ollama_cloud` and `custom_openai_compatible` provider profiles to Settings.
- Ollama Cloud: fixed endpoint, editable model ID and password-masked key.
- Custom compatible provider: display name, base URL, model ID, optional password-masked key.
- Add a generic OpenAI-compatible summarizer, reusing the exact chat-completions request shape currently used by Ollama Cloud.
- Propagate profile fields through config validation, Settings persistence, app-level `NoteMaker` rebuild, and final summarization.
- Preserve existing OpenAI, Anthropic, OpenRouter, local Ollama, and no-AI behavior.

## Explicit non-goals
- No provider-specific SDK/plugin system.
- No remote model auto-discovery. A model field must remain freeform because compatible endpoints vary.
- No modification of live credentials or the user’s real config file during tests.

## Acceptance criteria
1. Settings visibly offers Ollama Cloud and Custom OpenAI-compatible options.
2. Selecting Ollama Cloud presents model + API key fields and retains the exact configured model/key after Save/reload.
3. Selecting Custom presents name, base URL, model ID, and optional API key fields; all survive Save/reload.
4. Validation requires a syntactically valid HTTP(S) custom base URL and nonempty model ID, while accepting an optional custom key for self-hosted servers.
5. The runtime constructs a generic compatible summarizer with the configured endpoint/model/key. Ollama Cloud continues to use its preset endpoint and current `kimi-k2.6` fallback.
6. Existing config values, including Ollama Cloud credentials, survive unrelated Settings saves.
7. Tests cover config validation, Settings DOM/persistence, active NoteMaker construction, generic request construction, full suite/lint/compile, and a headless visual Settings capture.

## Execution
1. Add failing tests for config/profile persistence and Settings controls.
2. Add profile config fields and a generic compatible summarizer.
3. Wire `NoteMaker`, app initialization/settings reload, and Settings widgets/save handling.
4. Add provider-specific regression tests and visual verification.
5. Run full suite, inspect diff, and commit as one provider-settings feature.
