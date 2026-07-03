# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Paragraph Resolver
==================
Replaces anchor_resolver. Parses a markdown document into indexed paragraphs
(bounded by blank lines and ## Page N headers) and implements the `find_passage`
tool that the DataExtractionAgent calls via Mistral function calling.

The AI provides a natural-language query; this module finds the best-matching
paragraph and returns the verbatim text + code-derived PDF page number.
All source quotes and page numbers are therefore entirely code-derived.
"""

import json
import math
import re
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Mistral embed API — paragraph-level semantic embeddings
# ---------------------------------------------------------------------------

# Cache paragraph embeddings across ParagraphResolver instances.
# Key: tuple of paragraph texts (immutable). Value: numpy float32 array.
# Prevents re-embedding the same document when a second resolver is created
# from the same markdown (e.g., extraction resolver + verification resolver).
_PARAGRAPH_EMBED_CACHE: dict = {}

_MISTRAL_EMBED_MODEL = "mistral-embed"

# Mistral embed endpoint limit: ~16,384 tokens per request.  Real papers easily
# exceed this in a single batch (292 paragraphs ≈ 19,800 tokens on 41b5baa3),
# which produces a 400 Bad Request and silently drops semantic scoring.
# Chunking keeps every batch under _EMBED_TOKEN_BUDGET (conservative estimate).
_EMBED_TOKEN_BUDGET = 15000   # stay under Mistral's ~16k per-request cap
_EMBED_MAX_BATCH    = 128     # element-count safety valve per batch

# Read the API key at import time (on the main thread) so _embed_texts() never
# calls get_api_key() from a background thread.  Calling st.secrets from a
# background thread in Streamlit 1.46 corrupts the layout delta and causes
# frontend JS errors ("Bad 'setIn' index N").
try:
    from core.utils.config_loader import get_api_key as _get_api_key
    _MISTRAL_API_KEY: Optional[str] = _get_api_key("MISTRAL_API_KEY")
except Exception:
    _MISTRAL_API_KEY = None


def _embed_texts(texts: list) -> "Optional[object]":
    """Embed a list of texts via the Mistral embed API.

    Returns a numpy float32 array of shape (N, 1024), or None on any failure.
    Failure is silent — the resolver falls back to BM25-only automatically.

    Texts are sent in token-bounded batches (≤ _EMBED_TOKEN_BUDGET tokens,
    ≤ _EMBED_MAX_BATCH items) to stay under Mistral's per-request cap.
    Embeddings are reassembled in original input order across batches.
    """
    if not texts or _MISTRAL_API_KEY is None:
        return None
    try:
        import numpy as np
        import requests

        headers = {
            "Authorization": f"Bearer {_MISTRAL_API_KEY}",
            "Content-Type": "application/json",
        }

        # Build token-bounded batches.  Token estimate: len(text) // 4 (ASCII floor).
        # Indices track the original position so we can reassemble in order.
        batches: list[list[tuple[int, str]]] = []  # list of [(orig_idx, text), ...]
        current_batch: list[tuple[int, str]] = []
        running_tokens = 0
        for i, t in enumerate(texts):
            tok = max(1, len(t) // 4)
            if current_batch and (running_tokens + tok > _EMBED_TOKEN_BUDGET or len(current_batch) >= _EMBED_MAX_BATCH):
                batches.append(current_batch)
                current_batch = []
                running_tokens = 0
            current_batch.append((i, t))
            running_tokens += tok
        if current_batch:
            batches.append(current_batch)

        # POST each batch; sort by per-batch index (0-based at Mistral), extend result.
        all_embeddings: list = [None] * len(texts)
        for batch in batches:
            orig_indices = [pair[0] for pair in batch]
            batch_texts  = [pair[1] for pair in batch]
            resp = requests.post(
                "https://api.mistral.ai/v1/embeddings",
                headers=headers,
                json={"model": _MISTRAL_EMBED_MODEL, "input": batch_texts},
                timeout=60,  # longer timeout for multi-batch flows
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda x: x["index"])  # sort within batch by Mistral's index
            for batch_pos, item in enumerate(data):
                all_embeddings[orig_indices[batch_pos]] = item["embedding"]

        return np.array(all_embeddings, dtype=np.float32)
    except Exception as e:
        print(f"[ParagraphResolver] Mistral embed unavailable — BM25-only: {e}")
        return None

# ---------------------------------------------------------------------------
# Noise-section detection and stripping
# ---------------------------------------------------------------------------

# Boilerplate back-section headers to strip before extraction.
# Covers 7 section families, case-insensitive, optional #/## prefix, optional
# trailing colon.  The bare `contributions?` arm is intentionally absent —
# "Contribution:" / "## Contribution" is a legitimate CS/ML content heading;
# `author\s+contributions?` already covers the boilerplate form.
_RE_NOISE_HEADER = re.compile(
    r'^#{0,4}\s*(?:'
    r'references?|bibliography|works\s+cited|literature\s+cited'
    r'|acknowledgements?|acknowledgments?'
    r'|funding(?:\s+(?:statement|information))?|financial\s+support'
    r'|author\s+contributions?|authorship'
    r'|competing\s+interests?|conflicts?\s+of\s+interest|declarations?\s+of\s+interest|disclosure'
    r'|ethics\s+(?:statement|approval)|ethical\s+approval'
    r'|supplementary\s+(?:material|information)|supporting\s+information'
    r'):?\s*$',
    re.IGNORECASE,
)


def _is_noise_header(text: str) -> bool:
    """Return True if this segment is a boilerplate back-section header."""
    return bool(_RE_NOISE_HEADER.match(text))


def _normalize(text: str) -> str:
    """Normalize unicode punctuation and whitespace variants from PDF extraction."""
    # Unicode dash variants → ASCII hyphen
    text = re.sub(r'[\u2013\u2014\u2012\u2212\u2010\u2011]', '-', text)
    # Non-breaking and other unicode spaces → regular space
    text = re.sub(
        r'[\u00a0\u202f\u2009\u2008\u2007\u2006\u2005\u2004\u2003\u2002\u2001\u2000]',
        ' ', text
    )
    # Collapse runs of whitespace
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _truncate_at_inline_noise(text: str) -> str:
    """Truncate a text block at the first inline noise header.

    PDF extractors often emit "Acknowledgments" / "References" as ordinary
    lines inside a larger text block (single-newline separated, no blank-line
    break).  ``strip_noise_sections`` splits on ``\\n{2,}`` and therefore
    never sees these headers when they lack surrounding blank lines.

    This helper scans line-by-line.  When a line matches a noise header it
    returns only the text *before* that line.  If no inline header is found
    the original text is returned unchanged.
    """
    lines = text.split('\n')
    for i, line in enumerate(lines):
        stripped = _normalize(line.strip())
        if stripped and _is_noise_header(stripped):
            # Keep everything before this line
            before = '\n'.join(lines[:i]).rstrip()
            return before if before else ''
    return text


def strip_noise_sections(markdown_text: str) -> str:
    """
    Remove boilerplate back-sections from markdown before extraction.

    Two-pass approach:
    1. Split on double newlines — detect noise headers that are standalone
       segments (the common case when _clean_text promoted them to ### headers).
    2. Within each kept segment, scan for inline noise headers that only have
       single-newline separators (common with pymupdf/pypdf page-level blocks).
       Truncate the segment at the first such header.

    This is a deterministic pre-processing step — no LLM calls.  Both the LLM
    prompt and the ParagraphResolver index see the cleaned text.
    """
    segments = re.split(r'\n{2,}', markdown_text)
    kept: list[str] = []
    in_noise = False

    for seg in segments:
        seg_stripped = _normalize(seg.strip())
        if not seg_stripped:
            continue

        if _is_noise_header(seg_stripped):
            in_noise = True
            continue

        if in_noise:
            # A '#'-prefixed header that is NOT a noise header AND not a page-number
            # marker signals a new content section — resume keeping from here.
            # Page markers (## Page N) must not exit noise mode; they are structural
            # markers that appear before every reference page and would otherwise
            # cause the reference pages to be re-indexed.
            _PAGE_MARKER = re.compile(r'^##\s+Page\s+\d+', re.IGNORECASE)
            # Page-footer lines like "### 188 F. Gherardi" are short, start with
            # digits after the hashes, and should NOT exit noise mode.
            _FOOTER_HEADER = re.compile(r'^#+\s*\d', re.IGNORECASE)
            is_content_header = (
                seg_stripped.startswith('#')
                and not _is_noise_header(seg_stripped)
                and not _PAGE_MARKER.match(seg_stripped)
                and not _FOOTER_HEADER.match(seg_stripped)
            )
            if is_content_header:
                in_noise = False
                kept.append(seg)
            # Otherwise still inside the noise section — skip.
            continue

        # Pass 2: check for inline noise headers within this segment.
        # If "Acknowledgments" or "References" appears as a single-newline
        # separated line inside the block, truncate everything from that line on.
        # Also enter noise mode so the remaining segments (e.g. pure-reference
        # pages that follow) are dropped by the outer loop.
        truncated = _truncate_at_inline_noise(seg)
        if truncated != seg:
            # Truncation fired — we've hit a noise boundary inside this segment.
            in_noise = True
            if truncated.strip():
                kept.append(truncated)
        else:
            kept.append(seg)

    return '\n\n'.join(kept)


_STOP_WORDS = {
    "the", "a", "an", "and", "or", "of", "in", "to", "is", "was", "were",
    "are", "be", "been", "for", "with", "this", "that", "from", "by", "on",
    "at", "as", "it", "its", "we", "our", "their", "these", "those", "which",
    "have", "has", "had", "but", "not", "also", "both", "all", "more",
}

_MIN_PARAGRAPH_LENGTH = 20  # skip headers, stray lines, figure captions < 20 chars

# Figure and table caption paragraphs — excluded from the search index so they
# cannot be retrieved as extractable facts.  Pattern matches the opening line of
# a caption block: "Figure 3.", "Fig. 3:", "Table 2.", "Table S1.", etc.
_RE_FIGURE_CAPTION = re.compile(
    r'^(Figure|Fig\.|Table)\s*\w*\d+[.:]',
    re.IGNORECASE,
)

# Reference-list entry patterns — excluded from the search index so bibliography
# paragraphs cannot be retrieved as facts.  Two common PDF layouts:
#   Year-first:   "2014. Can recently-hatched crayfish cling to moving ducks…"
#   Author-first: "Águas, M.; Banha, F. … 2015."
# `strip_noise_sections` already attempts to remove the References section, but
# PDFs where the converter promotes author initials to ### markdown headers cause
# the stripper to exit noise mode prematurely.  This per-paragraph filter is the
# robust fallback — it judges shape, not section boundary.
_RE_REF_YEAR_FIRST = re.compile(r'^\s*(19|20)\d\d[a-z]?[.,]\s')
_RE_REF_AUTHOR_YEAR = re.compile(
    r'^\s*([A-ZÀ-Ý][\wÀ-ý-]+,\s+[A-Z]\.(?:[A-Z]\.)*[;,]?\s*){1,}.{0,200}\b(19|20)\d\d\b'
)
_MAX_SNIPPET_CHARS = 600     # cap on returned snippet length (≈ 3-4 sentences)

# BM25 retrieval parameters
_BM25_K1 = 1.5               # term saturation — higher = more weight to repeated terms
_BM25_B = 0.75               # length normalization — 0 = no normalization, 1 = full
_BM25_SCORE_THRESHOLD = 0.18 # normalized score floor; lowered from 0.30 — descriptive LLM queries miss verbatim overlap, verifier catches wrong anchors
_BM25_ALPHA = 0.85           # module-level default (context extraction); topic extraction overrides to 0.60 in standard_pipeline.py


def _tokenize(text: str) -> set:
    """Lowercase, split on non-alphanumeric, remove stop words."""
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    return {t for t in tokens if t not in _STOP_WORDS and len(t) > 1}


@dataclass
class IndexedParagraph:
    """One paragraph of the source PDF, indexed for passage lookup."""
    text: str        # verbatim paragraph text (normalized whitespace)
    page_index: int  # physical PDF page number from ## Page N header
    char_start: int  # character offset in original markdown (for debugging)


class ParagraphResolver:
    """
    Builds a paragraph index from markdown text and exposes a `find_passage`
    method suitable for use as a Haystack Tool function.
    """

    def __init__(self, markdown_text: str, *, bm25_alpha: float | None = None) -> None:
        """Index the markdown into paragraphs. `bm25_alpha` sets the hybrid lexical/semantic
        weight (None uses the module default _BM25_ALPHA)."""
        self._markdown = markdown_text
        # Per-instance hybrid weight. None → use module-level default (_BM25_ALPHA = 0.85).
        # Context extraction passes 0.50 so semantic scoring can carry terse metadata fields
        # (journal names, dates, locations) that have zero BM25 token overlap.
        resolved_alpha = bm25_alpha if bm25_alpha is not None else _BM25_ALPHA
        if not 0.0 <= resolved_alpha <= 1.0:
            raise ValueError(f"bm25_alpha must be in [0.0, 1.0], got {resolved_alpha}")
        self._bm25_alpha = resolved_alpha
        self._paragraphs: list[IndexedParagraph] = self._build_index()
        self._bm25_index = self._build_bm25_index()
        # Dense paragraph embeddings for semantic scoring via Mistral embed API.
        # None if the API call fails — retrieval falls back to BM25-only silently.
        self._embeddings = self._build_embeddings()
        # Tracks char_start positions of paragraphs already matched in this run.
        # Used to penalise re-use of the same paragraph across different fields.
        self._used_char_starts: set[int] = set()

    # ------------------------------------------------------------------ #
    # Index building                                                       #
    # ------------------------------------------------------------------ #

    def _build_index(self) -> list[IndexedParagraph]:
        """
        Split markdown on double newlines, track ## Page N headers for page numbers.
        Skips segments that are page headers, very short lines, or blank.

        Noise sections (References, Acknowledgments, Funding, etc.) are stripped
        upstream by strip_noise_sections() before this resolver is instantiated,
        so no section-boundary detection is needed here.
        """
        paragraphs: list[IndexedParagraph] = []
        current_page: int = 1  # default: first page is 1 if no header precedes it

        # Split on one or more blank lines
        segments = re.split(r'\n{2,}', self._markdown)

        # We need character positions — recompute offsets
        offset = 0
        for seg in segments:
            seg_stripped = _normalize(seg.strip())
            seg_len = len(seg) + 2  # approximate: segment + separator

            if not seg_stripped:
                offset += seg_len
                continue

            # Page header — update current page, don't add to index
            page_match = re.match(r'^##\s+Page\s+(\d+)\s*$', seg_stripped)
            if page_match:
                current_page = int(page_match.group(1))
                offset += seg_len
                continue

            # Skip very short segments (stray headers, figure labels, page numbers)
            if len(seg_stripped) < _MIN_PARAGRAPH_LENGTH:
                offset += seg_len
                continue

            # Skip markdown-level headers (# Title, ## Section) that aren't page markers
            if seg_stripped.startswith('#'):
                offset += seg_len
                continue

            # Skip figure/table caption blocks — they are not extractable facts and
            # cause the LLM to retrieve and reuse the same caption for multiple fields.
            if _RE_FIGURE_CAPTION.match(seg_stripped):
                offset += seg_len
                continue

            # Skip bibliography / reference-list entries.  strip_noise_sections()
            # attempts section-level removal but fails when the PDF converter promotes
            # author initials to ### markdown headers (causing the stripper to exit
            # noise mode prematurely).  Two layout patterns covered:
            #   "2014. Can recently-hatched crayfish cling to…"  (year-first)
            #   "Águas, M.; Banha, F. … 2015."                   (author-first)
            if _RE_REF_YEAR_FIRST.match(seg_stripped) or _RE_REF_AUTHOR_YEAR.match(seg_stripped):
                offset += seg_len
                continue

            # Skip markdown table blocks (pipe-delimited rows).  pymupdf's
            # find_tables() frequently misdetects figures/charts as tables,
            # producing garbage like "| (a) Austropot 200 | | |".  Even real
            # data tables are too structured for free-text extraction — the LLM
            # maps them to the wrong fields.  A segment is considered a table
            # block if the majority of its non-empty lines start with '|'.
            seg_lines = [ln for ln in seg_stripped.split('\n') if ln.strip()]
            if seg_lines and sum(1 for ln in seg_lines if ln.lstrip().startswith('|')) > len(seg_lines) / 2:
                offset += seg_len
                continue

            paragraphs.append(IndexedParagraph(
                text=seg_stripped,
                page_index=current_page,
                char_start=offset,
            ))
            offset += seg_len

        return paragraphs

    def _build_bm25_index(self) -> dict:
        """Precompute BM25 components: per-paragraph token frequencies, document
        frequencies across the corpus, and average document length.

        Called once at __init__ time after _build_index() completes.
        """
        token_freqs: list[dict[str, int]] = []
        doc_freqs: dict[str, int] = {}

        for para in self._paragraphs:
            toks = re.findall(r'[a-z0-9]+', para.text.lower())
            toks = [t for t in toks if t not in _STOP_WORDS and len(t) > 1]
            freq: dict[str, int] = {}
            for t in toks:
                freq[t] = freq.get(t, 0) + 1
            token_freqs.append(freq)
            for t in set(freq):
                doc_freqs[t] = doc_freqs.get(t, 0) + 1

        total_dl = sum(sum(f.values()) for f in token_freqs)
        avg_dl = total_dl / len(token_freqs) if token_freqs else 1.0

        return {"token_freqs": token_freqs, "doc_freqs": doc_freqs, "avg_dl": avg_dl}

    def _build_embeddings(self):
        """Embed all indexed paragraphs via the Mistral embed API.

        Returns a numpy float32 array of shape (N, 1024), or None on API failure
        (graceful degradation to BM25-only).

        Results are cached at module level keyed by paragraph content, so the
        second ParagraphResolver built from the same document (extraction vs.
        verification) skips the API call entirely.
        """
        if not self._paragraphs:
            return None
        texts = [p.text for p in self._paragraphs]
        cache_key = tuple(texts)
        if cache_key in _PARAGRAPH_EMBED_CACHE:
            return _PARAGRAPH_EMBED_CACHE[cache_key]
        embeddings = _embed_texts(texts)
        if embeddings is not None:
            _PARAGRAPH_EMBED_CACHE[cache_key] = embeddings
        return embeddings

    # ------------------------------------------------------------------ #
    # Search                                                               #
    # ------------------------------------------------------------------ #

    def _score_bm25(self, query_tokens: set, para_idx: int) -> float:
        """BM25 score for a query against a paragraph, normalized to [0, 1].

        IDF weighting gives rare domain terms (species names, measurements, Latin
        nomenclature) more weight than words that appear in many paragraphs.
        Normalizing by the theoretical maximum keeps the score in [0, 1] so the
        threshold remains interpretable across documents of different length.
        """
        if not query_tokens:
            return 0.0

        tf_map = self._bm25_index["token_freqs"][para_idx]
        doc_freqs = self._bm25_index["doc_freqs"]
        avg_dl = self._bm25_index["avg_dl"]
        N = len(self._paragraphs)
        dl = sum(tf_map.values())

        score = 0.0
        max_score = 0.0  # BM25 ceiling: IDF * (k1+1) as tf → ∞

        for token in query_tokens:
            df = doc_freqs.get(token, 0)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
            max_score += idf * (_BM25_K1 + 1)

            tf = tf_map.get(token, 0)
            if tf > 0:
                tf_factor = (tf * (_BM25_K1 + 1)) / (
                    tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avg_dl)
                )
                score += idf * tf_factor

        return score / max_score if max_score > 0 else 0.0

    @staticmethod
    def _score_sentence_overlap(query_tokens: set, text: str) -> float:
        """Token overlap fraction for sentence-level window selection.

        BM25 requires a corpus-level IDF index, which doesn't apply to individual
        sentences. Simple overlap is appropriate here — we only need to rank
        sentences within a single paragraph, not across the document.
        """
        if not query_tokens:
            return 0.0
        return len(query_tokens & _tokenize(text)) / len(query_tokens)

    def _search(self, query: str) -> Optional[IndexedParagraph]:
        """Return the best-matching paragraph using hybrid BM25 + semantic scoring,
        or None if the best score falls below the threshold.

        When paragraph embeddings are available (Mistral embed API reachable),
        each paragraph score is:
            self._bm25_alpha × bm25_score + (1 - self._bm25_alpha) × semantic_score
        Both components are normalized to [0, 1]. Falls back to BM25-only if
        the embed API is unavailable. Default alpha is 0.85; context extraction
        passes 0.50 to give semantic scoring enough weight for terse metadata fields.
        """
        query_tokens = _tokenize(query)
        if not query_tokens:
            return None

        # Embed the query and compute cosine similarity against all pre-computed
        # paragraph embeddings in one vectorized pass (one API call per query).
        semantic_scores = None
        if self._embeddings is not None:
            query_emb_arr = _embed_texts([query])
            if query_emb_arr is not None:
                import numpy as np
                query_emb = query_emb_arr[0]
                norms = (
                    np.linalg.norm(self._embeddings, axis=1) * np.linalg.norm(query_emb) + 1e-8
                )
                semantic_scores = np.clip(self._embeddings @ query_emb / norms, 0.0, 1.0)

        best: Optional[IndexedParagraph] = None
        best_score = 0.0

        for i, para in enumerate(self._paragraphs):
            bm25 = self._score_bm25(query_tokens, i)
            if semantic_scores is not None:
                score = self._bm25_alpha * bm25 + (1 - self._bm25_alpha) * float(semantic_scores[i])
            else:
                score = bm25
            # Penalise paragraphs already assigned to another field in this run.
            # Factor of 0.4 softens re-use enough that co-located facts in dense
            # review paragraphs survive; the verifier's duplicate-passage pre-filter
            # (≥80-char shared passage) is the hard safety net against genuine padding.
            if para.char_start in self._used_char_starts:
                score *= 0.4
            if score > best_score:
                best_score = score
                best = para

        if best_score < _BM25_SCORE_THRESHOLD:
            return None
        return best

    # ------------------------------------------------------------------ #
    # Sentence-level refinement                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _split_sentences(text: str) -> list:
        """
        Split a paragraph into individual sentences.
        Splits on sentence-ending punctuation followed by whitespace and an uppercase letter.
        Guards against splitting on common abbreviations (e.g. "Fig. 1", "et al.").
        """
        # Split at . ! ? followed by whitespace + uppercase — but not after a single capital
        # letter (abbreviations like "P. clarkii", "Fig.", "et al.", numbers like "1.")
        parts = re.split(r'(?<=[^A-Z\d][.!?])\s+(?=[A-Z])', text)
        # Filter out empty/whitespace-only fragments
        return [s.strip() for s in parts if s.strip()]

    def _extract_best_window(self, query_tokens: set, text: str) -> str:
        """
        Find the sentence in `text` most relevant to `query_tokens`.
        Returns that sentence plus any immediately adjacent neighbors that
        themselves share at least one token with the query (i.e. are genuinely
        related), capped near _MAX_SNIPPET_CHARS.

        The cap is enforced at sentence granularity, never mid-sentence: whole
        neighbor sentences are dropped to fit the budget, but no sentence is ever
        sliced. The best sentence is always kept even if it alone exceeds the cap
        — a complete long sentence is coherent; a fragment is not.

        Returns the whole `text` when it cannot be split into at least 2
        sentences (a single sentence/unit is returned intact rather than cut).
        """
        sentences = self._split_sentences(text)
        if len(sentences) < 2:
            return text

        # Score every sentence using token overlap (BM25 requires a corpus index,
        # which doesn't apply to individual sentences within a single paragraph)
        scores = [self._score_sentence_overlap(query_tokens, s) for s in sentences]

        best_idx = max(range(len(scores)), key=lambda i: scores[i])

        # Include a neighbor only if it shares at least one query token
        # (score > 0 means at least one token overlap after stop-word removal)
        selected = [best_idx]
        if best_idx > 0 and scores[best_idx - 1] > 0:
            selected.insert(0, best_idx - 1)
        if best_idx < len(sentences) - 1 and scores[best_idx + 1] > 0:
            selected.append(best_idx + 1)

        # Budget whole sentences: best is always in; each neighbor joins only if
        # the running total stays within the cap. No character slicing.
        kept = [best_idx]
        length = len(sentences[best_idx])
        for i in selected:
            if i == best_idx:
                continue
            extra = len(sentences[i]) + 1  # +1 for the joining space
            if length + extra <= _MAX_SNIPPET_CHARS:
                kept.append(i)
                length += extra

        kept.sort()
        return " ".join(sentences[i] for i in kept)

    # ------------------------------------------------------------------ #
    # Tool function                                                        #
    # ------------------------------------------------------------------ #

    def find_passage(self, query: str, field_name: str, reasoning: str, value: str = "") -> str:
        """
        Tool function exposed to the LLM via Mistral function calling.

        Args:
            query:      Natural-language description of the fact to find.
            field_name: Snake_case key the caller intends to assign this fact.
            reasoning:  Why this fact is relevant to the research topic.
            value:      Optional concise answer for this field (used by context extraction).

        Returns:
            JSON string: {"found": bool, "text": str, "page_index": int|null}
        """
        para = self._search(query)
        if para is None:
            print(f"[ParagraphResolver] No match for field '{field_name}' query: {query[:60]!r}")
            return json.dumps({"found": False, "text": "", "page_index": None})

        self._used_char_starts.add(para.char_start)
        query_tokens = _tokenize(query)
        snippet = self._extract_best_window(query_tokens, para.text)
        print(f"[ParagraphResolver] '{field_name}': {len(snippet)} chars from {len(para.text)}-char paragraph")
        return json.dumps({
            "found": True,
            "text": snippet,
            "page_index": para.page_index,
        })

    # ------------------------------------------------------------------ #
    # Haystack Tool factory                                                #
    # ------------------------------------------------------------------ #

    def make_haystack_tool(self):
        """Return a Haystack Tool wrapping find_passage, bound to this resolver."""
        from haystack.tools import Tool

        return Tool(
            name="find_passage",
            description=(
                "Search the document for a paragraph containing a specific fact. "
                "Call once per distinct fact you want to extract. "
                "Returns the verbatim paragraph text and its PDF page number. "
                "You MUST use this tool — do not copy or paraphrase text yourself."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural-language description of the fact — e.g. "
                            "'adult carapace length measurement in millimetres' or "
                            "'sex determination XY chromosome system'. "
                            "Do NOT paste verbatim text as the query."
                        ),
                    },
                    "field_name": {
                        "type": "string",
                        "description": (
                            "The snake_case output key for this field — e.g. "
                            "'adult_carapace_length_range' or 'sex_determination_system'."
                        ),
                    },
                    "reasoning": {
                        "type": "string",
                        "description": (
                            "Why this fact is relevant to the research topic — e.g. "
                            "'Morphology — body size measurement for this species'."
                        ),
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "Concise answer for this field (1-2 sentences) as it "
                            "should appear on a triage card. Optional — if omitted, "
                            "the retrieved passage text is used."
                        ),
                    },
                },
                "required": ["query", "field_name", "reasoning"],
            },
            function=self.find_passage,
        )
