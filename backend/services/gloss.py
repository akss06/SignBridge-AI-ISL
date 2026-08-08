"""
Gloss generation service — Stage 3.

Converts a plain-text transcript into ordered ISL gloss tokens using
spaCy dependency parsing.  Rule-based only — no LLM, no external calls.

ISL grammar rules applied (per published ISL linguistics):
  - Split text into clauses FIRST (coordinated / subordinate / complement)
    before any reordering, so non-root verbs in compound sentences are kept.
  - Reorder each clause: Time → Subject → Object → Verb
  - Drop function words that have no standalone ISL sign:
      articles, copulas, auxiliaries, most prepositions, particles
  - Negation: place NEG marker at the END of the clause
  - No wh-word repositioning (no documented ISL rule exists)
  - No fingerspelling — unknown tokens are simply kept as-is for Stage 4
    to drop if unmatched.

Output: list of SentenceResult objects (one per sentence in the input).
"""
from __future__ import annotations

import re
from typing import List, Optional

import spacy
from spacy.tokens import Doc, Span, Token

from backend.schemas import GlossToken, SentenceResult

# ---------------------------------------------------------------------------
# Model singleton
# ---------------------------------------------------------------------------

_nlp: Optional[spacy.Language] = None


def get_nlp() -> spacy.Language:
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


# ---------------------------------------------------------------------------
# Drop-lists  (words with no standalone ISL sign)
# ---------------------------------------------------------------------------

# Articles
_ARTICLES = {"a", "an", "the"}

# Copula lemmas
_COPULAS = {"be"}

# Pure auxiliary lemmas (when used as auxiliaries, not main verbs)
_AUX_LEMMAS = {
    "will", "would", "shall", "should",
    "can", "could", "may", "might",
    "do", "have",       # only when aux dep
    "need",             # modal use
}

# Prepositions/particles to drop
_PREP_DROP = {
    "of", "in", "on", "at", "to", "for", "with", "by",
    "from", "into", "onto", "upon", "about", "over",
    "under", "between", "among", "through", "during",
    "before", "after", "since", "until", "up", "out",
    "off", "down", "as", "per",
}

# Dependency labels that mark time/temporal expressions
_TIME_DEPS = {"npadvmod", "advmod", "nmod", "obl"}

# Dependency labels for clause boundary markers (coordinating conjunctions,
# subordinating conjunctions, complementisers)
_CLAUSE_DEP_LABELS = {
    "cc",       # coordinating conjunction (and, but, or)
    "mark",     # subordinating conjunction / complementiser (because, that, if)
    "advcl",    # adverbial clause modifier
    "relcl",    # relative clause modifier
    "ccomp",    # clausal complement
    "xcomp",    # open clausal complement
    "conj",     # conjunct (shares head with coordinated clause)
    "acl",      # adjectival clause
}

# dep_ labels whose tokens should be dropped from the gloss entirely
# (clause-boundary function words with no standalone ISL sign)
_CLAUSE_MARKER_DROP = {"cc", "mark"}

# Negation words
_NEG_WORDS = {"not", "n't", "never", "no", "nobody", "nothing",
              "nowhere", "neither", "nor"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_function_word(tok: Token) -> bool:
    """Return True if this token should be dropped from the gloss."""
    text_l = tok.text.lower()
    lemma_l = tok.lemma_.lower()

    # Clause-boundary markers (conjunctions, subordinators, complementisers)
    # have no ISL sign and must be dropped regardless of lemma
    if tok.dep_ in _CLAUSE_MARKER_DROP:
        return True

    if text_l in _ARTICLES:
        return True

    # Copula: dep is 'cop', or lemma is 'be' and POS is AUX/VERB
    if tok.dep_ == "cop":
        return True
    if lemma_l in _COPULAS and tok.pos_ in ("AUX", "VERB"):
        return True

    # Auxiliaries
    if tok.dep_ == "aux" and lemma_l in _AUX_LEMMAS:
        return True
    if tok.dep_ == "auxpass":
        return True

    # Prepositions / particles
    if tok.pos_ in ("ADP", "PART") and text_l in _PREP_DROP:
        return True

    # Punctuation, spaces
    if tok.is_punct or tok.is_space:
        return True

    return False


def _is_negation(tok: Token) -> bool:
    return tok.dep_ == "neg" or tok.text.lower() in _NEG_WORDS


def _is_time_expression(tok: Token) -> bool:
    """Heuristic: token is a temporal adverb/noun phrase."""
    if tok.dep_ in _TIME_DEPS:
        ent_type = tok.ent_type_
        if ent_type in ("DATE", "TIME"):
            return True
        # Common time adverbs not always NER-tagged
        if tok.pos_ == "ADV" and tok.lemma_.lower() in {
            "today", "tomorrow", "yesterday", "now", "soon",
            "already", "always", "never", "often", "usually",
            "sometimes", "recently", "daily", "weekly", "monthly",
            "annually", "early", "late", "morning", "evening", "night",
        }:
            return True
    return False


# ---------------------------------------------------------------------------
# Clause splitting
# ---------------------------------------------------------------------------

def _split_into_clauses(sent: Span) -> List[List[Token]]:
    """
    Split a spaCy sentence span into clauses.

    Strategy:
      - The root and its direct non-clausal dependents form the main clause.
      - Each token whose dep_ is in _CLAUSE_DEP_LABELS (or whose subtree
        contains such a token as head) becomes a separate clause, along
        with its full subtree.

    Returns a list of token lists, one per clause.  Preserves left-to-right
    order within each clause.  Clauses are returned in the order their
    leftmost token appears in the sentence.
    """
    used: set[int] = set()
    clauses: List[List[Token]] = []

    tokens = list(sent)

    # Find sub-clause roots: tokens whose dep_ marks a clause boundary
    # OR tokens that are the head of such a dep.
    sub_clause_roots: List[Token] = []
    for tok in tokens:
        if tok.dep_ in _CLAUSE_DEP_LABELS and tok.head in tokens:
            # The token itself might be a conjunction; the real clause root
            # may be its head or a sibling.  Use the token's subtree root.
            root = tok if tok.dep_ in ("advcl", "relcl", "ccomp",
                                       "xcomp", "acl", "conj") else tok
            if root not in sub_clause_roots:
                sub_clause_roots.append(root)

    # Collect each sub-clause as its subtree
    for sub_root in sub_clause_roots:
        subtree_idxs = {t.i for t in sub_root.subtree}
        clause_tokens = [t for t in tokens if t.i in subtree_idxs]
        if clause_tokens:
            clauses.append(clause_tokens)
            used.update(subtree_idxs)

    # Main clause = everything not claimed by a sub-clause
    main_clause = [t for t in tokens if t.i not in used]
    if main_clause:
        clauses.insert(0, main_clause)

    # Fallback: if splitting produced nothing, treat whole sentence as one clause
    if not clauses:
        clauses = [tokens]

    return clauses


# ---------------------------------------------------------------------------
# Single-clause reordering → gloss tokens
# ---------------------------------------------------------------------------

def _clause_to_gloss(clause_tokens: List[Token]) -> List[str]:
    """
    Reorder one clause's tokens into ISL gloss order:
        Time → Subject → Object → Verb
    then drop function words and move negation to the end.

    Returns a list of uppercase gloss strings.
    """
    time_toks:    List[Token] = []
    subject_toks: List[Token] = []
    object_toks:  List[Token] = []
    verb_toks:    List[Token] = []
    neg_found:    bool = False
    other_toks:   List[Token] = []

    for tok in clause_tokens:
        if _is_function_word(tok):
            continue
        if _is_negation(tok):
            neg_found = True
            continue

        dep = tok.dep_
        pos = tok.pos_

        if _is_time_expression(tok):
            time_toks.append(tok)
        elif dep in ("nsubj", "nsubjpass"):
            subject_toks.append(tok)
        elif dep in ("dobj", "obj", "iobj", "pobj", "obl", "attr"):
            object_toks.append(tok)
        elif pos in ("VERB", "AUX") and dep not in (
            "aux", "auxpass", "cop"
        ):
            verb_toks.append(tok)
        else:
            other_toks.append(tok)

    # Assemble in ISL order: Time Subject Object Verb [NEG]
    ordered: List[Token] = (
        time_toks + subject_toks + object_toks + verb_toks + other_toks
    )

    gloss = [tok.lemma_.upper() for tok in ordered]

    if neg_found:
        gloss.append("NOT")

    return gloss


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def text_to_gloss(transcript: str) -> List[SentenceResult]:
    """
    Convert a full transcript string into a list of SentenceResult objects.

    Each sentence is:
      1. Parsed with spaCy.
      2. Split into clauses.
      3. Each clause reordered into ISL Time-Subject-Object-Verb order.
      4. Function words dropped; negation moved to end.

    Returns one SentenceResult per spaCy sentence.
    """
    nlp = get_nlp()

    # Normalise whitespace
    transcript = re.sub(r"\s+", " ", transcript.strip())
    if not transcript:
        return []

    doc: Doc = nlp(transcript)
    results: List[SentenceResult] = []

    for sent in doc.sents:
        sent_text = sent.text.strip()
        if not sent_text:
            continue

        clauses = _split_into_clauses(sent)

        all_gloss: List[str] = []
        for clause in clauses:
            all_gloss.extend(_clause_to_gloss(clause))

        # Deduplicate consecutive identical tokens (artefact of clause overlap)
        deduped: List[str] = []
        for g in all_gloss:
            if not deduped or g != deduped[-1]:
                deduped.append(g)

        gloss_tokens = [
            GlossToken(token=g, clip_path=None, matched=False)
            for g in deduped
            if g.strip()
        ]

        results.append(SentenceResult(
            original=sent_text,
            gloss_tokens=gloss_tokens,
        ))

    return results
