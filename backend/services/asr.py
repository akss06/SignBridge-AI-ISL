"""
ASR service — Stage 2.

Responsibilities:
  1. Extract audio from a video file (ffmpeg) when the upload is .mp4.
  2. Run faster-whisper on the audio file and return a plain-text transcript.

The WhisperTranscriber is a module-level singleton so the model is loaded once
and reused across requests.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Model size — "tiny" by default; override via env var if needed
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "tiny")

# ffmpeg binary — assume PATH by default, allow explicit override
FFMPEG_BIN: str = os.getenv("FFMPEG_BIN", "ffmpeg")

# Video file extensions that need audio extraction before transcription
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

_model: Optional[WhisperModel] = None


def get_model() -> WhisperModel:
    """
    Return the shared WhisperModel instance, loading it on first call.
    Uses CPU with int8 quantization as specified.
    """
    global _model
    if _model is None:
        _model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device="cpu",
            compute_type="int8",
        )
    return _model


# ---------------------------------------------------------------------------
# Audio extraction (video → wav)
# ---------------------------------------------------------------------------

def extract_audio(video_path: Path, output_dir: Path) -> Path:
    """
    Extract the audio track from *video_path* to a temporary WAV file
    inside *output_dir* using ffmpeg.

    Raises RuntimeError if ffmpeg exits with a non-zero return code.
    """
    out_path = output_dir / f"audio_{uuid.uuid4().hex}.wav"
    cmd = [
        FFMPEG_BIN,
        "-y",                    # overwrite without asking
        "-i", str(video_path),
        "-vn",                   # no video
        "-acodec", "pcm_s16le",  # standard WAV PCM
        "-ar", "16000",          # 16 kHz — Whisper's native sample rate
        "-ac", "1",              # mono
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg audio extraction failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()}"
        )
    return out_path


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe(audio_path: Path) -> str:
    """
    Run faster-whisper on *audio_path* and return the full transcript as a
    single string (sentences joined by spaces).
    """
    model = get_model()
    segments, _info = model.transcribe(
        str(audio_path),
        beam_size=5,
        language="en",           # English only — ISL pipeline
        condition_on_previous_text=True,
    )
    parts = [seg.text.strip() for seg in segments if seg.text.strip()]
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Top-level helper called by the route (and reused in Stage 6 full pipeline)
# ---------------------------------------------------------------------------

def transcribe_upload(file_path: Path) -> str:
    """
    Accept either an audio or video file path.
    Extracts audio first if the file is a video, then transcribes.
    Returns the plain-text transcript.
    """
    suffix = file_path.suffix.lower()

    if suffix in _VIDEO_EXTENSIONS:
        # Extract audio into the same temp directory as the upload
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = extract_audio(file_path, Path(tmp_dir))
            return transcribe(audio_path)
    else:
        # Already an audio file — transcribe directly
        return transcribe(file_path)
