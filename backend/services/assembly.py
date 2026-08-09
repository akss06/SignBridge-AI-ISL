"""
Video assembly service — Stage 5.

Takes a list of matched clip paths (from Stage 4) and concatenates them
into a single output ISL video using ffmpeg.

Assembly strategy:
  - All matched clips (within and across sentences) are joined with a
    hard cut via the ffmpeg concat demuxer (-c copy, no re-encode).
    No crossfade — that was the original design but was never
    implemented; do not assume xfade runs anywhere in this file.
  - All clips are video-only (no audio track in CISLR normalized clips).
  - Clips are already h264 / 640×480 / yuv420p / 25fps — confirmed at
    Stage 5 build time. No re-normalization step.

Output: result_<uuid>.mp4 written to the outputs/ directory.
        Returns the URL path (/outputs/result_<uuid>.mp4).

Configuration:
  FFMPEG_BIN   — ffmpeg binary (default: "ffmpeg", or set via env var)
  FFPROBE_BIN  — ffprobe binary (default: "ffprobe", or set via env var)
  OUTPUTS_DIR  — resolved from project root at import time

Head/tail trim:
  Source clips (CISLR normalized_path) carry idle padding — the signer
  standing still before/after the sign — which otherwise makes assembled
  output run several times longer than the actual signing content. Each
  clip is trimmed to its own active (signing) window using the same
  scene-detection approach as trim_clips.py: an adaptive threshold set at
  the MOTION_PERCENTILE of that clip's own scene-score distribution (a
  fixed global threshold either barely trims high-motion signs or
  over-trims gentle ones). Trimmed segments are re-encoded rather than
  stream-copied — this lands cuts at the exact computed timestamp
  instead of snapping to the nearest keyframe, and normalizes every
  segment to identical encoding parameters, which is what makes the
  concat join clean (stream-copied segments from differing source
  encodes can flash/glitch at the cut).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from backend.schemas import PipelineResult, SentenceResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FFMPEG_BIN: str = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE_BIN: str = os.getenv("FFPROBE_BIN", "ffprobe")

# Percentile of a clip's own scene-score distribution used as its motion
# threshold. Real hand-motion is a narrow spike at the top of a clip's own
# score distribution — the rest is compression noise even during "idle"
# stretches — so the threshold needs to sit high (empirically ~90th
# percentile matches the previous fixed 0.008 threshold's own results).
# A low percentile (e.g. 30th) lets noise through as "active" and barely
# trims anything.
MOTION_PERCENTILE: float = 0.9

# Padding around the detected motion window, in seconds (3 frames @ 25fps —
# CISLR clips are confirmed uniform 25fps).
MOTION_BUFFER_SEC: float = 3 / 25

# Never trim a clip down to less than this — protects short/near-minimal
# clips from having real sign content cut off.
MIN_KEEP_SEC: float = 0.4

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



def _get_duration(clip_path: str) -> Optional[float]:
    """Return the clip's duration in seconds via ffprobe, or None on failure."""
    cmd = [
        FFPROBE_BIN, "-v", "quiet",
        "-print_format", "json",
        "-show_entries", "format=duration",
        clip_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def _get_motion_scores(clip_path: str) -> List[Tuple[float, float]]:
    """
    Return (pts_time, scene_score) for every frame, using ffmpeg scene
    detection on the upper 60% of the frame — where hands are during signing.
    Same approach as trim_clips.py's get_motion_scores().
    """
    cmd = [
        FFMPEG_BIN, "-i", clip_path,
        "-vf", "crop=iw:ih*0.6:0:0,select='gte(scene,0)',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    scores: List[Tuple[float, float]] = []
    pts: Optional[float] = None
    for line in result.stdout.splitlines():
        if "pts_time:" in line:
            try:
                pts = float(line.split("pts_time:")[1].split()[0])
            except (IndexError, ValueError):
                pts = None
        if "scene_score=" in line and pts is not None:
            try:
                scores.append((pts, float(line.split("scene_score=")[1].split()[0])))
            except (IndexError, ValueError):
                pass
            pts = None
    return scores


def _adaptive_trim_window(scores: List[Tuple[float, float]], duration: float) -> Tuple[float, float]:
    """
    Find the active (signing) window using a threshold set at
    MOTION_PERCENTILE of this clip's own scene-score distribution, padded
    by MOTION_BUFFER_SEC. Falls back to the full clip if there are no
    scores, or no frame clears the threshold.
    """
    if not scores:
        return 0.0, duration

    values = sorted(score for _, score in scores)
    threshold = values[int(len(values) * MOTION_PERCENTILE)]

    active = [pts for pts, score in scores if score >= threshold]
    if not active:
        return 0.0, duration

    t_start = max(0.0, min(active) - MOTION_BUFFER_SEC)
    t_end = min(duration, max(active) + MOTION_BUFFER_SEC)
    return t_start, t_end


def _trim_head_tail(clip_path: str, tmp_dir: Path) -> str:
    """
    Trim idle head/tail padding off *clip_path* using per-clip adaptive
    motion detection, re-encoding the result so cuts land at the exact
    computed timestamp (not snapped to the nearest keyframe) and every
    output segment shares identical encoding parameters — required for a
    clean concat join.

    Falls back to the original, untrimmed clip path if duration lookup or
    the re-encode fails, or if the detected window is too short to trim
    safely — never raises.
    """
    duration = _get_duration(clip_path)
    if duration is None:
        return clip_path

    scores = _get_motion_scores(clip_path)
    t_start, t_end = _adaptive_trim_window(scores, duration)
    if t_end - t_start < MIN_KEEP_SEC:
        t_start, t_end = 0.0, duration

    trimmed_path = str(tmp_dir / f"trim_{uuid.uuid4().hex[:8]}.mp4")
    cmd = [
        FFMPEG_BIN, "-y",
        "-ss", f"{t_start:.4f}",
        "-to", f"{t_end:.4f}",
        "-i", clip_path,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        trimmed_path,
    ]
    if not _run(cmd, label="adaptive trim + re-encode"):
        return clip_path
    return trimmed_path


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

        # Trim idle head/tail padding off each clip before concat
        trimmed_clips = [_trim_head_tail(clip, tmp_dir) for clip in all_clips]

        if len(trimmed_clips) == 1:
            cmd = [FFMPEG_BIN, "-y", "-i", trimmed_clips[0], "-c", "copy", output_path]
            if not _run(cmd, "copy single clip"):
                raise RuntimeError("Failed to write final output video.")
        else:
            if not _hard_concat(trimmed_clips, output_path, tmp_dir):
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
