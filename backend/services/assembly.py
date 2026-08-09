"""
Video assembly service — Stage 5.

Takes a list of matched clip paths (from Stage 4) and concatenates them
into a single output ISL video using ffmpeg.

Assembly strategy:
  - Each matched clip is first re-encoded individually (see
    "Segment normalization" below), then all re-encoded segments are
    joined with a hard cut via the ffmpeg concat demuxer (-c copy — no
    re-encode at the concat step itself, since normalization already
    happened per-clip). No crossfade — that was the original design but
    was never implemented; do not assume xfade runs anywhere in this file.
  - All clips are video-only (no audio track in CISLR normalized clips).
  - Source clips are h264 / 640×480 / yuv420p / 25fps, but NOT assumed
    uniform enough to concat directly — see below for why.

Output: result_<uuid>.mp4 written to the outputs/ directory.
        Returns the URL path (/outputs/result_<uuid>.mp4).

Configuration:
  FFMPEG_BIN   — ffmpeg binary (default: "ffmpeg", or set via env var)
  OUTPUTS_DIR  — resolved from project root at import time

Segment normalization:
  Source clips are pre-trimmed offline by trim_clips.py (idle head/tail
  padding removed via per-clip adaptive motion detection — see that file's
  MOTION_PERCENTILE) and clip_lookup.py serves those trimmed clips by
  default, so no further trimming happens here. Each clip is still
  re-encoded (not stream-copied) before concat, for two reasons found the
  hard way:
    1. Clips pulled from differing source encodes caused a visible
       flash/flicker at each concat join when stream-copied directly —
       re-encoding normalizes every segment to identical parameters.
    2. Re-encoding must also pass `-bf 0` (zero B-frames). Even with
       identical encode parameters, B-frame reordering (decode order !=
       display order) leaves a reordering buffer that doesn't reset
       cleanly at each concat-demuxer file boundary — ffprobe showed
       overlapping/non-monotonic pts_time at every clip join until `-bf 0`
       was added. Do not revert either of these without re-verifying
       frame timestamps are monotonic across a multi-clip concat (see
       git history for the ffprobe check used to diagnose this).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import List

from backend.schemas import PipelineResult, SentenceResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FFMPEG_BIN: str = os.getenv("FFMPEG_BIN", "ffmpeg")

# Output directory — project_root/outputs/
_BASE_DIR = Path(__file__).resolve().parent.parent.parent   # project root
OUTPUTS_DIR: Path = _BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: List[str], label: str = "") -> bool:
    """
    Run an ffmpeg command.  Returns True on success, False on failure.
    Logs stderr on failure so the caller can decide whether to fall back.
    """
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "ffmpeg %s failed (exit %d):\n%s",
            label, result.returncode, result.stderr.strip()
        )
        return False
    return True



def _normalize_clip(clip_path: str, tmp_dir: Path) -> str:
    """
    Re-encode *clip_path* into *tmp_dir* with normalized encoding parameters
    (no trimming — source clips are already trimmed offline by
    trim_clips.py). Two things are required for a clean concat join, both
    found empirically via ffprobe frame-timestamp inspection:
      - Identical encode parameters across every segment (differing source
        encodes caused a visible flash/flicker at each cut when
        stream-copied directly).
      - Zero B-frames (`-bf 0`). Even with matching parameters, B-frame
        reordering leaves a decode/display buffer that doesn't reset
        cleanly at a concat-demuxer file boundary — without this flag,
        ffprobe shows overlapping/non-monotonic pts_time at every join.

    Raises RuntimeError if the re-encode fails — deliberately not a silent
    fallback to the original clip. A fallback here would mean one segment
    keeps its original (non-normalized, possibly B-frame-containing)
    encoding while its neighbors are normalized, which reintroduces the
    exact flicker this function exists to prevent, just for that one clip's
    boundary. Better to surface the failure (caller turns it into a clean
    `error` field via assemble_from_pipeline) than ship a video with a
    silently-degraded join.
    """
    normalized_path = str(tmp_dir / f"norm_{uuid.uuid4().hex[:8]}.mp4")
    cmd = [
        FFMPEG_BIN, "-y",
        "-i", clip_path,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-bf", "0",
        "-an",
        normalized_path,
    ]
    if not _run(cmd, label="normalize clip"):
        raise RuntimeError(f"Failed to normalize clip for assembly: {clip_path}")
    return normalized_path


def _hard_concat(clip_paths: List[str], out_path: str, tmp_dir: Path) -> bool:
    """
    Concatenate clip_paths using the ffmpeg concat demuxer (-c copy, no re-encode).
    Returns True on success, False on failure.
    """
    list_file = tmp_dir / f"concat_{uuid.uuid4().hex[:8]}.txt"
    with list_file.open("w", encoding="utf-8") as fh:
        for p in clip_paths:
            # Use forward slashes and escape single quotes for ffmpeg on Windows
            safe = p.replace("\\", "/").replace("'", "\\'")
            fh.write(f"file '{safe}'\n")

    cmd = [
        FFMPEG_BIN, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        out_path,
    ]
    return _run(cmd, label="hard concat")



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_video(result: PipelineResult) -> str:
    """
    Assemble the final ISL video from all matched clips in *result*.

    - All clips (within and across sentences) are joined with a hard cut.
    - Output written to outputs/result_<uuid>.mp4.

    Returns the URL path string (/outputs/result_<uuid>.mp4).
    Raises RuntimeError if assembly produces no output (0% coverage, ffmpeg crash).
    """
    # Collect all matched clip paths, grouped by sentence
    sentence_clips: List[List[str]] = []
    for sent in result.sentences:
        clips = [gt.clip_path for gt in sent.gloss_tokens if gt.matched and gt.clip_path]
        if clips:
            sentence_clips.append(clips)

    if not sentence_clips:
        raise RuntimeError(
            "No matched clips to assemble — coverage is 0%. "
            "Cannot produce a video with no sign clips."
        )

    output_filename = f"result_{uuid.uuid4().hex}.mp4"
    output_path = str(OUTPUTS_DIR / output_filename)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)

        # Flatten all matched clips across all sentences into one list
        all_clips: List[str] = [
            clip
            for sent_clips in sentence_clips
            for clip in sent_clips
        ]

        # Normalize each clip's encoding parameters before concat (clips are
        # already trimmed offline — see module docstring)
        normalized_clips = [_normalize_clip(clip, tmp_dir) for clip in all_clips]

        if len(normalized_clips) == 1:
            cmd = [FFMPEG_BIN, "-y", "-i", normalized_clips[0], "-c", "copy", output_path]
            if not _run(cmd, "copy single clip"):
                raise RuntimeError("Failed to write final output video.")
        else:
            if not _hard_concat(normalized_clips, output_path, tmp_dir):
                raise RuntimeError("Failed to concatenate clips into final video.")

    return f"/outputs/{output_filename}"


def assemble_from_pipeline(result: PipelineResult) -> PipelineResult:
    """
    Run video assembly and return an updated PipelineResult with
    output_video_url populated.

    On 0% coverage or assembly failure, sets error field instead of raising.
    """
    try:
        url = assemble_video(result)
        return PipelineResult(
            transcript=result.transcript,
            sentences=result.sentences,
            coverage=result.coverage,
            output_video_url=url,
            error=None,
        )
    except RuntimeError as exc:
        return PipelineResult(
            transcript=result.transcript,
            sentences=result.sentences,
            coverage=result.coverage,
            output_video_url=None,
            error=str(exc),
        )
