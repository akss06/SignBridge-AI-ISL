"""
Clip lookup service — Stage 4.

Loads the CISLR vocab JSON once at startup and exposes a single function:
    lookup_clips(sentences) -> (sentences_with_clips, coverage_float)

Matching strategy: GREEDY LONGEST-MATCH
  - For each position in the gloss token list, try the longest possible
    n-gram first (up to MAX_PHRASE_WORDS tokens), falling back to shorter
    spans until a single token is tried.
  - If no match at any span length: the token is DROPPED (clip_path=None,
    matched=False).  No fingerspelling, no substitution.

Coverage = matched_tokens / total_tokens_attempted  (dropped tokens are
           included in the denominator — never inflated by excluding failures).

Configuration (env vars):
  ISL_VOCAB_PATH   — absolute path to isl_vocab_full.json
  ISL_CLIPS_DIR    — absolute path to the normalised clips directory
                     (used only as a fallback if normalized_path in the JSON
                      is missing or the file doesn't exist there)
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.schemas import GlossToken, PipelineResult, SentenceResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ISL_VOCAB_PATH: str = os.getenv(
    "ISL_VOCAB_PATH",
    r"C:\Users\aksha\Desktop\asl project\data\isl_explore\isl_vocab_full.json",
)

ISL_CLIPS_DIR: str = os.getenv(
    "ISL_CLIPS_DIR",
    r"C:\Users\aksha\Desktop\asl project\data\isl_explore\cislr_normalized",
)

# Maximum n-gram window for greedy longest-match.
# Dataset has phrases up to 7 real words; set to 11 to be safe.
MAX_PHRASE_WORDS: int = 11


# ---------------------------------------------------------------------------
# Vocab index (singleton)
# ---------------------------------------------------------------------------

# Maps UPPERCASE phrase → absolute clip path string
_vocab: Optional[Dict[str, str]] = None


def _load_vocab() -> Dict[str, str]:
    """
    Load and index the ISL vocab JSON.
    Returns a dict mapping UPPERCASE phrase → absolute clip path.
    Keys in the JSON are already uppercase — no normalisation needed.
    """
    vocab_path = Path(ISL_VOCAB_PATH)
    if not vocab_path.exists():
        logger.error("ISL vocab JSON not found at configured path: %s", vocab_path)
        raise FileNotFoundError(
            "ISL vocab JSON not found. Check the ISL_VOCAB_PATH server "
            "configuration."
        )

    with vocab_path.open(encoding="utf-8") as fh:
        raw: dict = json.load(fh)

    index: Dict[str, str] = {}
    clips_dir = Path(ISL_CLIPS_DIR)

    for phrase, entry in raw.items():
        # Primary: use normalized_path from the JSON
        clip_path = entry.get("normalized_path", "")

        if clip_path and Path(clip_path).exists():
            index[phrase.upper()] = clip_path
            continue

        # Fallback: reconstruct path from uid + clips directory
        uid = entry.get("uid", "")
        if uid:
            fallback = clips_dir / f"{uid}.mp4"
            if fallback.exists():
                index[phrase.upper()] = str(fallback)
                continue

        # Entry exists in vocab but clip file is missing — skip silently.
        # This is not a crash condition; coverage will simply reflect it.

    return index


def get_vocab() -> Dict[str, str]:
    """Return the shared vocab index, loading on first call."""
    global _vocab
    if _vocab is None:
        _vocab = _load_vocab()
    return _vocab


# ---------------------------------------------------------------------------
# Greedy longest-match lookup
# ---------------------------------------------------------------------------

def _lookup_phrase(
    lemmas: List[str],
    surfaces: List[str],
    start: int,
    vocab: Dict[str, str],
) -> Tuple[int, Optional[str]]:
    """
    Starting at *start*, try the longest possible phrase match first,
    shrinking the window down to a single token.

    For each span length, tries the lemma form first, then the surface form
    as a fallback (handles cases like "games" → lemma "GAME" not in vocab
    but surface "GAMES" is).

    Returns (span_length, clip_path) where:
      - span_length >= 1 always
      - clip_path is None if no match was found (token is dropped)
    """
    max_end = min(start + MAX_PHRASE_WORDS, len(lemmas))

    for end in range(max_end, start, -1):
        # Try lemma phrase first
        lemma_phrase = " ".join(lemmas[start:end])
        if lemma_phrase in vocab:
            return (end - start), vocab[lemma_phrase]

        # Fallback: surface phrase (only meaningful when span=1 or surfaces differ)
        surface_phrase = " ".join(surfaces[start:end])
        if surface_phrase != lemma_phrase and surface_phrase in vocab:
            return (end - start), vocab[surface_phrase]

    # No match at any span length
    return 1, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup_clips(sentences: List[SentenceResult]) -> Tuple[List[SentenceResult], float]:
    """
    For each gloss token in *sentences*, attempt a greedy longest-match
    lookup against the CISLR vocab.

    Mutates a copy of each SentenceResult's gloss_tokens in-place with
    clip_path and matched fields populated.

    Returns:
      (updated_sentences, coverage)

    Coverage = matched_token_positions / total_token_positions_attempted
    Multi-word matches count as 1 match for N positions consumed.
    Dropped tokens count as 0 matches for their 1 position.
    """
    vocab = get_vocab()
    updated_sentences: List[SentenceResult] = []
    total_attempted = 0
    total_matched = 0

    for sent in sentences:
        lemma_tokens   = [gt.token for gt in sent.gloss_tokens]
        surface_tokens = [gt.surface or gt.token for gt in sent.gloss_tokens]
        new_gloss: List[GlossToken] = []
        i = 0

        while i < len(lemma_tokens):
            span, clip_path = _lookup_phrase(lemma_tokens, surface_tokens, i, vocab)

            if clip_path is not None:
                # Matched span — emit one GlossToken representing the match.
                # For multi-word matches, the token label joins the span.
                matched_label = " ".join(lemma_tokens[i : i + span])
                new_gloss.append(GlossToken(
                    token=matched_label,
                    clip_path=clip_path,
                    matched=True,
                ))
                total_matched += span      # each consumed position = 1 match
                total_attempted += span
            else:
                # No match — drop the single token, record the attempt
                new_gloss.append(GlossToken(
                    token=lemma_tokens[i],
                    clip_path=None,
                    matched=False,
                ))
                total_attempted += 1       # dropped token still counts

            i += span

        updated_sentences.append(SentenceResult(
            original=sent.original,
            gloss_tokens=new_gloss,
        ))

    coverage = total_matched / total_attempted if total_attempted > 0 else 0.0
    return updated_sentences, coverage


def enrich_pipeline_result(result: PipelineResult) -> PipelineResult:
    """
    Take a PipelineResult with sentences populated (from the gloss stage)
    and fill in clip_path / matched on every GlossToken, plus set coverage.

    Returns a new PipelineResult (does not mutate the input).
    """
    updated_sentences, coverage = lookup_clips(result.sentences)
    return PipelineResult(
        transcript=result.transcript,
        sentences=updated_sentences,
        coverage=round(coverage, 4),
        output_video_url=result.output_video_url,
        error=result.error,
    )
