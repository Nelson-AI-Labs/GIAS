#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Custom Topic Pipeline (CTS)

Three-agent pipeline for handling custom research topics:
1. Topic Interpreter Agent - Interprets user's custom topic
2. Prompt Generator Agent - Generates extraction prompts
3. Data Extraction Agent - Extracts data using custom prompts

Usage:
    # Step 1: Interpret custom topic
    interpretation = run_topic_interpretation(
        custom_topic="invasive potential",
        species_name="Procambarus clarkii"
    )

    # Step 2: User reviews interpretation (in UI)

    # Step 3: Generate extraction prompt
    prompt = run_prompt_generation(
        custom_topic="invasive potential",
        interpretation_data=interpretation,
        species_name="Procambarus clarkii"
    )

    # Step 4: Extract data from sources
    results = run_custom_topic_extraction(
        pdf_bytes=pdf_data,
        source_metadata=metadata,
        custom_topic="invasive potential",
        species_name="Procambarus clarkii",
        universal_id="species_123"
    )
"""

from typing import Dict, Any, Optional, List
from pathlib import Path

# Import extraction components
from functionalities.extraction.agents.custom_topic_interpreter import TopicInterpreterAgent
from functionalities.extraction.agents.custom_prompt_generator import PromptGeneratorAgent
from functionalities.extraction.agents.custom_search_term_generator import SearchTermGeneratorAgent
from functionalities.extraction.agents.data_extraction_agent import DataExtractionAgent
from functionalities.extraction.converters.pdf_to_markdown import PDFToMarkdownConverter

# Import utilities
from functionalities.extraction.utils.prompt_loader import load_custom_prompt, save_custom_prompt, prompt_exists
from functionalities.extraction.utils.output_saver import save_extraction_output
from functionalities.extraction.agents.verification_agent import ExtractionVerificationAgent

from core.utils.generator_factory import create_generator
from core.utils.session_context import get_session_id


# ============================================================================
# AGENT 1: TOPIC INTERPRETATION
# ============================================================================

def run_topic_interpretation(
    custom_topic: str,
    species_name: str = ""
) -> Dict[str, Any]:
    """
    Run Agent 1: Topic Interpreter

    Interprets a custom research topic and generates explanation
    of what will be extracted.

    Args:
        custom_topic: User's custom topic (e.g., "invasive potential")
        species_name: Optional species name for context

    Returns:
        Dict containing:
            - interpretation: Text explanation
            - key_concepts: List of key concepts
            - scope_boundaries: What's included/excluded
            - full_interpretation: Complete formatted text
    """
    print(f"[CTS Agent 1] Interpreting topic: '{custom_topic}'")

    agent = TopicInterpreterAgent()
    result = agent.run(
        custom_topic=custom_topic,
        species_name=species_name
    )

    print(f"[CTS Agent 1] ✓ Interpretation complete")
    return result


# ============================================================================
# SEARCH TERM GENERATION FOR CUSTOM TOPICS
# ============================================================================

def generate_custom_search_terms(
    custom_topic: str,
    species_name: str,
    num_terms: int = 4
) -> list[str]:
    """
    Generate search terms for custom topics using SearchTermGeneratorAgent.

    This function is used for custom topics only. Anchor topics use
    predefined search terms from StandardTopicRegistry.

    Args:
        custom_topic: The custom topic name
        species_name: Species scientific name
        num_terms: Number of search terms to generate (default: 4)

    Returns:
        List of search terms
    """
    print(f"[CTS Search] Generating search terms for custom topic: '{custom_topic}'")

    agent = SearchTermGeneratorAgent()
    result = agent.run(
        research_topic=custom_topic,
        species_name=species_name,
        num_terms=num_terms
    )

    search_terms = result.get('search_terms', [])
    print(f"[CTS Search] ✓ Generated {len(search_terms)} search terms")

    return search_terms


# ============================================================================
# AGENT 2: PROMPT GENERATION
# ============================================================================

def run_prompt_generation(
    custom_topic: str,
    interpretation_data: Dict[str, Any],
    species_name: str = "",
    force_regenerate: bool = False
) -> Dict[str, Any]:
    """
    Run Agent 2: Prompt Generator

    Generates extraction prompt for custom topic using Mistral-optimized template.

    Args:
        custom_topic: Custom topic name
        interpretation_data: Output from Agent 1
        species_name: Optional species name
        force_regenerate: If True, regenerate even if prompt exists

    Returns:
        Dict containing:
            - extraction_prompt: Generated prompt markdown
            - generation_status: "success" or "failed"
            - prompt_filepath: Path to saved prompt (if saved)
    """
    print(f"[CTS Agent 2] Generating prompt for: '{custom_topic}'")

    # Check if prompt already exists
    if not force_regenerate and prompt_exists(custom_topic):
        print(f"[CTS Agent 2] ✓ Prompt already exists in cache")
        prompt_content = load_custom_prompt(custom_topic)
        return {
            "extraction_prompt": prompt_content,
            "generation_status": "loaded_from_cache",
            "prompt_filepath": None
        }

    # Generate new prompt
    agent = PromptGeneratorAgent()
    result = agent.run(
        custom_topic=custom_topic,
        topic_interpretation=interpretation_data['interpretation'],
        key_concepts=interpretation_data['key_concepts'],
        scope_boundaries=interpretation_data['scope_boundaries'],
        species_name=species_name
    )

    if result['generation_status'] != 'success':
        print(f"[CTS Agent 2] ✗ Prompt generation failed: {result['generation_status']}")
        return result

    # Save to session cache
    saved = save_custom_prompt(custom_topic, result['extraction_prompt'])

    if saved:
        print(f"[CTS Agent 2] ✓ Prompt generated and saved")
    else:
        print(f"[CTS Agent 2] ⚠ Prompt generated but not saved")

    return {
        "extraction_prompt": result['extraction_prompt'],
        "generation_status": "success",
        "prompt_filepath": f"cache/{{session_id}}/custom_extraction_prompts/{custom_topic}.md" if saved else None
    }


# ============================================================================
# AGENT 3: DATA EXTRACTION
# ============================================================================

def run_custom_topic_extraction(
    pdf_bytes: bytes,
    source_metadata: Dict[str, Any],
    custom_topic: str,
    species_name: str,
    search_terms: list,
    universal_id: str,
    save_output: bool = True,
    extracted_data_dir: Optional[Path] = None,
    session_id: Optional[str] = None,
    synonym_list: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Run Agent 3: Data Extraction

    Extracts data from PDF using custom prompt generated by Agent 2.

    Args:
        pdf_bytes: Binary PDF content
        source_metadata: Dict with 'url', 'title', 'domain', 'id'
        custom_topic: Custom topic name
        species_name: Species name
        search_terms: List of search terms used
        universal_id: Universal species ID
        save_output: Whether to save extracted data
        session_id: Session ID (captured on main thread for thread safety)
        synonym_list: Additional species name synonyms for extraction context

    Returns:
        Dict containing:
            - extraction_status: "success", "no_data" (ran cleanly, found nothing
              relevant), or "failed" (PDF/API error)
            - extracted_data: Extracted JSON data
            - output_filepath: Path to saved file (if saved)
            - error_message: Error description if failed, None for success/no_data
            - fields_extracted: Number of fields extracted
    """
    print(f"[CTS Agent 3] Extracting data for topic: '{custom_topic}'")

    if session_id is None:
        session_id = get_session_id()

    try:
        # Ensure custom prompt exists
        if not prompt_exists(custom_topic):
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": f"No custom prompt found for topic '{custom_topic}'. Run Agent 2 first.",
                "fields_extracted": 0
            }

        # Step 1: Convert PDF to markdown
        pdf_converter = PDFToMarkdownConverter()
        pdf_result = pdf_converter.run(pdf_bytes=pdf_bytes, source_metadata=source_metadata)

        if pdf_result.get("extraction_status") == "failed":
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": f"PDF conversion failed: {pdf_result.get('error_message', 'Unknown PDF error')}",
                "fields_extracted": 0
            }

        markdown_text = pdf_result["markdown_text"]

        # Step 2: Extract structured data
        extraction_agent = DataExtractionAgent(generator=create_generator("data_extraction"))
        extraction_result = extraction_agent.run(
            markdown_text=markdown_text,
            species_name=species_name,
            research_topic=custom_topic,
            search_terms=search_terms,
            universal_id=universal_id,
            session_id=session_id,
            synonym_list=synonym_list or []
        )

        extraction_status = extraction_result.get("extraction_status", "failed")
        raw_extracted_data = extraction_result.get("extracted_data", {})

        # A real failure (PDF conversion or API error) carries an error_message.
        if extraction_status == "failed":
            return {
                "extraction_status": "failed",
                "extracted_data": {},
                "output_filepath": None,
                "error_message": extraction_result.get("error_message", "Extraction failed"),
                "fields_extracted": 0
            }

        # Clean run, nothing relevant found — a legitimate empty result, not a failure.
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
        verification_agent = ExtractionVerificationAgent(generator=create_generator("verification"))
        verification_result = verification_agent.run(
            extracted_data=raw_extracted_data,
            source_text=markdown_text,
            species_name=species_name,
            research_topic=custom_topic,
            universal_id=universal_id,
            source_id=source_metadata.get('id', 'unknown'),
            source_title=source_metadata.get('title', ''),
            extracted_data_dir=extracted_data_dir,
            session_id=session_id
        )

        verified_data = verification_result.get("verified_data", {})
        fields_count = len(verified_data)

        # Save output
        output_filepath = None
        if save_output and verified_data:
            save_result = save_extraction_output(
                extracted_data=verified_data,
                universal_id=universal_id,
                source_id=source_metadata.get('id', 'unknown'),
                research_topic=custom_topic,
                source_metadata=source_metadata,
                species_name=species_name,
                extraction_type="topic",
                topic_type="custom",
                pipeline_name="custom_topic_pipeline",
                extracted_data_dir=extracted_data_dir
            )
            output_filepath = save_result["output_filepath"]

        print(f"[CTS Agent 3] ✓ Extraction complete: {fields_count} fields (verified)")

        return {
            "extraction_status": "success",
            "extracted_data": verified_data,
            "output_filepath": output_filepath,
            "error_message": None,
            "fields_extracted": fields_count
        }

    except Exception as e:
        print(f"[CTS Agent 3] ✗ Extraction error: {e}")
        return {
            "extraction_status": "failed",
            "extracted_data": {},
            "output_filepath": None,
            "error_message": f"Pipeline error: {str(e)}",
            "fields_extracted": 0
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def run_full_custom_topic_workflow(
    custom_topic: str,
    species_name: str,
    pdf_bytes: bytes,
    source_metadata: Dict[str, Any],
    search_terms: list,
    universal_id: str,
    user_approved_interpretation: bool = True
) -> Dict[str, Any]:
    """
    Run complete custom topic workflow: interpret → generate → extract

    Args:
        custom_topic: Custom topic name
        species_name: Species name
        pdf_bytes: PDF data
        source_metadata: Source info
        search_terms: Search terms used
        universal_id: Species ID
        user_approved_interpretation: Whether user approved interpretation

    Returns:
        Dict with all three agent results
    """
    print(f"\n{'='*60}")
    print(f"Custom Topic Workflow: '{custom_topic}'")
    print(f"{'='*60}\n")

    # Agent 1: Interpret
    interpretation = run_topic_interpretation(custom_topic, species_name)

    if not user_approved_interpretation:
        return {
            "agent_1": interpretation,
            "agent_2": None,
            "agent_3": None,
            "workflow_status": "awaiting_user_approval"
        }

    # Agent 2: Generate prompt
    prompt_result = run_prompt_generation(custom_topic, interpretation, species_name)

    if prompt_result['generation_status'] not in ['success', 'loaded_from_cache']:
        return {
            "agent_1": interpretation,
            "agent_2": prompt_result,
            "agent_3": None,
            "workflow_status": "prompt_generation_failed"
        }

    # Agent 3: Extract
    extraction_result = run_custom_topic_extraction(
        pdf_bytes=pdf_bytes,
        source_metadata=source_metadata,
        custom_topic=custom_topic,
        species_name=species_name,
        search_terms=search_terms,
        universal_id=universal_id
    )

    return {
        "agent_1": interpretation,
        "agent_2": prompt_result,
        "agent_3": extraction_result,
        "workflow_status": "complete"
    }
