"""
Output video cleanup — deletes old result_*.mp4 files from outputs/.

Run once automatically at server startup (see backend/main.py's lifespan)
and also available as a standalone script (scripts/cleanup_outputs.py) for
on-demand manual sweeps. Only ever touches files matching the
"result_*.mp4" naming convention that assembly.py itself produces — never
touches anything else that might be sitting in outputs/.

Configuration:
  OUTPUT_RETENTION_HOURS — age threshold in hours (default: 24)
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Output directory — project_root/outputs/ (same resolution as assembly.py)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUTS_DIR: Path = _BASE_DIR / "outputs"

DEFAULT_RETENTION_HOURS = 24.0


def _retention_hours_from_env() -> float:
    raw = os.getenv("OUTPUT_RETENTION_HOURS")
    if not raw:
        return DEFAULT_RETENTION_HOURS
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid OUTPUT_RETENTION_HOURS=%r — falling back to default %.1fh",
            raw, DEFAULT_RETENTION_HOURS,
        )
        return DEFAULT_RETENTION_HOURS


def cleanup_old_outputs(
    max_age_hours: Optional[float] = None,
    outputs_dir: Optional[Path] = None,
) -> List[Path]:
    """
    Delete result_*.mp4 files in *outputs_dir* older than *max_age_hours*.

    - *max_age_hours* defaults to the OUTPUT_RETENTION_HOURS env var (or 24h
      if unset).
    - *outputs_dir* defaults to the real outputs/ directory; overridable for
      testing.
    - Age is based on file mtime, so a video still being written or one from
      the current session is never touched — only files whose last
      modification is genuinely older than the threshold.
    - Only matches "result_*.mp4" — never touches unrelated files.

    Returns the list of deleted paths. Safe to call on a missing/empty
    directory (no-op).
    """
    if max_age_hours is None:
        max_age_hours = _retention_hours_from_env()
    if outputs_dir is None:
        outputs_dir = OUTPUTS_DIR

    if not outputs_dir.exists():
        return []

    max_age_seconds = max_age_hours * 3600
    now = time.time()
    deleted: List[Path] = []

    for path in sorted(outputs_dir.glob("result_*.mp4")):
        if not path.is_file():
            continue

        age_seconds = now - path.stat().st_mtime
        if age_seconds < max_age_seconds:
            continue

        age_hours = age_seconds / 3600
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("Failed to delete old output %s: %s", path.name, exc)
            continue

        logger.info(
            "Deleted old output %s (age: %.1fh, threshold: %.1fh)",
            path.name, age_hours, max_age_hours,
        )
        deleted.append(path)

    if deleted:
        logger.info("Output cleanup: removed %d file(s) older than %.1fh", len(deleted), max_age_hours)
    else:
        logger.info("Output cleanup: nothing older than %.1fh", max_age_hours)

    return deleted
