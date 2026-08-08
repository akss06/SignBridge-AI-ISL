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
from typing import List, Optional, Tuple

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

# Articles and possessive determiners (no standalone ISL sign)
_ARTICLES = {"a", "an", "the", "my", "your", "his", "her", "its", "our", "their"}

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

# Negation words — "no" excluded here; handled by dep_=="neg" to avoid
# eating "no" when used as a standalone content word / determiner
_NEG_WORDS = {"not", "n't", "never", "nobody", "nothing",
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
    # "no" is only treated as negation when spaCy marks it dep_=="neg"
    # (e.g. "no money" → det, not neg — kept as content word)
    if tok.dep_ == "neg":
        return True
    return tok.text.lower() in _NEG_WORDS


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
            if tok not in sub_clause_roots:
                sub_clause_roots.append(tok)

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

def _reorder_adjectives(toks: List[Token], clause_set: set) -> List[Token]:
    """
    Within a list of tokens, move adjectival modifiers (amod dependents)
    to immediately AFTER their head noun.

    ISL places adjectives after the noun they modify — e.g. English
    "red ball" becomes ISL gloss BALL RED.
    (Adjective-after-noun order is documented across multiple ISL computational
    linguistics and gloss-generation system papers; also consistent with the
    SOV-language typology described in Zeshan 2000.)

    Only reorders within the supplied token list; ignores amod links that
    cross clause boundaries.
    """
    if len(toks) <= 1:
        return toks

    tok_set = {t.i for t in toks}
    result: List[Token] = []
    placed: set[int] = set()

    for tok in toks:
        if tok.i in placed:
            continue
        result.append(tok)
        placed.add(tok.i)
        # Append any amod children of this token that are also in this list
        for child in tok.children:
            if child.dep_ == "amod" and child.i in tok_set and child.i not in placed:
                result.append(child)
                placed.add(child.i)

    return result


def _clause_to_gloss(clause_tokens: List[Token]) -> List[Tuple[str, str]]:
    """
    Reorder one clause's tokens into ISL gloss order:
        Time → Subject → Object → Verb
    then:
      - drop function words
      - move adjectives after their head nouns (ISL adjective-after-noun order)
      - append NEG marker at the end

    Returns a list of (lemma_upper, surface_upper) pairs.
    """
    time_toks:    List[Token] = []
    subject_toks: List[Token] = []
    object_toks:  List[Token] = []
    verb_toks:    List[Token] = []
    neg_found:    bool = False
    other_toks:   List[Token] = []

    clause_set = {t.i for t in clause_tokens}

    for tok in clause_tokens:
        if _is_function_word(tok):
            continue
        if _is_negation(tok):
            neg_found = True
            continue

        dep = tok.dep_
        pos = tok.pos_

        # amod tokens are bucketed with their head noun's group so that
        # _reorder_adjectives can place them immediately after the noun.
        # We still need them in the bucket — do NOT skip them here.
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

    # Apply adjective-after-noun reordering within each nominal group
    subject_toks = _reorder_adjectives(subject_toks, clause_set)
    object_toks  = _reorder_adjectives(object_toks,  clause_set)
    other_toks   = _reorder_adjectives(other_toks,   clause_set)

    # Assemble in ISL order: Time Subject Object Verb [NEG]
    ordered: List[Token] = (
        time_toks + subject_toks + object_toks + verb_toks + other_toks
    )

    # Return (lemma, surface) pairs so the caller can store both forms.
    # Surface form is used by clip lookup as a fallback when the lemma
    # doesn't match the vocab (e.g. "games" lemmatises to "game" but
    # the vocab has "GAMES").
    pairs: List[Tuple[str, str]] = [
        (tok.lemma_.upper(), tok.text.upper()) for tok in ordered
    ]

    if neg_found:
        pairs.append(("NOT", "NOT"))

    return pairs


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

        all_pairs: List[Tuple[str, str]] = []
        for clause in clauses:
            all_pairs.extend(_clause_to_gloss(clause))

        # Deduplicate consecutive identical lemmas (artefact of clause overlap)
        deduped: List[Tuple[str, str]] = []
        for pair in all_pairs:
            if not deduped or pair[0] != deduped[-1][0]:
                deduped.append(pair)

        gloss_tokens = [
            GlossToken(
                token=lemma,
                surface=surface if surface != lemma else None,
                clip_path=None,
                matched=False,
            )
            for lemma, surface in deduped
            if lemma.strip()
        ]

        results.append(SentenceResult(
            original=sent_text,
            gloss_tokens=gloss_tokens,
        ))

    return results
