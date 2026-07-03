#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Source Extraction Pipeline (SEP)

A Haystack Pipeline for extracting structured data from research PDFs.
Converts PDF → Markdown → AI Extraction → JSON Output

Also supports contextual extraction: always-run prompts that capture
study metadata (geographic location, population details, methodology).
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from haystack import Pipeline

from core.utils.generator_factory import create_generator, get_agent_config

# Import extraction components
from functionalities.extraction.converters.pdf_to_markdown import PDFToMarkdownConverter
from functionalities.extraction.agents.data_extraction_agent import DataExtractionAgent
from functionalities.extraction.agents.verification_agent import ExtractionVerificationAgent

# Import registries and utilities
from core.registries.context_registry import ContextPromptRegistry
from functionalities.extraction.utils.output_saver import save_extraction_output
from functionalities.extraction.utils.paragraph_resolver import strip_noise_sections, ParagraphResolver
from core.utils.language_utils import detect_language, translate_to_english

# Import session-aware cache manager
from core.utils.cache_manager import get_extracted_data_dir
from core.utils.session_context import get_session_id
from core.utils.config_loader import get_api_key


# Expected fields for paper_summary context extraction.
# Hallucinated field names outside this set are dropped by _filter_context_fields.
_PAPER_SUMMARY_FIELDS = frozenset({
    "paper_type", "key_finding", "management_relevance",
    "data_or_specimen_origin", "study_scale", "study_period", "publication_venue",
})


def _filter_context_fields(
    raw_data: Dict[str, Any],
    expected_fields: frozenset,
) -> tuple:
    """Deterministic local filter for context extraction (replaces LLM verification).

    LLM verification was designed for topic/fact extraction where value=passage.
    For context fields, the LLM synthesizes a concise value from the full paper
    (value ≠ passage). Verification Check 3 (field-label/passage match) fires false
    positives unpredictably, causing 3–6/7 variance between identical runs.

    This filter applies only structural checks — no Mistral call:
      1. unexpected_field      — field name outside expected schema
      2. passage_not_found     — no candidate_source_quote
      3. duplicate_source      — same passage already used by a sibling field
      4. empty_value           — value is empty/whitespace
      5. unsynthesized_value   — value == passage and len(passage) > 120 (LLM did not
                                 synthesize a concise answer; reused raw passage verbatim)

    Returns (verified_data, removed_fields, n_removed).
    """
    kept: Dict[str, Any] = {}
    removed: Dict[str, Any] = {}
    seen_passages: Dict[str, str] = {}

    for field_name, content in raw_data.items():
        if not isinstance(content, dict):
            continue

        # 1. Schema guard: drop hallucinated field names
        if field_name not in expected_fields:
            removed[field_name] = {**content, "removal_reason": "unexpected_field"}
            continue

        # 2. Passage must exist
        passage = content.get("candidate_source_quote", "")
        if not passage:
            removed[field_name] = {**content, "removal_reason": "passage_not_found"}
            continue

        # 3. Dedup passages (mirrors VerificationAgent._deduplicate_passages logic)
        norm = re.sub(r"\s+", " ", re.sub(r"\b\d{1,4}\b", "", passage)).strip()
        if len(norm) >= 80:
            if norm in seen_passages:
                print(
                    f"[ContextFilter] Duplicate passage: '{field_name}' "
                    f"shares passage with '{seen_passages[norm]}' — removing"
                )
                removed[field_name] = {**content, "removal_reason": "duplicate_source"}
                continue
            seen_passages[norm] = field_name

        # 4. Value must be non-empty
        if not (content.get("value") or "").strip():
            removed[field_name] = {**content, "removal_reason": "empty_value"}
            continue

        # 5. Unsynthesized copy: if value == passage and passage is long, the LLM did not
        #    write a concise answer — it reused the raw retrieved passage verbatim.
        #    Context fields require a concise synthesized value; raw copies are rejected.
        value_str = content.get("value", "")
        if value_str == passage and len(passage) > 120:
            removed[field_name] = {**content, "removal_reason": "unsynthesized_value"}
            continue

        # Keep: strip internal resolver keys to match topic-path verified_data schema.
        # source_quote is the canonical passage key downstream; candidate_source_quote is internal.
        _internal = {"text_anchor", "candidate_source_quote"}
        clean = {k: v for k, v in content.items() if k not in _internal}
        kept[field_name] = {**clean, "source_quote": passage, "verification_verdict": "verified"}

    n_removed = len(removed)
    if n_removed:
        reasons: Dict[str, int] = {}
        for c in removed.values():
            r = c.get("removal_reason", "unknown") if isinstance(c, dict) else "unknown"
            reasons[r] = reasons.get(r, 0) + 1
        reason_str = ", ".join(f"{n} {r}" for r, n in reasons.items())
        print(f"[ContextFilter] Removed {n_removed} field(s): {reason_str}")

    return kept, removed, n_removed


def run_source_extraction_pipeline(
    pdf_bytes: bytes,
    source_metadata: Dict[str, Any],
    species_name: str,
    research_topic: str,
    search_terms: list,
    universal_id: str,
    save_output: bool = True,
    extracted_data_dir: Optional[Path] = None,
    session_id: Optional[str] = None,
    synonym_list: Optional[List[str]] = None,
    progress_callback=None
) -> Dict[str, Any]:
    """
    Run the source extraction pipeline on a single PDF source.

    Args:
        pdf_bytes: Binary PDF content
        source_metadata: Dict with 'url', 'title', 'domain', 'id'
        species_name: Name of the species
        research_topic: Research topic (e.g., "biological characteristics")
        search_terms: List of search terms used to find this source
        universal_id: Universal ID for the species (for file organization)
        save_output: Whether to save extracted data to file
        extracted_data_dir: Pre-resolved extracted data directory (for thread safety)
        session_id: Session ID captured on main thread (avoids thread context loss)

    Returns:
        Dict containing:
            - extraction_status: "success", "no_data" (ran cleanly, found nothing
              relevant for this topic), or "failed" (PDF/API error)
            - extracted_data: The verified JSON data (hallucinated fields removed)
            - output_filepath: Path to saved JSON file (if save_output=True)
            - error_message: Error description if failed, None for success/no_data
            - fields_extracted: Number of verified fields extracted
    """
    try:
        # Use provided session_id (captured on main thread by caller) or fall back to current context
        if session_id is None:
            session_id = get_session_id()

        generator = create_generator("data_extraction")
        extraction_cfg = get_agent_config("data_extraction")
        pdf_converter = PDFToMarkdownConverter()
        # bm25_alpha=0.60: topic extraction queries are descriptive paraphrases
        # (not verbatim text), so semantic scoring needs real weight to anchor them.
        # Context extraction uses 0.50 (terse metadata fields); module default is 0.85.
        extraction_agent = DataExtractionAgent(
            generator=generator,
            coverage_check=extraction_cfg.get("coverage_check", True),
            bm25_alpha=0.60,
        )
        verification_agent = ExtractionVerificationAgent(generator=create_generator("verification"))

        def _cb(label):
            if progress_callback:
                progress_callback(label)

        # Step 1: Convert PDF to markdown
        pdf_result = pdf_converter.run(pdf_bytes=pdf_bytes, source_metadata=source_metadata)
        pdf_status = pdf_result.get("extraction_status", "failed")

        if pdf_status == "failed":
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": f"PDF conversion failed: {pdf_result.get('error_message', 'Unknown PDF error')}",
                "fields_extracted": 0
            }

        _cb("Converting PDF")
        markdown_text = pdf_result["markdown_text"]

        # Step 1b: Fill missing citation metadata from PDF text (only for manually
        # uploaded sources where API fields like authors/year may be absent)
        if not (source_metadata.get('authors') and source_metadata.get('publication_year')):
            from functionalities.extraction.agents.citation_extractor import extract_citation_from_markdown
            source_metadata = extract_citation_from_markdown(markdown_text, source_metadata)

        # Step 2: Detect language — translate to English if needed
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
                "translation_note": trans_result["translation_note"]
            }
            markdown_text = trans_result["translated_text"]
            print(f"[Language] {trans_result['translation_note']}")
        _cb("Detecting language")

        # Step 2b: Strip boilerplate noise sections before extraction.
        # Removes Acknowledgments, Funding, Author Contributions, Ethics,
        # Supplementary Material, and References from the markdown so the LLM
        # prompt and the ParagraphResolver index both see only content sections.
        markdown_text = strip_noise_sections(markdown_text)

        # Build a resolver for the verification agent to use for cross-referencing.
        # This is a fresh instance (no used_char_starts state) so the verifier can
        # query any paragraph in the document without the extraction dedup penalty.
        verification_resolver = ParagraphResolver(markdown_text)

        # Step 3: Extract structured data
        extraction_result = extraction_agent.run(
            markdown_text=markdown_text,
            species_name=species_name,
            research_topic=research_topic,
            search_terms=search_terms,
            universal_id=universal_id,
            session_id=session_id,
            synonym_list=synonym_list
        )

        _cb("Extracting data")
        extraction_status = extraction_result.get("extraction_status", "failed")
        raw_extracted_data = extraction_result.get("extracted_data", {})

        # A real failure (PDF conversion or API error) carries an error_message.
        if extraction_status == "failed":
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": extraction_result.get("error_message", "Extraction failed"),
                "error_type": extraction_result.get("error_type", "unknown"),
                "fields_extracted": 0
            }

        # The extraction ran cleanly but the model found nothing relevant for this
        # topic in this source — a legitimate empty result, not a failure.
        if not raw_extracted_data:
            return {
                "extraction_status": "no_data",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": None,
                "fields_extracted": 0
            }

        # candidate_source_quote and pdf_page_index are populated inline by the
        # DataExtractionAgent via its find_passage tool, so no separate source-anchor
        # resolution step runs between extraction and verification.

        # Step 4: Verify extracted data
        verification_result = verification_agent.run(
            extracted_data=raw_extracted_data,
            source_text=markdown_text,
            species_name=species_name,
            research_topic=research_topic,
            universal_id=universal_id,
            source_id=source_metadata.get('id', 'unknown'),
            source_title=source_metadata.get('title', ''),
            extracted_data_dir=extracted_data_dir,
            session_id=session_id,
            paragraph_resolver=verification_resolver,
        )

        _cb("Verifying facts")
        verified_data = verification_result.get("verified_data", {})
        fields_removed = verification_result.get("fields_removed_count", 0)
        fields_count = len(verified_data)

        if fields_removed > 0:
            halluc = len(verification_result.get("removed_hallucinations", []))
            wrong_sp = len(verification_result.get("removed_wrong_species", []))
            print(f"Verification removed {fields_removed} field(s): "
                  f"{halluc} hallucination(s), {wrong_sp} wrong-species")
            print(f"Kept {fields_count} verified field(s)")

        # Step 5: Save output
        output_filepath = None
        if save_output and verified_data:
            save_result = save_extraction_output(
                extracted_data=verified_data,
                universal_id=universal_id,
                source_id=source_metadata.get('id', 'unknown'),
                research_topic=research_topic,
                source_metadata=source_metadata,
                species_name=species_name,
                extraction_type="topic",
                extracted_data_dir=extracted_data_dir
            )
            output_filepath = save_result["output_filepath"]

        return {
            "extraction_status": "success",
            "extracted_data": verified_data,
            "output_filepath": output_filepath,
            "error_message": None,
            "fields_extracted": fields_count,
            "translated_from": source_metadata.get("translated_from"),
            "translation_note": source_metadata.get("translation_note"),
            "translation_failed": source_metadata.get("translation_failed", False)
        }

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"ERROR: Pipeline failed with exception:")
        print(error_details)
        return {
            "extraction_status": "failed",
            "extracted_data": {},
            "output_filepath": None,
            "error_message": f"Pipeline error: {str(e)}",
            "fields_extracted": 0
        }


def run_context_extraction_for_source(
    pdf_bytes: bytes,
    source_metadata: Dict[str, Any],
    species_name: str,
    universal_id: str,
    save_output: bool = True,
    extracted_data_dir: Optional[Path] = None,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Run all contextual extraction prompts on a single source.

    Contextual prompts (geographic, population, methodology) run once per source
    to capture cross-cutting study metadata. Results are stored separately from
    topic-specific extractions.

    Args:
        pdf_bytes: Binary PDF content
        source_metadata: Dict with 'url', 'title', 'domain', 'id'
        species_name: Name of the species
        universal_id: Universal ID for the species (for file organization)
        save_output: Whether to save extracted data to file
        extracted_data_dir: Pre-resolved extracted data directory (for thread safety)

    Returns:
        Dict containing:
            - context_status: "success" if at least one context extracted, "failed" if all failed
            - context_results: Dict keyed by context_key with extraction results
            - context_keys_extracted: List of context keys that produced data
            - total_context_fields: Total number of fields extracted across all contexts
    """
    context_keys = ContextPromptRegistry.get_all_context_keys()
    source_id = source_metadata.get('id', 'unknown')

    # Convert PDF to markdown once (shared across all context extractions)
    pdf_converter = PDFToMarkdownConverter()
    pdf_result = pdf_converter.run(pdf_bytes=pdf_bytes, source_metadata=source_metadata)

    markdown_text = pdf_result.get("markdown_text", "")
    pdf_status = pdf_result.get("extraction_status", "failed")

    if pdf_status == "failed" or not markdown_text:
        pdf_error = pdf_result.get("error_message", "Unknown PDF error")
        return {
            "context_status": "failed",
            "context_results": {},
            "context_keys_extracted": [],
            "total_context_fields": 0,
            "error_message": f"PDF conversion failed: {pdf_error}"
        }

    # Detect language — translate to English if needed (shared across all context extractions)
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
            "translation_note": trans_result["translation_note"]
        }
        markdown_text = trans_result["translated_text"]
        print(f"[Language] {trans_result['translation_note']}")

    # Strip boilerplate noise sections before extraction (same as run_source_extraction_pipeline).
    markdown_text = strip_noise_sections(markdown_text)

    # Use provided session_id (captured on main thread by caller) or fall back to current context
    if session_id is None:
        session_id = get_session_id()

    # coverage_check disabled for context extraction: the schema is fixed (7 named fields),
    # so a second open-ended pass only generates hallucinated field names.
    # bm25_alpha=0.50: context fields are terse metadata (journal names, dates, locations)
    # with zero BM25 token overlap. Lowering alpha lets semantic scoring carry the result.
    # Topic extraction uses default alpha=0.85 (unchanged).
    extraction_agent = DataExtractionAgent(
        generator=create_generator("data_extraction"),
        coverage_check=False,
        bm25_alpha=0.50,
    )

    context_results = {}
    context_keys_extracted = []
    total_fields = 0

    for context_key in context_keys:
        print(f"[Context] Extracting {context_key} from source '{source_id}'...")

        try:
            # Run extraction agent with context key as the research_topic
            extraction_result = extraction_agent.run(
                markdown_text=markdown_text,
                species_name=species_name,
                research_topic=context_key,
                search_terms=[],  # Context prompts don't use search terms
                universal_id=universal_id,
                session_id=session_id
            )

            extraction_status = extraction_result.get("extraction_status", "failed")
            raw_data = extraction_result.get("extracted_data", {})

            if extraction_status == "failed":
                context_results[context_key] = {
                    "extraction_status": "failed",
                    "extracted_data": {},
                    "fields_extracted": 0,
                    "error_message": extraction_result.get("error_message", "Extraction failed")
                }
                continue

            if not raw_data:
                context_results[context_key] = {
                    "extraction_status": "no_data",
                    "extracted_data": {},
                    "fields_extracted": 0,
                    "error_message": None
                }
                continue

            # (anchor resolution removed) DataExtractionAgent populates
            # candidate_source_quote and pdf_page_index via find_passage tool.

            # Filter context fields locally — no LLM verification.
            # LLM verification fires false positives on synthesized context values
            # (value ≠ passage), causing 3–6/7 variance. Local structural checks
            # (schema guard, passage_exists, dedup) are sufficient for fixed 7-field schema.
            verified_data, _removed_ctx, fields_removed = _filter_context_fields(
                raw_data,
                _PAPER_SUMMARY_FIELDS,
            )

            if fields_removed > 0:
                print(f"[Context] {context_key}: Local filter removed {fields_removed} field(s)")

            fields_count = len(verified_data)

            # Save if requested
            output_filepath = None
            if save_output and verified_data:
                save_result = save_extraction_output(
                    extracted_data=verified_data,
                    universal_id=universal_id,
                    source_id=source_id,
                    research_topic=context_key,
                    source_metadata=source_metadata,
                    species_name=species_name,
                    extraction_type="context",
                    extracted_data_dir=extracted_data_dir
                )
                output_filepath = save_result["output_filepath"]

            context_results[context_key] = {
                "extraction_status": "success",
                "extracted_data": verified_data,
                "fields_extracted": fields_count,
                "output_filepath": output_filepath,
                "error_message": None
            }

            if fields_count > 0:
                context_keys_extracted.append(context_key)
                total_fields += fields_count

            print(f"[Context] {context_key}: Extracted {fields_count} verified field(s)")

        except Exception as e:
            print(f"[Context] {context_key}: Failed with error: {e}")
            context_results[context_key] = {
                "extraction_status": "failed",
                "extracted_data": {},
                "fields_extracted": 0,
                "error_message": str(e)
            }

    overall_status = "success" if context_keys_extracted else "failed"

    result = {
        "context_status": overall_status,
        "context_results": context_results,
        "context_keys_extracted": context_keys_extracted,
        "total_context_fields": total_fields
    }

    # Surface translation info at the top level so callers can show a banner
    if source_metadata.get("translated_from"):
        result["translated_from"] = source_metadata["translated_from"]
        result["translation_failed"] = source_metadata.get("translation_failed", False)
        result["translation_note"] = source_metadata.get("translation_note", "")

    return result


# Convenience function for batch processing
def run_batch_extraction(
    sources: list,
    species_name: str,
    universal_id: str
) -> Dict[str, Any]:
    """
    Run extraction on multiple sources.

    Args:
        sources: List of dicts with pdf_bytes, metadata, topics, search_terms
        species_name: Species name
        universal_id: Universal species ID

    Returns:
        Dict with results per source
    """
    results = {}

    for source in sources:
        source_id = source['metadata']['id']
        results[source_id] = {}

        # Extract for each topic assigned to this source
        for topic in source.get('topics', []):
            result = run_source_extraction_pipeline(
                pdf_bytes=source['pdf_bytes'],
                source_metadata=source['metadata'],
                species_name=species_name,
                research_topic=topic,
                search_terms=source.get('search_terms', []),
                universal_id=universal_id,
                save_output=True
            )
            results[source_id][topic] = result

    return results
