# Recording View Redesign — Phase 4

## Goal
Turn live, freeform recording notes into a clean final Obsidian output without changing audio capture, sidecar durability, or the AI prompt.

## Output contract
1. Parse conservative, familiar inline conventions from the sidecar note body:
   - `- [ ] item` or `ACTION: item` → user-captured action item
   - `? question` or `QUESTION: question` → user-captured question
   - `[MM:SS] text` or `@MM:SS text` → recording marker
   - `#tag` → additional Obsidian tag
   - all remaining content stays verbatim in a notes section.
2. Render a `## Live Notes` section before AI output with only non-empty subsections: Action Items, Questions, Markers, Notes.
3. Merge sanitized discovered tags into frontmatter while retaining `meeting` and `auto-generated`.
4. Add a compact convention hint to the recording notes label. Do not require structured input and do not alter the sidecar schema.

## Non-goals
- No LLM schema/prompt changes, no automatic extraction from transcription, no capture changes, no change to sidecar persistence/retention.
- No conversion of old notes or external publication.

## Verification
- RED tests for parsing, Markdown formatting, and NoteMaker integration.
- Full pytest, Ruff, compileall, diff check, and recorder/level-meter empty diff.
- Stop at this final redesign boundary.
