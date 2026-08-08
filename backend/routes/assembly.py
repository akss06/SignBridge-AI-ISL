"""
Assembly router — Stage 5.

POST /assembly/assemble
  Accepts a PipelineResult (with clip_path populated from Stage 4),
  runs ffmpeg assembly, returns the result with output_video_url set.
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.schemas import PipelineResult
from backend.services.assembly import assemble_from_pipeline

router = APIRouter(prefix="/assembly", tags=["assembly"])


@router.post("/assemble", response_model=PipelineResult)
async def assemble(result: PipelineResult) -> PipelineResult:
    """
    Assemble matched CISLR clips into a single ISL video.
    Returns PipelineResult with output_video_url populated (or error set).
    """
    return assemble_from_pipeline(result)
