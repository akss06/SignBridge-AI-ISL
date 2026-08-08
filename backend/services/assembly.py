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
from typing import List, Optional

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

# Crossfade duration in seconds (200ms = 0.2s)
XFADE_DURATION: float = 0.2

# Frames per second of normalised clips
CLIP_FPS: int = 25


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


def _ffprobe_bin() -> str:
    """
    Derive the ffprobe binary path from FFMPEG_BIN.
    Handles three cases:
      "ffmpeg"                  → "ffprobe"
      "/usr/bin/ffmpeg"         → "/usr/bin/ffprobe"
      "C:\\tools\\ffmpeg.exe"   → "C:\\tools\\ffprobe.exe"
    """
    p = Path(FFMPEG_BIN)
    stem = p.stem.lower().replace("ffmpeg", "ffprobe")
    suffix = p.suffix   # ".exe" on Windows, "" on Unix
    if p.parent == Path("."):
        # bare name — no directory component
        return stem + suffix
    return str(p.parent / (stem + suffix))


def _get_duration(clip_path: str) -> Optional[float]:
    """Return clip duration in seconds via ffprobe, or None on error."""
    cmd = [
        _ffprobe_bin(),
        "-v", "quiet",
        "-print_format", "json",
        "-show_entries", "format=duration",
        clip_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        import json
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return None


def _xfade_pair(clip_a: str, clip_b: str, out_path: str) -> bool:
    """
    Crossfade clip_a → clip_b with a ~200ms xfade and write to out_path.
    Returns True on success, False on failure (caller should hard-cut instead).

    The xfade filter requires knowing when to start the transition:
        offset = duration(clip_a) - XFADE_DURATION
    If offset <= 0 (clip too short), falls back to hard cut.
    """
    dur_a = _get_duration(clip_a)
    if dur_a is None or dur_a <= XFADE_DURATION:
        return False   # clip too short for a crossfade — caller hard-cuts

    offset = dur_a - XFADE_DURATION

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", clip_a,
        "-i", clip_b,
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=fade:duration={XFADE_DURATION}:offset={offset:.4f}[v]",
        "-map", "[v]",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        out_path,
    ]
    return _run(cmd, label=f"xfade {Path(clip_a).name}→{Path(clip_b).name}")


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


def _assemble_sentence(clips: List[str], tmp_dir: Path) -> Optional[str]:
    """
    Assemble a single sentence's clips with crossfades between signs.
    Falls back to hard cut for any pair where xfade fails.

    Returns the path to the assembled sentence clip, or None on total failure.
    """
    if not clips:
        return None
    if len(clips) == 1:
        return clips[0]   # nothing to join

    # Build up by processing pairs: accumulate into a growing intermediate clip
    current = clips[0]

    for idx, next_clip in enumerate(clips[1:], start=1):
        out = str(tmp_dir / f"sent_seg_{idx}_{uuid.uuid4().hex[:6]}.mp4")
        success = _xfade_pair(current, next_clip, out)

        if not success:
            # xfade failed — hard-cut this pair
            logger.info("xfade failed for clip %d, using hard cut", idx)
            hc_out = str(tmp_dir / f"sent_hc_{idx}_{uuid.uuid4().hex[:6]}.mp4")
            if not _hard_concat([current, next_clip], hc_out, tmp_dir):
                logger.warning("Hard concat also failed at clip %d — skipping clip", idx)
                # Keep current unchanged, skip next_clip
                continue
            out = hc_out

        current = out

    return current


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

        # Step 1: assemble each sentence into a single clip
        sentence_parts: List[str] = []
        for s_idx, clips in enumerate(sentence_clips):
            part = _assemble_sentence(clips, tmp_dir)
            if part:
                sentence_parts.append(part)
            else:
                logger.warning("Sentence %d produced no output — skipping", s_idx)

        if not sentence_parts:
            raise RuntimeError("All sentence assemblies failed — no output produced.")

        # Step 2: hard-cut between sentences
        if len(sentence_parts) == 1:
            # Single sentence — just re-encode to output location for consistent container
            cmd = [
                FFMPEG_BIN, "-y",
                "-i", sentence_parts[0],
                "-c", "copy",
                output_path,
            ]
            if not _run(cmd, "copy single sentence"):
                raise RuntimeError("Failed to write final output video.")
        else:
            if not _hard_concat(sentence_parts, output_path, tmp_dir):
                raise RuntimeError("Failed to concatenate sentence clips into final video.")

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
