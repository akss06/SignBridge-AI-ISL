#!/usr/bin/env python
"""
Manual sweep of old result_*.mp4 files in outputs/.

Runs the exact same logic as the automatic startup cleanup
(backend/services/output_cleanup.py) — this just lets you trigger it
on demand instead of waiting for the next server restart.

Usage:
    python scripts/cleanup_outputs.py
    python scripts/cleanup_outputs.py --older-than-hours 1
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from backend.services.output_cleanup import DEFAULT_RETENTION_HOURS, cleanup_old_outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete old result_*.mp4 files from outputs/.")
    parser.add_argument(
        "--older-than-hours",
        type=float,
        default=None,
        help=f"Age threshold in hours (default: OUTPUT_RETENTION_HOURS env var, or {DEFAULT_RETENTION_HOURS}h)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    deleted = cleanup_old_outputs(max_age_hours=args.older_than_hours)
    if not deleted:
        print("No files deleted.")
    else:
        print(f"Deleted {len(deleted)} file(s).")


if __name__ == "__main__":
    main()
