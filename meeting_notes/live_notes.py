"""Live-note parsing for legacy freeform notes and structured committed entries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .recording_notes import NoteEntry

_ACTION = re.compile(r"^(?:[-*]\s*\[\s?\]\s*|ACTION:\s*)(.+)$", re.IGNORECASE)
_QUESTION = re.compile(r"^(?:\?\s*|QUESTION:\s*)(.+)$", re.IGNORECASE)
_MARKER = re.compile(r"^(?:\[|@)(\d{1,2}:\d{2}(?::\d{2})?)(?:\]|\s)(.*)$")
_TAG = re.compile(r"(?<!\w)#([A-Za-z][\w-]*)")
_TAG_LINE = re.compile(r"^\s*(?:#[A-Za-z][\w-]*\s*)+$")
_LEADING_ABSOLUTE = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]")
_LEADING_RELATIVE = re.compile(r"^\[-(\d+)([ms]?)\]")
_LEADING_ACTION = re.compile(r"^(?:[-*]\s*)?\[\s?\]")
_LEADING_QUESTION = re.compile(r"^\?")


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


def _seconds(stamp: str) -> float:
    units = [int(part) for part in stamp.split(":")]
    if len(units) == 2:
        minutes, seconds = units
        return minutes * 60 + seconds
    hours, minutes, seconds = units
    return hours * 3600 + minutes * 60 + seconds


def format_offset(seconds: float) -> str:
    """Render recording-relative time in the same format as transcript starts."""
    whole = max(0, int(seconds))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def parse_note_entry(text: str, *, offset_s: float, seq: int) -> NoteEntry:
    """Parse optional leading shorthand once, at the instant an entry is committed."""
    remaining = text.strip()
    kind = "note"
    resolved_offset = max(0.0, offset_s)
    while remaining:
        token = remaining.lstrip()
        if match := _LEADING_ABSOLUTE.match(token):
            resolved_offset = _seconds(match.group(1))
            remaining = token[match.end():]
            continue
        if match := _LEADING_RELATIVE.match(token):
            magnitude = int(match.group(1))
            unit = match.group(2) or "s"
            resolved_offset = max(0.0, offset_s - magnitude * (60 if unit == "m" else 1))
            remaining = token[match.end():]
            continue
        if match := _LEADING_ACTION.match(token):
            kind = "action"
            remaining = token[match.end():]
            continue
        if match := _LEADING_QUESTION.match(token):
            kind = "question"
            remaining = token[match.end():]
            continue
        break
    body = remaining.strip()
    tags = _unique([tag.lower() for tag in _TAG.findall(body)])
    if not body and kind == "note":
        kind = "marker"
    return NoteEntry(seq=seq, offset_s=resolved_offset, kind=kind, speaker=None, text=body, tags=tags)


def bare_marker(*, offset_s: float, seq: int) -> NoteEntry:
    return NoteEntry(seq=seq, offset_s=max(0.0, offset_s), kind="marker", speaker=None, text="", tags=[])


def parse_live_notes(text: str) -> LiveNotes:
    """Parse legacy freeform sidecars while preserving ordinary note text."""
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
        action_items=_unique(action_items), questions=_unique(questions), markers=markers,
        tags=_unique(tags), notes="\n".join(remaining).strip(),
    )


def format_live_notes(notes: LiveNotes) -> str:
    """Render populated sections for legacy freeform sidecars."""
    sections: list[str] = []
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


def entries_tags(entries: list[NoteEntry]) -> list[str]:
    return _unique([tag for entry in entries for tag in entry.tags])


def format_note_entries(entries: list[NoteEntry]) -> str:
    """Render committed ledger entries for the final Obsidian note."""
    if not entries:
        return ""
    glyphs = {"note": "•", "action": "[ ]", "question": "?", "marker": "◆"}
    lines: list[str] = []
    for entry in entries:
        prefix = f"- **[{format_offset(entry.offset_s)}]** {glyphs[entry.kind]}"
        lines.append(f"{prefix} {entry.text}".rstrip())
    return "## Live Notes\n\n" + "\n".join(lines)


def entries_for_prompt(entries: list[NoteEntry]) -> str:
    """Provide explicit user-authored ledger content to the existing user-notes block."""
    lines: list[str] = []
    for entry in entries:
        marker = {"action": "[ ] ", "question": "? ", "marker": "", "note": ""}[entry.kind]
        content = f"[{format_offset(entry.offset_s)}] {marker}{entry.text}".rstrip()
        lines.append(content)
    return "\n".join(lines)
