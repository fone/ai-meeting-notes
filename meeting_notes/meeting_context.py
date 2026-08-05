"""Typed meeting context helpers kept separate from live-note marker parsing."""

from __future__ import annotations

from dataclasses import dataclass


def split_csv(value: str) -> list[str]:
    """Split a user-entered comma list without changing the spelling or order."""
    return [item.strip() for item in value.split(",") if item.strip()]


def merge_name_index(existing: list[str], attendees: str) -> list[str]:
    """Add only typed attendee names to the global completion index."""
    merged = list(existing)
    known = {name.casefold() for name in existing}
    for name in split_csv(attendees):
        if name.casefold() not in known:
            merged.append(name)
            known.add(name.casefold())
    return merged


@dataclass(frozen=True)
class MeetingContext:
    title: str = ""
    attendees: str = ""
    glossary: str = ""
    notes: str = ""

    @property
    def has_summary(self) -> bool:
        return bool(self.title or self.attendees or self.glossary)

    def summary(self) -> str:
        """Return the compact in-recording summary, omitting empty portions."""
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        if self.attendees:
            parts.append(f"{len(split_csv(self.attendees))} attendee{'s' if len(split_csv(self.attendees)) != 1 else ''}")
        if self.glossary:
            parts.append(f"{len(split_csv(self.glossary))} term{'s' if len(split_csv(self.glossary)) != 1 else ''}")
        return " · ".join(parts)
