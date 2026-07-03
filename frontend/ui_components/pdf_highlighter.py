# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
PDF Highlight Annotator
========================
Uses PyMuPDF (fitz) to stamp coloured highlight annotations onto PDF bytes
before the bytes are displayed via st.pdf().

Each highlight entry carries:
    {
        "topic":  str   — topic key from StandardTopicRegistry
        "quote":  str   — verbatim text span from verification_agent source_quote
        "color":  (r, g, b)  — 0-1 float tuple for fitz annotation
    }
"""

import re
from typing import Optional


def _normalize(text: str) -> str:
    """
    Apply the same normalization as ParagraphResolver so that source_quote
    text (which is normalized) can be matched against the page's word tokens
    (which come from the raw PDF text layer and may contain unicode variants).
    """
    # Unicode dash variants → ASCII hyphen
    text = re.sub(r'[–—‒−‐‑]', '-', text)
    # Non-breaking and other unicode spaces → regular space
    text = re.sub(
        r'[            ]',
        ' ', text
    )
    # Collapse runs of whitespace
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _normalize_for_match(text: str) -> str:
    """
    Reduce text to a flat, case-folded, whitespace-free, hyphen-free character
    stream suitable for substring matching.

    This resolves the three failure modes in exact-string matching:
      1. Whitespace / newlines — source_quote contains internal \\n (paragraph
         resolver _normalize only collapses repeated spaces, not \\n), while the
         page-word stream is space-joined.  Stripping all whitespace on both sides
         eliminates the gap.
      2. Hyphenation — fitz TEXT_DEHYPHENATE joins a broken word in get_text("words")
         but the converter that produced source_quote (pdf_to_markdown.py) does not
         use TEXT_DEHYPHENATE, so "extinc-\\ntion" is left in the quote.  Stripping
         hyphens on both sides makes "extinc-tion" == "extinction".
      3. Case drift — minor case differences in PDF headers or OCR artefacts.
    """
    # First apply the standard unicode normalization
    text = _normalize(text)
    # Lowercase
    text = text.lower()
    # Strip all whitespace and hyphens (content chars only)
    text = re.sub(r'[\s\-]+', '', text)
    return text


def _find_quote_rects(page, quote: str) -> list:
    """
    Search for a quote string on a fitz page and return the matching rect list.

    Uses char-stream matching: both the page word-stream and the quote are reduced
    to lowercased, whitespace-free, hyphen-free character sequences.  A per-character
    → fitz.Rect map is built so that after str.find() succeeds the matched character
    span can be mapped back to word bounding boxes for annotation.

    Args:
        page: fitz.Page object
        quote: verbatim text from verification_agent source_quote field

    Returns:
        List of fitz.Rect objects covering the matched text, or [] if not found.
    """
    if not quote or not quote.strip():
        return []

    try:
        import fitz
    except ImportError:
        return []

    # Get words with bounding boxes.
    # Do NOT pass TEXT_DEHYPHENATE here — we strip hyphens ourselves in
    # _normalize_for_match, keeping the raw word tokens consistent with how
    # pdf_to_markdown.py extracted the text that produced source_quote.
    try:
        words = page.get_text("words")
    except Exception:
        return []

    if not words:
        return []

    # Build the char-stream and a parallel per-char rect list.
    # Each content character in _normalize_for_match(word) maps to the word's rect.
    stream = []        # list of single chars (the flat content stream)
    char_rects = []    # parallel list: char_rects[i] = fitz.Rect for stream[i]

    for w in words:
        x0, y0, x1, y1, word_text = w[0], w[1], w[2], w[3], w[4]
        norm = _normalize_for_match(word_text)
        if not norm:
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        for ch in norm:
            stream.append(ch)
            char_rects.append(rect)

    page_stream = ''.join(stream)
    norm_quote = _normalize_for_match(quote)

    if not norm_quote:
        return []

    # Try the full quote first; fall back to the first 120 content chars only if
    # necessary.  The 120-char fallback avoids total misses on very long quotes
    # where the tail diverges (e.g. sentence-splicing artefacts from the resolver's
    # _extract_best_window), at the cost of highlighting less text.
    _FALLBACK_CHARS = 120
    candidates = [norm_quote]
    if len(norm_quote) > _FALLBACK_CHARS:
        candidates.append(norm_quote[:_FALLBACK_CHARS])

    for candidate in candidates:
        if not candidate:
            continue
        start = page_stream.find(candidate)
        if start == -1:
            continue
        end = start + len(candidate)

        # Map the matched char span back to word rects.
        # Multiple stream chars share the same fitz.Rect (one per word), so
        # dedup while preserving left-to-right, top-to-bottom order.
        seen_ids = set()
        rects = []
        for rect in char_rects[start:end]:
            rid = id(rect)
            if rid not in seen_ids:
                seen_ids.add(rid)
                rects.append(rect)

        if rects:
            return rects

    return []


def slice_pdf_to_page(pdf_bytes: bytes, page_number: int) -> Optional[bytes]:
    """
    Return a new PDF containing only the single page identified by *page_number*.

    page_number is 1-based (matches the pdf_page_index field on extracted facts, which
    is derived from the ## Page N headers in pdf_to_markdown.py).  The page is clamped
    to the document range so out-of-range values don't raise.

    Preserves existing annotations (e.g. highlights baked by
    annotate_pdf_with_highlights) because fitz.Document.select() keeps page-level
    annotations on the selected pages.

    Args:
        pdf_bytes:    PDF bytes, typically the already-annotated output of
                      annotate_pdf_with_highlights.
        page_number:  1-based page number to keep.

    Returns:
        Bytes of a single-page PDF, or None if fitz is unavailable / input is invalid.
    """
    try:
        import fitz
    except ImportError:
        return None

    if not pdf_bytes:
        return None

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        idx = max(0, min(page_number - 1, len(doc) - 1))
        doc.select([idx])
        return doc.tobytes(garbage=4, deflate=True)
    except Exception as e:
        print(f"WARNING: PDF slice failed (page {page_number}): {e}")
        return None


def annotate_pdf_with_highlights(
    pdf_bytes: bytes,
    highlights: list,
) -> Optional[bytes]:
    """
    Stamp coloured highlight annotations onto a PDF and return the modified bytes.

    Args:
        pdf_bytes:  Original PDF bytes (from source['uploaded_pdf'])
        highlights: List of dicts, each with keys:
                      "topic"  — topic key string
                      "quote"  — source quote string to locate in the PDF
                      "color"  — (r, g, b) tuple in 0-1 range

    Returns:
        Annotated PDF bytes, or None if fitz is unavailable / pdf_bytes is invalid.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return None

    if not highlights or not pdf_bytes:
        return None

    # Cap at 25 highlights to keep the synchronous search loop off the critical path.
    _MAX_HIGHLIGHTS = 25
    highlights = highlights[:_MAX_HIGHLIGHTS]

    print(f"[PDF Highlighter] Annotating PDF with {len(highlights)} highlights")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_hits = 0

        for page in doc:
            for hl in highlights:
                quote = hl.get("quote", "")
                color = hl.get("color", (1.0, 1.0, 0.0))

                rects = _find_quote_rects(page, quote)
                if rects:
                    total_hits += 1
                for rect in rects:
                    annot = page.add_highlight_annot(rect)
                    annot.set_colors(stroke=color)
                    annot.update()

        print(f"[PDF Highlighter] Placed highlights for {total_hits}/{len(highlights)} quotes")
        if total_hits == 0:
            # Log first quote and first page sample (normalized) for diagnosis
            first_hl = highlights[0] if highlights else {}
            first_quote_norm = _normalize_for_match(first_hl.get("quote", "").strip())[:80]
            first_page = doc[0] if len(doc) > 0 else None
            if first_page and first_quote_norm:
                sample_words = first_page.get_text("words")[:5]
                sample_stream = _normalize_for_match(
                    " ".join(w[4] for w in sample_words)
                )[:80]
                print(f"[PDF Highlighter] First quote stream (80 chars): {first_quote_norm!r}")
                print(f"[PDF Highlighter] First page stream sample:      {sample_stream!r}")

        return doc.tobytes(garbage=4, deflate=True)

    except Exception as e:
        print(f"WARNING: PDF annotation failed: {e}")
        import traceback
        traceback.print_exc()
        return None
