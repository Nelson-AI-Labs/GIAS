#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
MarkdownPreprocessor Component

Wraps the deterministic pre-extraction glue (citation backfill, language
detection/translation, boilerplate noise stripping) as a single Haystack
component so the Source Extraction Pipeline can run it as a graph node.

The logic is lifted verbatim from the former inline steps in
standard_pipeline.run_source_extraction_pipeline — no behavioural change.
"""

from typing import Dict, Any, Optional

from haystack import component

from functionalities.extraction.agents.citation_extractor import extract_citation_from_markdown
from functionalities.extraction.utils.paragraph_resolver import strip_noise_sections
from core.utils.language_utils import detect_language, translate_to_english


@component
class MarkdownPreprocessor:
    """Backfill citation metadata, translate non-English text, strip noise sections.

    Runs after PDF conversion and before extraction. Shared by the topic and
    context extraction pipelines.
    """

    def __init__(self):
        # Optional callback(label) — set externally before pipeline.run().
        self.progress_callback = None

    @component.output_types(
        markdown_text=str,
        source_metadata=Dict[str, Any],
    )
    def run(
        self,
        markdown_text: str,
        source_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        source_metadata = dict(source_metadata or {})

        # Fill missing citation metadata from PDF text (only for manually uploaded
        # sources where API fields like authors/year may be absent).
        if not (source_metadata.get("authors") and source_metadata.get("publication_year")):
            source_metadata = extract_citation_from_markdown(markdown_text, source_metadata)

        # Detect language — translate to English if needed.
        lang_result = detect_language(markdown_text)
        if not lang_result["is_english"] and not lang_result["detection_failed"]:
            lang_name = lang_result["language_name"]
            lang_code = lang_result["language_code"]
            print(f"[Language] Detected {lang_name} (confidence: {lang_result['confidence']:.0%}). Translating...")
            trans_result = translate_to_english(markdown_text, lang_code)
            source_metadata = {
                **source_metadata,
                "translated_from": lang_name,
                "translation_failed": not trans_result["success"],
                "translation_note": trans_result["translation_note"],
            }
            markdown_text = trans_result["translated_text"]
            print(f"[Language] {trans_result['translation_note']}")

        if self.progress_callback:
            self.progress_callback("Detecting language")

        # Strip boilerplate noise sections (Acknowledgments, Funding, References, …)
        # so both the extraction prompt and the ParagraphResolver see content only.
        markdown_text = strip_noise_sections(markdown_text)

        return {"markdown_text": markdown_text, "source_metadata": source_metadata}
