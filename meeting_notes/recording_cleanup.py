"""Pure cleanup policy for meeting recordings.

This module is intentionally dependency-light so the cleanup rules can be
tested directly without spinning up a Textual app instance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CleanupPolicy:
    """Policy knobs for automatic recording cleanup.

    Attributes:
        normal_retention_days: days to keep completed non-diagnostic WAVs.
            ``0`` disables age-based cleanup for normal recordings.
        temp_retention_hours: hours to keep diagnostic ``temp-*.wav`` files.
            ``0`` disables age-based cleanup for temp files.
        temp_size_cap_gib: maximum total size in GiB for ``temp-*.wav`` files.
            ``0`` disables size-cap eviction for temp files.
    """

    normal_retention_days: int = 30
    temp_retention_hours: int = 72
    temp_size_cap_gib: int = 20

    def __post_init__(self) -> None:
        for name, value in (
            ("normal_retention_days", self.normal_retention_days),
            ("temp_retention_hours", self.temp_retention_hours),
            ("temp_size_cap_gib", self.temp_size_cap_gib),
        ):
            if value < 0:
                raise ValueError(f"{name} must be non-negative, got {value}")


def _format_bytes(num_bytes: int) -> str:
    """Return a human-readable byte string."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes = int(num_bytes / 1024)
    return f"{num_bytes} PiB"


def _iter_wav_files(directory: Path) -> Iterable[Path]:
    """Yield WAV files in directory, skipping non-files and dotfiles."""
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file() and path.suffix.lower() == ".wav":
            yield path


def _is_temp_wav(path: Path) -> bool:
    """Diagnostic temp files match ``temp-*.wav``.

    Normal completed WAVs (e.g. ``2026-08-04-100146.wav``) do not match.
    """
    return path.name.lower().startswith("temp-")


def _age_cutoff_hours(hours: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    return now - timedelta(hours=hours)


def _age_cutoff_days(days: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    return now - timedelta(days=days)


def cleanup_recordings(
    recordings_dir: Path,
    policy: CleanupPolicy,
    now: datetime | None = None,
) -> list[str]:
    """Apply retention policy to a recordings directory.

    Returns:
        Names of files removed.

    Notes:
        * Normal ``*.wav`` files are removed when older than
          ``policy.normal_retention_days``. ``0`` disables this.
        * Diagnostic ``temp-*.wav`` files are removed when older than
          ``policy.temp_retention_hours``. ``0`` disables this.
        * After age cleanup, if ``policy.temp_size_cap_gib > 0``, temp files
          are evicted oldest-first until the total is under the cap.
        * Non-WAV files are never touched.
    """
    now = now or datetime.now()
    removed: list[str] = []

    if not recordings_dir.is_dir():
        logger.debug("Recordings directory does not exist: %s", recordings_dir)
        return removed

    # Phase 1: age-based cleanup
    if policy.normal_retention_days > 0:
        normal_cutoff = _age_cutoff_days(policy.normal_retention_days, now)
        for wav in _iter_wav_files(recordings_dir):
            if _is_temp_wav(wav):
                continue
            mtime = datetime.fromtimestamp(wav.stat().st_mtime)
            if mtime < normal_cutoff:
                try:
                    wav.unlink()
                    removed.append(wav.name)
                    logger.info(
                        "Removed old recording %s (mtime %s, older than %s days)",
                        wav.name,
                        mtime.isoformat(),
                        policy.normal_retention_days,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to remove %s: %s", wav.name, exc)

    if policy.temp_retention_hours > 0:
        temp_cutoff = _age_cutoff_hours(policy.temp_retention_hours, now)
        for wav in _iter_wav_files(recordings_dir):
            if not _is_temp_wav(wav):
                continue
            mtime = datetime.fromtimestamp(wav.stat().st_mtime)
            if mtime < temp_cutoff:
                try:
                    wav.unlink()
                    removed.append(wav.name)
                    logger.info(
                        "Removed old diagnostic temp audio %s (mtime %s, older than %s hours)",
                        wav.name,
                        mtime.isoformat(),
                        policy.temp_retention_hours,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to remove %s: %s", wav.name, exc)

    # Phase 2: temp size cap
    if policy.temp_size_cap_gib > 0:
        cap_bytes = policy.temp_size_cap_gib * 1024 * 1024 * 1024
        temp_files = sorted(
            (
                wav
                for wav in _iter_wav_files(recordings_dir)
                if _is_temp_wav(wav)
            ),
            key=lambda p: p.stat().st_mtime,
        )
        total_bytes = sum(p.stat().st_size for p in temp_files)
        if total_bytes > cap_bytes:
            logger.info(
                "Diagnostic temp audio size %s exceeds cap %s GiB; evicting oldest first",
                _format_bytes(total_bytes),
                policy.temp_size_cap_gib,
            )
        while total_bytes > cap_bytes and temp_files:
            oldest = temp_files.pop(0)
            size = oldest.stat().st_size
            try:
                oldest.unlink()
                removed.append(oldest.name)
                total_bytes -= size
                logger.info(
                    "Evicted diagnostic temp audio %s (%s) to keep temp storage under %s GiB",
                    oldest.name,
                    _format_bytes(size),
                    policy.temp_size_cap_gib,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to evict %s: %s", oldest.name, exc)
                # Don't loop forever on an undeletable file; stop trying to
                # shrink the cap for this run.
                break

    return removed
