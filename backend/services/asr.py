"""
ASR service — Stage 2.

Responsibilities:
  1. Extract audio from a video file (ffmpeg) when the upload is .mp4.
  2. Run faster-whisper on the audio file and return a plain-text transcript.

Models are cached one per device (cpu/cuda) and reused across requests — the
first cpu call and the first cuda call each load their model once. The device
can be chosen per request (transcribe_upload(device=...), driven by the
frontend's CPU/GPU toggle) or defaulted via the ASR_DEVICE env var. On Windows,
the CUDA runtime DLLs shipped by the nvidia-* pip wheels are registered
automatically before a GPU load (see _register_cuda_dll_dirs).
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

# Model size — "small" by default (matches README / .env.example baseline);
# override via env var (tiny | base | small | medium | large-v3).
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "small")

# Default compute device — "cpu". Set ASR_DEVICE=cuda to default to the GPU.
# A request can also override this per-call (see transcribe_upload(device=...)),
# which is how the frontend's CPU/GPU toggle picks the device for one job.
ASR_DEVICE: str = os.getenv("ASR_DEVICE", "cpu")

# Devices we accept — anything else is rejected rather than passed to the model.
_VALID_DEVICES = {"cpu", "cuda"}

# Optional precision override. If unset, precision is chosen per device:
# int8 on CPU (fast, low memory), float16 on GPU (fast, accurate). Set
# explicitly to benchmark other combos, e.g. ASR_COMPUTE_TYPE=int8_float16.
_ASR_COMPUTE_TYPE_OVERRIDE: Optional[str] = os.getenv("ASR_COMPUTE_TYPE")


def _compute_type_for(device: str) -> str:
    if _ASR_COMPUTE_TYPE_OVERRIDE:
        return _ASR_COMPUTE_TYPE_OVERRIDE
    return "float16" if device == "cuda" else "int8"

# ffmpeg binary — assume PATH by default, allow explicit override
FFMPEG_BIN: str = os.getenv("FFMPEG_BIN", "ffmpeg")

# Video file extensions that need audio extraction before transcription
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

def _register_cuda_dll_dirs() -> None:
    """
    On Windows, make the CUDA 12 runtime DLLs shipped by the nvidia-* pip
    wheels (nvidia-cublas-cu12, nvidia-cudnn-cu12) discoverable before a GPU
    model load. Those wheels drop their DLLs under site-packages/nvidia/*/bin,
    which Windows does not search by default — and CTranslate2, unlike PyTorch,
    won't register them for us, so a cuda load fails with
    "cublas64_12.dll is not found" until we add them here.

    Both mechanisms below are needed: os.add_dll_directory lets Python's own
    loader find the DLLs, but CTranslate2's internal C++ loader searches the
    plain PATH instead — so the directories must be prepended to PATH as well,
    or the cuda load fails with "cublas64_12.dll is not found" even though the
    file is present.

    No-op on non-Windows and when the packages aren't installed (CPU is
    unaffected either way).
    """
    if os.name != "nt":
        return
    import importlib.util

    spec = importlib.util.find_spec("nvidia")
    if not spec or not spec.submodule_search_locations:
        return
    nvidia_root = Path(list(spec.submodule_search_locations)[0])
    for bin_dir in nvidia_root.glob("*/bin"):
        if not bin_dir.is_dir():
            continue
        bin_str = str(bin_dir)
        try:
            os.add_dll_directory(bin_str)
        except OSError:
            pass
        # CTranslate2 loads its CUDA deps via PATH, not add_dll_directory.
        if bin_str not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = bin_str + os.pathsep + os.environ.get("PATH", "")


# One cached model per device. A CPU and a GPU request each load their model
# once, then reuse it — loading per request would cost seconds every time.
_models: dict[str, WhisperModel] = {}


def get_model(device: Optional[str] = None) -> WhisperModel:
    """
    Return the shared WhisperModel for *device* (default: ASR_DEVICE), loading
    and caching it on first use. Raises ValueError for an unsupported device.
    """
    dev = (device or ASR_DEVICE).lower()
    if dev not in _VALID_DEVICES:
        raise ValueError(
            f"Unsupported ASR device {dev!r}; expected one of {sorted(_VALID_DEVICES)}."
        )
    if dev not in _models:
        if dev == "cuda":
            _register_cuda_dll_dirs()
        _models[dev] = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=dev,
            compute_type=_compute_type_for(dev),
        )
    return _models[dev]


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

def transcribe(audio_path: Path, device: Optional[str] = None) -> str:
    """
    Run faster-whisper on *audio_path* and return the full transcript as a
    single string (sentences joined by spaces). *device* selects cpu/cuda
    (default: ASR_DEVICE).
    """
    model = get_model(device)
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

def transcribe_upload(file_path: Path, device: Optional[str] = None) -> str:
    """
    Accept either an audio or video file path.
    Extracts audio first if the file is a video, then transcribes.
    Returns the plain-text transcript. *device* selects cpu/cuda for this
    call (default: ASR_DEVICE).
    """
    suffix = file_path.suffix.lower()

    if suffix in _VIDEO_EXTENSIONS:
        # Extract audio into the same temp directory as the upload
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = extract_audio(file_path, Path(tmp_dir))
            return transcribe(audio_path, device=device)
    else:
        # Already an audio file — transcribe directly
        return transcribe(file_path, device=device)
