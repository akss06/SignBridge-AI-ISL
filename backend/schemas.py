"""
SignBridge AI — ISL Video Generation Pipeline
Pydantic schemas shared across all pipeline stages.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Per-token result
# ---------------------------------------------------------------------------

class GlossToken(BaseModel):
    """A single gloss token produced by the grammar/gloss engine."""
    token: str = Field(..., description="The sign label / gloss word (lemma, uppercase)")
    surface: Optional[str] = Field(
        None,
        description="Original surface form of the word before lemmatization "
                    "(uppercase). Used by clip lookup as a fallback when the "
                    "lemma form is not in the vocab.",
    )
    clip_path: Optional[str] = Field(
        None,
        description="Absolute or relative path to the matched CISLR clip, "
                    "or null if the token was dropped (no match found).",
    )
    matched: bool = Field(
        False,
        description="True if a clip was found for this token.",
    )


# ---------------------------------------------------------------------------
# Per-sentence result
# ---------------------------------------------------------------------------

class SentenceResult(BaseModel):
    """Processing result for a single sentence."""
    original: str = Field(..., description="Original sentence text.")
    gloss_tokens: List[GlossToken] = Field(
        default_factory=list,
        description="Ordered list of gloss tokens in ISL word order.",
    )


# ---------------------------------------------------------------------------
# Top-level pipeline result — the canonical shape for every stage
# ---------------------------------------------------------------------------

class PipelineResult(BaseModel):
    """
    Canonical output of the full SignBridge pipeline.
    Every stage reads/writes this shape — no loose dicts.
    """
    transcript: str = Field(
        ...,
        description="Full original transcript from ASR.",
    )
    sentences: List[SentenceResult] = Field(
        default_factory=list,
        description="Per-sentence breakdown with gloss tokens.",
    )
    coverage: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of gloss tokens for which a clip was found. "
            "Denominator = total tokens attempted (including dropped ones). "
            "Range [0.0, 1.0]."
        ),
    )
    output_video_url: Optional[str] = Field(
        None,
        description=(
            "URL path (e.g. /outputs/result_<uuid>.mp4) to the assembled "
            "ISL video, served as a static file by FastAPI. "
            "Null until the assembly stage completes."
        ),
    )
    error: Optional[str] = Field(
        None,
        description="Human-readable error message if any stage failed.",
    )
