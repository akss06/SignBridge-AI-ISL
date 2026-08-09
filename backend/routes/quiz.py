"""
Quiz router — learning/quiz mode.

  GET /quiz/topics             → list of topics
  GET /quiz/topics/{topic_id}  → question list for a topic (options shuffled)
  GET /quiz/clips/{phrase}     → streams the sign clip for a vocab phrase

Independent of the main pipeline routes/services.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.services import quiz as quiz_service

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.get("/topics")
async def get_topics():
    return quiz_service.list_topics()


@router.get("/topics/{topic_id}")
async def get_topic(topic_id: str):
    questions = quiz_service.get_topic_questions(topic_id)
    if questions is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"topic_id": topic_id, "questions": questions}


@router.get("/clips/{phrase}")
async def get_clip(phrase: str):
    clip_path = quiz_service.resolve_clip_path(phrase)
    if clip_path is None:
        raise HTTPException(status_code=404, detail="Clip not found")
    return FileResponse(clip_path, media_type="video/mp4")
