"""Resolve PipeWire/Pulse internal device names for human-facing UI text."""

from __future__ import annotations

import subprocess
from collections.abc import Callable


def parse_pactl_descriptions(output: str) -> dict[str, str]:
    """Return ``pactl list`` Name → Description mappings from its text output."""
    descriptions: dict[str, str] = {}
    current_name: str | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name: "):
            current_name = stripped.removeprefix("Name: ").strip()
        elif stripped.startswith("Description: ") and current_name:
            descriptions[current_name] = stripped.removeprefix("Description: ").strip()
            current_name = None
    return descriptions


def _run_pactl(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=2)
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_device_name(
    name: str | None,
    *,
    kind: str,
    runner: Callable[[list[str]], str] = _run_pactl,
) -> str:
    """Resolve an internal source/sink name, falling back safely to the input."""
    if not name:
        return "default"
    if kind not in {"source", "sink"}:
        raise ValueError("kind must be 'source' or 'sink'")
    descriptions = parse_pactl_descriptions(runner(["pactl", "list", f"{kind}s"]))
    return descriptions.get(name, name)
