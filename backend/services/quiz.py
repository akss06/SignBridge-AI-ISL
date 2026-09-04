"""
Quiz service — learning/quiz mode.

Content-independent of the main pipeline: reads its own hardcoded question
JSON. Clip phrases are resolved through the main pipeline's cached vocab
index (clip_lookup.get_vocab — read-only, loaded and parsed once), so quiz
clips are the same CISLR clips with the same trimmed→normalized resolution,
without re-reading the vocab JSON on every request.

Configuration:
  QUIZ_DATA_PATH — path to the quiz topics/questions JSON
                    (default: backend/data/quiz_data.json)

  Clip lookup uses ISL_VOCAB_PATH via clip_lookup — this module no longer
  reads the vocab JSON itself.
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import List, Optional

from backend.services.clip_lookup import get_vocab

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root

QUIZ_DATA_PATH: str = os.getenv(
    "QUIZ_DATA_PATH", str(_BASE_DIR / "backend" / "data" / "quiz_data.json")
)


def _load_quiz_data() -> dict:
    path = Path(QUIZ_DATA_PATH)
    if not path.exists():
        raise FileNotFoundError("Quiz data file not found. Check QUIZ_DATA_PATH.")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _find_topic(data: dict, topic_id: str) -> Optional[dict]:
    for topic in data.get("topics", []):
        if topic.get("id") == topic_id:
            return topic
    return None


def list_topics() -> List[dict]:
    """Return [{id, name, question_count}] for every topic."""
    data = _load_quiz_data()
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "question_count": len(t.get("questions", [])),
        }
        for t in data.get("topics", [])
    ]


def get_topic_questions(topic_id: str) -> Optional[List[dict]]:
    """
    Return the question list for *topic_id* with options (correct answer +
    distractors) shuffled per question. Returns None if the topic doesn't
    exist.
    """
    data = _load_quiz_data()
    topic = _find_topic(data, topic_id)
    if topic is None:
        return None

    questions = []
    for q in topic.get("questions", []):
        options = [q["correct_answer"]] + list(q.get("distractors", []))
        random.shuffle(options)
        questions.append(
            {
                "id": q["id"],
                "clip_phrase": q["clip_phrase"],
                "options": options,
                "correct_answer": q["correct_answer"],
            }
        )
    return questions


def resolve_clip_path(phrase: str) -> Optional[str]:
    """
    Resolve an ISL vocab phrase to its clip file path via the main pipeline's
    cached vocab index (clip_lookup.get_vocab) — same trimmed→normalized→uid
    resolution, parsed once and reused rather than re-read per request.
    Returns None if the phrase isn't in the vocab or the vocab file is missing.
    """
    try:
        vocab = get_vocab()
    except FileNotFoundError:
        logger.error("ISL vocab JSON not found — cannot resolve quiz clips.")
        return None
    return vocab.get(phrase.upper())
