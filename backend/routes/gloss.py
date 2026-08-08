"""
Gloss router — Stage 3.

POST /gloss/generate
  Accepts a plain-text transcript body, returns a PipelineResult
  with sentences and gloss_tokens populated.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.schemas import PipelineResult
from backend.services.gloss import text_to_gloss

router = APIRouter(prefix="/gloss", tags=["gloss"])


class GlossRequest(BaseModel):
    transcript: str


@router.post("/generate", response_model=PipelineResult)
async def generate_gloss(req: GlossRequest) -> PipelineResult:
    """
    Convert a transcript string into ISL gloss tokens.
    Returns a PipelineResult with transcript + sentences populated.
    """
    sentences = text_to_gloss(req.transcript)
    return PipelineResult(
        transcript=req.transcript,
        sentences=sentences,
    )
