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
from haystack import Pipeline, component
from haystack.components.routers import ConditionalRouter

from core.utils.generator_factory import create_generator, get_agent_config

# Import extraction components
from functionalities.extraction.converters.pdf_to_markdown import PDFToMarkdownConverter
from functionalities.extraction.agents.data_extraction_agent import DataExtractionAgent
from functionalities.extraction.agents.verification_agent import ExtractionVerificationAgent
from functionalities.extraction.components.markdown_preprocessor import MarkdownPreprocessor
from functionalities.extraction.components.output_saver import OutputSaver

# Import registries and utilities
from core.registries.context_registry import ContextPromptRegistry
from functionalities.extraction.utils.output_saver import save_extraction_output

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


def create_source_extraction_pipeline(
    generator: Any,
    verification_generator: Any,
    coverage_check: bool,
) -> Pipeline:
    """Build the topic Source Extraction Pipeline as a Haystack graph.

    Flow: pdf_converter → pdf_router → preprocess → extraction_agent
          → verification_agent → output_saver

    pdf_router (ConditionalRouter) gates the chain: on PDF-conversion failure the
    "markdown_failed" branch dead-ends, so no downstream component runs. The
    extraction-failed and no_data short-circuits are handled after the run by the
    result-assembly shim in run_source_extraction_pipeline (reads component outputs
    via include_outputs_from) — cleaner than forwarding every field through routers.
    """
    pipeline = Pipeline()

    pipeline.add_component("pdf_converter", PDFToMarkdownConverter())
    pipeline.add_component("pdf_router", ConditionalRouter(routes=[
        {"condition": "{{ status != 'failed' }}", "output": "{{ markdown }}",
         "output_name": "markdown_ok", "output_type": str},
        {"condition": "{{ status == 'failed' }}", "output": "{{ markdown }}",
         "output_name": "markdown_failed", "output_type": str},
    ]))
    pipeline.add_component("preprocess", MarkdownPreprocessor())
    # bm25_alpha=0.60: topic queries are descriptive paraphrases (not verbatim text),
    # so semantic scoring needs real weight to anchor them.
    pipeline.add_component("extraction_agent", DataExtractionAgent(
        generator=generator, coverage_check=coverage_check, bm25_alpha=0.60))
    pipeline.add_component("verification_agent",
                           ExtractionVerificationAgent(generator=verification_generator))
    pipeline.add_component("output_saver", OutputSaver())

    pipeline.connect("pdf_converter.markdown_text", "pdf_router.markdown")
    pipeline.connect("pdf_converter.extraction_status", "pdf_router.status")
    pipeline.connect("pdf_router.markdown_ok", "preprocess.markdown_text")
    pipeline.connect("preprocess.markdown_text", "extraction_agent.markdown_text")
    pipeline.connect("preprocess.markdown_text", "verification_agent.source_text")
    pipeline.connect("preprocess.source_metadata", "output_saver.source_metadata")
    pipeline.connect("extraction_agent.extracted_data", "verification_agent.extracted_data")
    pipeline.connect("verification_agent.verified_data", "output_saver.verified_data")

    return pipeline


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

        extraction_cfg = get_agent_config("data_extraction")
        pipeline = create_source_extraction_pipeline(
            generator=create_generator("data_extraction"),
            verification_generator=create_generator("verification"),
            coverage_check=extraction_cfg.get("coverage_check", True),
        )

        # Wire progress callbacks onto the components (data_aggregation pattern):
        # each stage emits its own label as it runs.
        if progress_callback:
            for name in ("pdf_converter", "preprocess", "extraction_agent", "verification_agent"):
                pipeline.get_component(name).progress_callback = progress_callback

        source_id = source_metadata.get('id', 'unknown')
        source_title = source_metadata.get('title', '')

        result = pipeline.run(
            {
                "pdf_converter": {"pdf_bytes": pdf_bytes, "source_metadata": source_metadata},
                "preprocess": {"source_metadata": source_metadata},
                "extraction_agent": {
                    "species_name": species_name,
                    "research_topic": research_topic,
                    "search_terms": search_terms,
                    "universal_id": universal_id,
                    "session_id": session_id,
                    "synonym_list": synonym_list,
                },
                "verification_agent": {
                    "species_name": species_name,
                    "research_topic": research_topic,
                    "universal_id": universal_id,
                    "source_id": source_id,
                    "source_title": source_title,
                    "extracted_data_dir": extracted_data_dir,
                    "session_id": session_id,
                },
                "output_saver": {
                    "universal_id": universal_id,
                    "source_id": source_id,
                    "research_topic": research_topic,
                    "species_name": species_name,
                    "extraction_type": "topic",
                    "extracted_data_dir": extracted_data_dir,
                    "save_output": save_output,
                },
            },
            include_outputs_from={
                "pdf_converter", "preprocess", "extraction_agent",
                "verification_agent", "output_saver",
            },
        )

        # ── Result-assembly shim: graph outputs → legacy return contract ──────────
        # Reproduces the exact short-circuit semantics of the former inline returns.
        pdf_out = result.get("pdf_converter", {})
        if pdf_out.get("extraction_status") == "failed":
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": f"PDF conversion failed: {pdf_out.get('error_message', 'Unknown PDF error')}",
                "fields_extracted": 0
            }

        extr = result.get("extraction_agent", {})
        # A real failure (API error) carries an error_message + error_type.
        if extr.get("extraction_status") == "failed":
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": extr.get("error_message", "Extraction failed"),
                "error_type": extr.get("error_type", "unknown"),
                "fields_extracted": 0
            }

        raw_extracted_data = extr.get("extracted_data", {})
        # Extraction ran cleanly but found nothing relevant — a legitimate empty result.
        if not raw_extracted_data:
            return {
                "extraction_status": "no_data",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": None,
                "fields_extracted": 0
            }

        verif = result.get("verification_agent", {})
        verified_data = verif.get("verified_data", {})
        fields_removed = verif.get("fields_removed_count", 0)
        fields_count = len(verified_data)

        if fields_removed > 0:
            halluc = len(verif.get("removed_hallucinations", []))
            wrong_sp = len(verif.get("removed_wrong_species", []))
            print(f"Verification removed {fields_removed} field(s): "
                  f"{halluc} hallucination(s), {wrong_sp} wrong-species")
            print(f"Kept {fields_count} verified field(s)")

        # Translation info comes from the (possibly updated) metadata the preprocess
        # component emitted.
        prep_meta = result.get("preprocess", {}).get("source_metadata", {})

        return {
            "extraction_status": "success",
            "extracted_data": verified_data,
            "output_filepath": result.get("output_saver", {}).get("output_filepath"),
            "error_message": None,
            "fields_extracted": fields_count,
            "translated_from": prep_meta.get("translated_from"),
            "translation_note": prep_meta.get("translation_note"),
            "translation_failed": prep_meta.get("translation_failed", False)
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


@component
class ContextProcessor:
    """Filter context extraction locally and persist it — the context path's terminal node.

    Replaces the LLM verifier for context fields: the paper_summary schema is fixed, so
    the structural checks in _filter_context_fields are sufficient (see that function's
    docstring for why LLM verification is avoided here). No-ops on failed/empty input.
    """

    @component.output_types(
        verified_data=Dict[str, Any],
        output_filepath=Optional[str],
        fields_extracted=int,
    )
    def run(
        self,
        extracted_data: Dict[str, Any],
        extraction_status: str,
        context_key: str,
        universal_id: str,
        source_id: str,
        source_metadata: Dict[str, Any],
        species_name: str,
        extracted_data_dir: Optional[Path] = None,
        save_output: bool = True,
    ) -> Dict[str, Any]:
        if extraction_status == "failed" or not extracted_data:
            return {"verified_data": {}, "output_filepath": None, "fields_extracted": 0}

        verified_data, _removed, fields_removed = _filter_context_fields(
            extracted_data, _PAPER_SUMMARY_FIELDS)
        if fields_removed > 0:
            print(f"[Context] {context_key}: Local filter removed {fields_removed} field(s)")

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
                extracted_data_dir=extracted_data_dir,
            )
            output_filepath = save_result["output_filepath"]

        return {
            "verified_data": verified_data,
            "output_filepath": output_filepath,
            "fields_extracted": len(verified_data),
        }


def create_context_extraction_pipeline(generator: Any) -> Pipeline:
    """Build the context (paper_summary) extraction pipeline as a Haystack graph.

    Same shape as the topic pipeline (pdf_converter → pdf_router → preprocess →
    extraction_agent) but ends in a local ContextProcessor (structural filter + save)
    instead of the LLM verifier.
    """
    pipeline = Pipeline()

    pipeline.add_component("pdf_converter", PDFToMarkdownConverter())
    pipeline.add_component("pdf_router", ConditionalRouter(routes=[
        {"condition": "{{ status != 'failed' }}", "output": "{{ markdown }}",
         "output_name": "markdown_ok", "output_type": str},
        {"condition": "{{ status == 'failed' }}", "output": "{{ markdown }}",
         "output_name": "markdown_failed", "output_type": str},
    ]))
    pipeline.add_component("preprocess", MarkdownPreprocessor())
    # coverage_check=False: the schema is fixed (7 named fields), so a second open-ended
    # pass only generates hallucinated field names.
    # bm25_alpha=0.50: context fields are terse metadata with zero BM25 token overlap.
    pipeline.add_component("extraction_agent", DataExtractionAgent(
        generator=generator, coverage_check=False, bm25_alpha=0.50))
    pipeline.add_component("context_processor", ContextProcessor())

    pipeline.connect("pdf_converter.markdown_text", "pdf_router.markdown")
    pipeline.connect("pdf_converter.extraction_status", "pdf_router.status")
    pipeline.connect("pdf_router.markdown_ok", "preprocess.markdown_text")
    pipeline.connect("preprocess.markdown_text", "extraction_agent.markdown_text")
    pipeline.connect("preprocess.source_metadata", "context_processor.source_metadata")
    pipeline.connect("extraction_agent.extracted_data", "context_processor.extracted_data")
    pipeline.connect("extraction_agent.extraction_status", "context_processor.extraction_status")

    return pipeline


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

    # Use provided session_id (captured on main thread by caller) or fall back to current context
    if session_id is None:
        session_id = get_session_id()

    pipeline = create_context_extraction_pipeline(
        generator=create_generator("data_extraction"))

    context_results: Dict[str, Any] = {}
    context_keys_extracted: List[str] = []
    total_fields = 0
    translation_meta: Dict[str, Any] = {}

    # context_keys is a single key today ('paper_summary'), so the full pipeline
    # (incl. PDF conversion + preprocess) runs once per key. If context prompts
    # multiply, hoist conversion/preprocess out of this loop to avoid re-parsing.
    for context_key in context_keys:
        print(f"[Context] Extracting {context_key} from source '{source_id}'...")
        try:
            result = pipeline.run(
                {
                    "pdf_converter": {"pdf_bytes": pdf_bytes, "source_metadata": source_metadata},
                    "preprocess": {"source_metadata": source_metadata},
                    "extraction_agent": {
                        "species_name": species_name,
                        "research_topic": context_key,
                        "search_terms": [],  # context prompts don't use search terms
                        "universal_id": universal_id,
                        "session_id": session_id,
                    },
                    "context_processor": {
                        "context_key": context_key,
                        "universal_id": universal_id,
                        "source_id": source_id,
                        "species_name": species_name,
                        "extracted_data_dir": extracted_data_dir,
                        "save_output": save_output,
                    },
                },
                include_outputs_from={
                    "pdf_converter", "preprocess", "extraction_agent", "context_processor",
                },
            )
        except Exception as e:
            print(f"[Context] {context_key}: Failed with error: {e}")
            context_results[context_key] = {
                "extraction_status": "failed",
                "extracted_data": {},
                "fields_extracted": 0,
                "error_message": str(e),
            }
            continue

        # PDF failure aborts the whole source (matches the former pre-loop check).
        pdf_out = result.get("pdf_converter", {})
        if pdf_out.get("extraction_status") == "failed":
            return {
                "context_status": "failed",
                "context_results": {},
                "context_keys_extracted": [],
                "total_context_fields": 0,
                "error_message": f"PDF conversion failed: {pdf_out.get('error_message', 'Unknown PDF error')}",
            }

        # Capture translation info from the (possibly updated) preprocess metadata.
        prep_meta = result.get("preprocess", {}).get("source_metadata", {})
        if prep_meta.get("translated_from") and not translation_meta:
            translation_meta = {
                "translated_from": prep_meta["translated_from"],
                "translation_failed": prep_meta.get("translation_failed", False),
                "translation_note": prep_meta.get("translation_note", ""),
            }

        extr = result.get("extraction_agent", {})
        extraction_status = extr.get("extraction_status", "failed")
        raw_data = extr.get("extracted_data", {})

        if extraction_status == "failed":
            context_results[context_key] = {
                "extraction_status": "failed",
                "extracted_data": {},
                "fields_extracted": 0,
                "error_message": extr.get("error_message", "Extraction failed"),
            }
            continue

        if not raw_data:
            context_results[context_key] = {
                "extraction_status": "no_data",
                "extracted_data": {},
                "fields_extracted": 0,
                "error_message": None,
            }
            continue

        proc = result.get("context_processor", {})
        verified_data = proc.get("verified_data", {})
        fields_count = len(verified_data)

        context_results[context_key] = {
            "extraction_status": "success",
            "extracted_data": verified_data,
            "fields_extracted": fields_count,
            "output_filepath": proc.get("output_filepath"),
            "error_message": None,
        }

        if fields_count > 0:
            context_keys_extracted.append(context_key)
            total_fields += fields_count

        print(f"[Context] {context_key}: Extracted {fields_count} verified field(s)")

    overall_status = "success" if context_keys_extracted else "failed"

    result = {
        "context_status": overall_status,
        "context_results": context_results,
        "context_keys_extracted": context_keys_extracted,
        "total_context_fields": total_fields,
    }

    # Surface translation info at the top level so callers can show a banner.
    if translation_meta:
        result.update(translation_meta)

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
