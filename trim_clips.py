"""
trim_clips.py — One-time offline script to trim idle padding from CISLR clips.

Strategy:
  Each CISLR clip starts and ends with the signer standing still (hands at
  sides). The actual sign occupies the middle portion. We detect motion in
  the UPPER 60% of the frame (where hands are during signing) by computing
  per-frame pixel difference, then trim the still head/tail.

  Trimmed clips are written to a new directory (cislr_trimmed/).
  The original normalized clips are NOT modified.

  A trimmed vocab JSON is written alongside, with normalized_path updated
  to point to the trimmed clips.

Usage:
  # Subset mode (demo clips only — run this first):
  python trim_clips.py --subset

  # Full mode (all 4765 clips — only after subset is verified):
  python trim_clips.py --full

  # Preview mode (show what would be trimmed without writing files):
  python trim_clips.py --subset --dry-run

Output:
  cislr_trimmed/<uid>.mp4            trimmed clips
  isl_vocab_trimmed.json             vocab with updated normalized_path
  trim_log.json                      per-clip log (durations, trim points, warnings)

Configuration (edit below or set env vars):
  VOCAB_PATH   — path to isl_vocab_full.json
  CLIPS_DIR    — path to cislr_normalized/
  OUT_DIR      — output directory for trimmed clips
  FFMPEG_BIN   — ffmpeg binary
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VOCAB_PATH = os.getenv(
    "ISL_VOCAB_PATH",
    r"C:\Users\aksha\Desktop\asl project\data\isl_explore\isl_vocab_full.json",
)
CLIPS_DIR = os.getenv(
    "ISL_CLIPS_DIR",
    r"C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_normalized",
)
OUT_DIR = os.getenv(
    "ISL_TRIMMED_DIR",
    r"C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_trimmed",
)
FFMPEG_BIN = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")

# Trim parameters
# Adaptive per-clip threshold: real hand-motion is a narrow spike at the top
# of a clip's own scene-score distribution — the rest is compression noise
# even during "idle" stretches — so the threshold is taken as the
# MOTION_PERCENTILE of each clip's own scores, not one fixed value shared
# across all clips. A low percentile (e.g. 30th) lets noise through as
# "active" and barely trims anything. Empirically, the 90th percentile
# reproduces the results of the old fixed 0.008 threshold on clips where
# that threshold worked, and additionally succeeds on gentle-motion clips
# (e.g. pronouns) that the fixed threshold couldn't trim at all — validated
# against backend/services/assembly.py's identical implementation across
# the full 30-clip demo subset (45% avg savings, 0 near-zero-length results).
MOTION_PERCENTILE = 0.9
BUFFER_FRAMES    = 3       # frames of buffer before/after motion window
MIN_RESULT_SEC   = 0.5     # warn if trimmed clip < 0.5s (probably over-trimmed)
MAX_UNCHANGED_RATIO = 0.95 # warn if trimmed duration > 95% of original (barely trimmed)

# Demo subset — clips used in our test sentences
DEMO_CLIPS = {
    "-5lgXJQG0EM_1.mp4", "-Em79Yvwac4_1.mp4", "0DYb-qL1t0A.mp4",
    "1R3n6vTHqzs_1.mp4", "1XLi2MXWjGc_1.mp4", "3fKtgE9aQso.mp4",
    "5FSC6Og1RBQ_2.mp4", "5naqubp3l2I_1.mp4", "6X8mSzwuKWw_1.mp4",
    "7Vn056hXh9U_1.mp4", "7qLPwuH3tVw.mp4",   "AzVqMQPhOWI_1.mp4",
    "BEEOC2ZXhsg.mp4",   "BXw0xmFB8pQ_1.mp4", "Cgs1MibMXJ0.mp4",
    "FCMh8YKvD-8_1.mp4", "FhgAT_pNTIE.mp4",   "IRpEcHFlSk0_1.mp4",
    "Iub1Yb-tOAI.mp4",   "LUwTvq8IlG8_1.mp4", "OvDIlDiFmnU.mp4",
    "P-k3HOBisv8_1.mp4", "PQoocuBF2f8_1.mp4", "Qc72veU0a6g_1.mp4",
    "Qu5KH6X5dd8_1.mp4", "UMGZsGFUVcA_1.mp4", "s13W7g7VnJ8_1.mp4",
    "uqaIszhdKfc.mp4",   "wyu_qsxDouM_1.mp4", "zSXKZb2Frqc_1.mp4",
}


# ---------------------------------------------------------------------------
# ffprobe helpers
# ---------------------------------------------------------------------------

def get_duration(clip_path: str) -> float:
    cmd = [
        FFPROBE_BIN, "-v", "quiet",
        "-print_format", "json",
        "-show_entries", "format=duration",
        clip_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {clip_path}: {r.stderr.strip()}")
    return float(json.loads(r.stdout)["format"]["duration"])


def get_fps(clip_path: str) -> float:
    cmd = [
        FFPROBE_BIN, "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v",
        clip_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return 25.0
    streams = json.loads(r.stdout).get("streams", [{}])
    rr = streams[0].get("r_frame_rate", "25/1")
    num, den = rr.split("/")
    return float(num) / float(den)


# ---------------------------------------------------------------------------
# Motion detection — find active frame range
# ---------------------------------------------------------------------------

def get_motion_scores(clip_path: str) -> list[tuple[float, float]]:
    """
    Return list of (pts_time, scene_score) for every frame.
    Uses ffmpeg scene detection on the upper 60% of the frame only,
    which is where hands appear during signing.
    """
    # crop=w:h:x:y  — keep full width, top 60% of height
    # For 640x480: h = 288, y = 0
    cmd = [
        FFMPEG_BIN, "-i", clip_path,
        "-vf", "crop=iw:ih*0.6:0:0,select='gte(scene,0)',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    lines = r.stdout.splitlines()

    scores: list[tuple[float, float]] = []
    pts = None
    for line in lines:
        if "pts_time:" in line:
            try:
                pts = float(line.split("pts_time:")[1].split()[0])
            except (IndexError, ValueError):
                pts = None
        if "scene_score=" in line and pts is not None:
            try:
                score = float(line.split("scene_score=")[1].split()[0])
                scores.append((pts, score))
                pts = None
            except (IndexError, ValueError):
                pass

    return scores


def find_trim_points(
    scores: list[tuple[float, float]],
    fps: float,
    duration: float,
) -> tuple[float, float]:
    """
    Given per-frame motion scores, return (trim_start, trim_end) in seconds.

    Threshold is MOTION_PERCENTILE of this clip's own score distribution
    (see MOTION_PERCENTILE for why a fixed global threshold doesn't work).
    Finds first and last frame exceeding that threshold, then adds
    BUFFER_FRAMES of padding, clamped to [0, duration].
    """
    if not scores:
        return 0.0, duration

    values = sorted(score for _, score in scores)
    threshold = values[int(len(values) * MOTION_PERCENTILE)]

    active = [pts for pts, score in scores if score >= threshold]

    if not active:
        # No motion detected at all — return full clip (don't trim)
        return 0.0, duration

    frame_dur = 1.0 / fps
    buf = BUFFER_FRAMES * frame_dur

    t_start = max(0.0, min(active) - buf)
    t_end   = min(duration, max(active) + buf)

    return t_start, t_end


# ---------------------------------------------------------------------------
# Trim a single clip
# ---------------------------------------------------------------------------

def trim_clip(
    src: str,
    dst: str,
    t_start: float,
    t_end: float,
) -> bool:
    """
    Write a trimmed copy of src to dst using -c copy (no re-encode).
    Returns True on success.
    """
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", f"{t_start:.4f}",
        "-to", f"{t_end:.4f}",
        "-i", src,
        "-c", "copy",
        dst,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Main processing loop
# ---------------------------------------------------------------------------

def process_clips(clip_paths: list[Path], out_dir: Path, dry_run: bool) -> dict:
    """
    Process a list of clip paths.
    Returns a log dict: {filename: {orig_dur, trim_start, trim_end, result_dur, warning}}
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    log = {}
    total = len(clip_paths)

    for i, src_path in enumerate(clip_paths, 1):
        fname = src_path.name
        dst_path = out_dir / fname
        print(f"[{i:4d}/{total}] {fname}", end=" ... ", flush=True)

        try:
            orig_dur = get_duration(str(src_path))
            fps      = get_fps(str(src_path))
            scores   = get_motion_scores(str(src_path))
            t_start, t_end = find_trim_points(scores, fps, orig_dur)
            result_dur = t_end - t_start

            # Determine warnings
            warnings = []
            if result_dur < MIN_RESULT_SEC:
                warnings.append(f"NEAR_ZERO_LENGTH: result={result_dur:.2f}s")
            if result_dur / orig_dur > MAX_UNCHANGED_RATIO:
                warnings.append(f"BARELY_TRIMMED: {result_dur:.2f}s / {orig_dur:.2f}s")
            if t_start < 0.05 and (orig_dur - t_end) < 0.05:
                warnings.append("NO_TRIM_APPLIED: motion detected full duration")

            log[fname] = {
                "orig_dur":   round(orig_dur, 3),
                "trim_start": round(t_start, 3),
                "trim_end":   round(t_end, 3),
                "result_dur": round(result_dur, 3),
                "saved_sec":  round(orig_dur - result_dur, 3),
                "warnings":   warnings,
            }

            if warnings:
                print("WARN  " + "; ".join(warnings))
            else:
                pct = (1 - result_dur / orig_dur) * 100
                print("OK  %.2fs -> %.2fs (-%.0f%%)" % (orig_dur, result_dur, pct))

            if not dry_run:
                ok = trim_clip(str(src_path), str(dst_path), t_start, t_end)
                if not ok:
                    log[fname]["warnings"].append("FFMPEG_TRIM_FAILED: copied original")
                    # Fall back to copying the original unchanged
                    import shutil
                    shutil.copy2(str(src_path), str(dst_path))

        except Exception as exc:
            print(f"ERROR: {exc}")
            log[fname] = {"error": str(exc), "warnings": ["PROCESSING_FAILED"]}

    return log


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Trim idle padding from CISLR clips.")
    parser.add_argument("--subset", action="store_true",
                        help="Process only the 30 demo clips (run this first)")
    parser.add_argument("--full",   action="store_true",
                        help="Process all 4765 clips")
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyse clips and log results without writing files")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N selected clips (for timing a pilot run)")
    args = parser.parse_args()

    if not args.subset and not args.full:
        parser.print_help()
        sys.exit(1)

    clips_dir = Path(CLIPS_DIR)
    out_dir   = Path(OUT_DIR)
    vocab_path = Path(VOCAB_PATH)

    # Select clips to process
    if args.subset:
        clip_paths = [clips_dir / name for name in sorted(DEMO_CLIPS)
                      if (clips_dir / name).exists()]
        print(f"Subset mode: processing {len(clip_paths)} demo clips")
    else:
        clip_paths = sorted(clips_dir.glob("*.mp4"))
        print(f"Full mode: processing {len(clip_paths)} clips")

    if args.limit is not None:
        clip_paths = clip_paths[:args.limit]
        print(f"--limit {args.limit}: processing only the first {len(clip_paths)} clips")

    if args.dry_run:
        print("DRY RUN -- no files will be written\n")

    t0 = time.time()
    log = process_clips(clip_paths, out_dir, dry_run=args.dry_run)
    elapsed = time.time() - t0

    # Summary stats
    durations = [(v["orig_dur"], v["result_dur"]) for v in log.values()
                 if "orig_dur" in v]
    if durations:
        total_orig   = sum(o for o, _ in durations)
        total_result = sum(r for _, r in durations)
        saved        = total_orig - total_result
        pct_saved    = saved / total_orig * 100 if total_orig else 0
        print(f"\n{'='*60}")
        print(f"Processed : {len(log)} clips in {elapsed:.1f}s")
        print("Total orig : %.1fs  ->  trimmed: %.1fs" % (total_orig, total_result))
        print(f"Saved      : {saved:.1f}s  ({pct_saved:.1f}%)")

    # Warnings summary
    warned = {k: v for k, v in log.items() if v.get("warnings")}
    if warned:
        print(f"\nClips needing review ({len(warned)}):")
        for fname, entry in warned.items():
            print(f"  {fname}: {'; '.join(entry['warnings'])}")

    # Write log
    log_path = Path("trim_log.json")
    with log_path.open("w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=2)
    print(f"\nLog written to: {log_path.resolve()}")

    # Write updated vocab JSON (only in full/subset non-dry-run)
    if not args.dry_run:
        with vocab_path.open(encoding="utf-8") as fh:
            vocab = json.load(fh)

        updated = 0
        for phrase, entry in vocab.items():
            uid = entry.get("uid", "")
            trimmed = out_dir / f"{uid}.mp4"
            if trimmed.exists():
                entry["trimmed_path"] = str(trimmed)
                updated += 1

        trimmed_vocab_path = vocab_path.parent / "isl_vocab_trimmed.json"
        with trimmed_vocab_path.open("w", encoding="utf-8") as fh:
            json.dump(vocab, fh, indent=2)
        print(f"Updated vocab written to: {trimmed_vocab_path}")
        print(f"  {updated} entries now have trimmed_path")


if __name__ == "__main__":
    main()
