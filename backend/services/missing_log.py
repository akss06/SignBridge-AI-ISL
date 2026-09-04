"""
Missing-words log — a persistent backlog of gloss tokens we couldn't sign.

Every conversion that drops a word (no clip in the CISLR vocab) records it
here. Entries accumulate across all conversions and across restarts, so the
file grows into a prioritized worklist to go through with the ISL user — new
clips or fingerspelling for the words that come up most.

Format (JSON object keyed by the UPPERCASE gloss token):
    {
      "GERMANY": {"count": 4, "first_seen": "...", "last_seen": "..."},
      ...
    }
count is how many conversions dropped that word — sort by it to tackle the
most frequent misses first.

Configuration:
  MISSING_WORDS_LOG — path to the JSON file
                      (default: missing_words.json in the project root).
                      Gitignored: it's local working state, not source.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root

MISSING_WORDS_LOG: str = os.getenv(
    "MISSING_WORDS_LOG", str(_BASE_DIR / "missing_words.json")
)

# Serializes the read-modify-write below — requests run in worker threads
# (asyncio.to_thread), so two conversions can finish at once.
_lock = threading.Lock()


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        # A corrupt/unreadable log must never break a conversion — start fresh.
        logger.warning("Could not read missing-words log (%s); starting empty.", exc)
        return {}


def record_missing(words: Iterable[str]) -> None:
    """
    Merge *words* into the persistent backlog, bumping counts and timestamps.
    Never raises — logging a miss must not fail the pipeline.
    """
    words = [w for w in dict.fromkeys(words) if w]  # dedupe, keep order, drop empties
    if not words:
        return

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = Path(MISSING_WORDS_LOG)

    try:
        with _lock:
            log = _load(path)
            for word in words:
                entry = log.get(word)
                if entry:
                    entry["count"] = entry.get("count", 0) + 1
                    entry["last_seen"] = now
                else:
                    log[word] = {"count": 1, "first_seen": now, "last_seen": now}

            tmp = path.with_suffix(path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(log, fh, ensure_ascii=False, indent=2, sort_keys=True)
            tmp.replace(path)  # atomic — never leaves a half-written log
    except OSError as exc:
        logger.warning("Could not write missing-words log (%s).", exc)
