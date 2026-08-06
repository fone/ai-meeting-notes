"""Parse optional live-note conventions into stable final-note sections."""

from __future__ import annotations

import re
from dataclasses import dataclass

_ACTION = re.compile(r"^(?:[-*]\s*\[\s?\]\s*|ACTION:\s*)(.+)$", re.IGNORECASE)
_QUESTION = re.compile(r"^(?:\?\s*|QUESTION:\s*)(.+)$", re.IGNORECASE)
_MARKER = re.compile(r"^(?:\[|@)(\d{1,2}:\d{2}(?::\d{2})?)(?:\]|\s)(.*)$")
_TAG = re.compile(r"(?<!\w)#([A-Za-z][\w-]*)")
_TAG_LINE = re.compile(r"^\s*(?:#[A-Za-z][\w-]*\s*)+$")


@dataclass(frozen=True)
class LiveNotes:
    action_items: list[str]
    questions: list[str]
    markers: list[tuple[str, str]]
    tags: list[str]
    notes: str


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def parse_live_notes(text: str) -> LiveNotes:
    """Parse optional conventions while preserving ordinary freeform notes."""
    action_items: list[str] = []
    questions: list[str] = []
    markers: list[tuple[str, str]] = []
    tags: list[str] = []
    remaining: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            remaining.append("")
            continue
        tags.extend(tag.lower() for tag in _TAG.findall(stripped))
        if action := _ACTION.match(stripped):
            action_items.append(action.group(1).strip())
        elif question := _QUESTION.match(stripped):
            questions.append(question.group(1).strip())
        elif marker := _MARKER.match(stripped):
            markers.append((marker.group(1), marker.group(2).strip()))
        elif _TAG_LINE.match(stripped):
            continue
        else:
            remaining.append(line.rstrip())

    return LiveNotes(
        action_items=_unique(action_items),
        questions=_unique(questions),
        markers=markers,
        tags=_unique(tags),
        notes="\n".join(remaining).strip(),
    )


def format_live_notes(notes: LiveNotes) -> str:
    """Render populated structured-note sections as Obsidian-flavored Markdown."""
    sections: list[str] = []
    # Freeform text is the primary payload. Put it directly below the parent
    # heading; a nested "Notes" heading only repeated what "Live Notes" says.
    if notes.notes:
        sections.append(notes.notes)
    if notes.action_items:
        sections.append("### Action Items\n\n" + "\n".join(f"- [ ] {item}" for item in notes.action_items))
    if notes.questions:
        sections.append("### Questions\n\n" + "\n".join(f"- {item}" for item in notes.questions))
    if notes.markers:
        markers = "\n".join(f"- **[{stamp}]** {text}".rstrip() for stamp, text in notes.markers)
        sections.append("### Markers\n\n" + markers)
    return "## Live Notes\n\n" + "\n\n".join(sections) if sections else ""
