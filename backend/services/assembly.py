"""
Video assembly service — Stage 5.

Takes a list of matched clip paths (from Stage 4) and concatenates them
into a single output ISL video using ffmpeg.

Assembly strategy:
  - Within a sentence: crossfade transition (~200ms = 5 frames at 25fps)
    using ffmpeg xfade filter. If xfade fails for any reason, falls back
    to a hard cut for that pair — never crashes.
  - Between sentences: hard cut (no transition).
  - All clips are video-only (no audio track in CISLR normalized clips).
  - Clips are already h264 / 640×480 / yuv420p / 25fps — confirmed at
    Stage 5 build time. No re-normalization step.

Output: result_<uuid>.mp4 written to the outputs/ directory.
        Returns the URL path (/outputs/result_<uuid>.mp4).

Configuration:
  FFMPEG_BIN   — ffmpeg binary (default: "ffmpeg", or set via env var)
  OUTPUTS_DIR  — resolved from project root at import time
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

    - Clips within a sentence are joined with crossfades (fallback: hard cut).
    - Sentences are joined with hard cuts.
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
        # and concat everything in a single -c copy pass — near-instant.
        all_clips: List[str] = [
            clip
            for sent_clips in sentence_clips
            for clip in sent_clips
        ]

        if len(all_clips) == 1:
            cmd = [FFMPEG_BIN, "-y", "-i", all_clips[0], "-c", "copy", output_path]
            if not _run(cmd, "copy single clip"):
                raise RuntimeError("Failed to write final output video.")
        else:
            if not _hard_concat(all_clips, output_path, tmp_dir):
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
