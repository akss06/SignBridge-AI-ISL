"""
Quiz service — learning/quiz mode.

Independent of the main pipeline: reads its own dummy/hardcoded question
JSON, and resolves clip phrases against the same ISL vocab JSON the main
pipeline uses (read-only, same env vars) so quiz clips are just the CISLR
clips already in the project. Does not import or modify clip_lookup.py.

Configuration:
  QUIZ_DATA_PATH — path to the quiz topics/questions JSON
                    (default: backend/data/quiz_data.json)
  ISL_VOCAB_PATH — same vocab JSON the main pipeline uses, for clip lookup
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root

QUIZ_DATA_PATH: str = os.getenv(
    "QUIZ_DATA_PATH", str(_BASE_DIR / "backend" / "data" / "quiz_data.json")
)

ISL_VOCAB_PATH: str = os.getenv(
    "ISL_VOCAB_PATH",
    r"C:\Users\aksha\Desktop\asl project\data\isl_explore\isl_vocab_trimmed.json",
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
    Resolve an ISL vocab phrase to its clip file path, preferring
    trimmed_path over normalized_path (mirrors clip_lookup.py's own
    preference) — returns None if the phrase or file isn't found.
    """
    vocab_path = Path(ISL_VOCAB_PATH)
    if not vocab_path.exists():
        logger.error("ISL vocab JSON not found at configured path: %s", vocab_path)
        return None

    with vocab_path.open(encoding="utf-8") as fh:
        raw: Dict[str, dict] = json.load(fh)

    entry = raw.get(phrase.upper())
    if entry is None:
        return None

    trimmed_path = entry.get("trimmed_path", "")
    if trimmed_path and Path(trimmed_path).exists():
        return trimmed_path

    normalized_path = entry.get("normalized_path", "")
    if normalized_path and Path(normalized_path).exists():
        return normalized_path

    return None
