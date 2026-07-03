#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Citation Extractor Agent

Extracts structured bibliographic metadata from the opening text of a converted PDF.
Used as a fallback when API sources (Semantic Scholar, Europe PMC) do not supply
authors/year/journal/DOI — most commonly for manually uploaded PDFs.

Only fills in fields that are already absent from existing_metadata so API-provided
data is never overwritten.
"""

import json
from typing import Any, Dict

from haystack.dataclasses import ChatMessage

from core.utils.generator_factory import create_generator


# How many characters of markdown text to send to the model.
# The title page / header region is sufficient for bibliographic data and
# keeps the prompt small and cheap.
_CONTEXT_CHARS = 2000

_SYSTEM_PROMPT = """\
You are a bibliographic metadata extractor. Given the opening text of a research \
paper (converted from PDF to markdown), extract citation metadata and return it \
as a JSON object with these fields:

- "authors": list of author names as strings (e.g. ["Smith, J. A.", "Jones, B. C."])
- "year": publication year as integer (e.g. 2021), or null
- "journal": journal or book title as a string, or null
- "doi": DOI string without the https://doi.org/ prefix, or null
- "title": paper title as a string, or null

Return ONLY a valid JSON object. Do not add explanation or markdown fencing.
If a field is not clearly present in the text, set it to null (for scalars) or [] \
(for authors).
"""


def extract_citation_from_markdown(
    markdown_text: str,
    existing_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Extract missing citation fields from the opening section of a paper's markdown.

    Fields already present in existing_metadata are not overwritten — the function
    only fills gaps. This preserves API-sourced data (which is more reliable) and
    only adds value for manually uploaded PDFs where API metadata is absent.

    Args:
        markdown_text: Full markdown text of the converted PDF. Only the first
            _CONTEXT_CHARS characters are sent to the model.
        existing_metadata: Source metadata dict (may already contain doi, authors,
            publication_year, journal_name, title).

    Returns:
        Merged dict: existing_metadata fields take priority; extracted fields
        fill in any gaps. Returns existing_metadata unchanged on any error.
    """
    # Determine which fields are already present so we skip them
    needs_authors = not existing_metadata.get('authors')
    needs_year = existing_metadata.get('publication_year') is None
    needs_journal = not existing_metadata.get('journal_name')
    needs_doi = not existing_metadata.get('doi')
    existing_title = existing_metadata.get('title') or ''
    # A filename (e.g. "foods-13-03780-v2.pdf") is not a real bibliographic title —
    # treat it as absent so the extractor can replace it with the actual paper title.
    needs_title = not existing_title or existing_title.lower().endswith('.pdf')

    # Nothing missing — skip LLM call entirely
    if not any([needs_authors, needs_year, needs_journal, needs_doi, needs_title]):
        return existing_metadata

    snippet = markdown_text[:_CONTEXT_CHARS]

    try:
        generator = create_generator("citation_extraction")
        messages = [
            ChatMessage.from_system(_SYSTEM_PROMPT),
            ChatMessage.from_user(snippet),
        ]
        response = generator.run(messages=messages)
        raw_text = response["replies"][0].text.strip()

        # Strip markdown code fences if model added them despite instructions
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        extracted: Dict[str, Any] = json.loads(raw_text)
    except Exception as e:
        print(f"WARNING citation_extractor: extraction failed — {e}")
        return existing_metadata

    # Merge: existing_metadata wins; extracted fills gaps only
    merged = dict(existing_metadata)

    if needs_authors and extracted.get('authors'):
        merged['authors'] = extracted['authors']
    if needs_year and extracted.get('year') is not None:
        try:
            merged['publication_year'] = int(extracted['year'])
        except (ValueError, TypeError):
            pass
    if needs_journal and extracted.get('journal'):
        merged['journal_name'] = extracted['journal']
    if needs_doi and extracted.get('doi'):
        merged['doi'] = extracted['doi']
    if needs_title and extracted.get('title'):
        merged['title'] = extracted['title']

    return merged
