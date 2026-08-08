"""
ASR router — Stage 2.

POST /asr/transcribe
  Accepts a multipart file upload (.wav, .mp3, .mp4).
  Returns the plain-text transcript plus the PipelineResult skeleton
  (transcript field populated, rest empty/defaults).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.schemas import PipelineResult
from backend.services.asr import transcribe_upload

router = APIRouter(prefix="/asr", tags=["asr"])

_ALLOWED_EXTENSIONS = {".wav", ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".webm"}


@router.post("/transcribe", response_model=PipelineResult)
async def transcribe_file(file: UploadFile = File(...)) -> PipelineResult:
    """
    Upload an audio (.wav, .mp3) or video (.mp4) file.
    Returns a PipelineResult with the transcript field populated.
    """
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )

    # Write upload to a named temp file so faster-whisper can read it by path
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        tmp.write(content)

    try:
        transcript = transcribe_upload(tmp_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return PipelineResult(transcript=transcript)
