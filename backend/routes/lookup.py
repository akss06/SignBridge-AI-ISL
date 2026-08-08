"""
Clip lookup router — Stage 4.

POST /lookup/clips
  Accepts a PipelineResult body (with sentences/gloss_tokens populated),
  returns the same shape with clip_path + matched fields filled in
  and coverage computed.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.schemas import PipelineResult
from backend.services.clip_lookup import enrich_pipeline_result

router = APIRouter(prefix="/lookup", tags=["lookup"])


@router.post("/clips", response_model=PipelineResult)
async def lookup_clips(result: PipelineResult) -> PipelineResult:
    """
    Given a PipelineResult with gloss_tokens populated, match each token
    against the CISLR vocab using greedy longest-match and return
    clip paths + coverage.
    """
    try:
        return enrich_pipeline_result(result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
