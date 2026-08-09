"""
Full pipeline router — Stage 6.

POST /pipeline/run
  Accepts a multipart file upload (.wav, .mp3, .mp4).
  Runs all stages in sequence:
    1. ASR        — transcribe audio/video to text
    2. Gloss      — text → ISL gloss tokens (rule-based)
    3. Clip lookup — gloss tokens → CISLR clip paths (greedy longest-match)
    4. Assembly   — matched clips → output ISL video

  Returns a fully populated PipelineResult.
  On 0% coverage the result has output_video_url=null and error set — no crash.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.schemas import PipelineResult
from backend.services.asr import transcribe_upload
from backend.services.gloss import text_to_gloss
from backend.services.clip_lookup import lookup_clips
from backend.services.assembly import assemble_from_pipeline

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

_ALLOWED_EXTENSIONS = {".wav", ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".webm"}


@router.post("/run", response_model=PipelineResult)
async def run_pipeline(file: UploadFile = File(...)) -> PipelineResult:
    """
    Upload an audio (.wav, .mp3) or video (.mp4) file and run the full
    ISL generation pipeline. Returns a PipelineResult with all fields
    populated.
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

    # --- Stage 2: ASR ---
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(await file.read())

    try:
        transcript = transcribe_upload(tmp_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"ASR failed: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    if not transcript.strip():
        return PipelineResult(
            transcript="",
            sentences=[],
            coverage=0.0,
            output_video_url=None,
            error="No speech detected in the uploaded file.",
        )

    # --- Stage 3: Gloss ---
    try:
        sentences = text_to_gloss(transcript)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gloss generation failed: {exc}") from exc

    # --- Stage 4: Clip lookup ---
    try:
        sentences, coverage = lookup_clips(sentences)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # --- Stage 5: Assembly (graceful on 0% coverage) ---
    partial_result = PipelineResult(
        transcript=transcript,
        sentences=sentences,
        coverage=round(coverage, 4),
    )
    return assemble_from_pipeline(partial_result)
