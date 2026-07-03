# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Topic Suggestion Service

Analyzes a source document's structure (TOC, abstract, keywords) and scores
each topic's relevance using AI. Pure service layer — no Streamlit imports.

Used by source_extraction.py to power per-card topic suggestions.
"""

from typing import Dict, List, Any, Optional


def _build_generator():
    from core.utils.generator_factory import create_generator
    return create_generator("topic_suggestion")


def _load_custom_topics(research_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the custom topics list from research state for the analyzer."""
    custom_topic_interpretations = research_state.get('custom_topic_interpretations', {})
    result = []
    for topic_name in research_state.get('custom_topics', []):
        interpretation_data = custom_topic_interpretations.get(topic_name, {})
        result.append({
            'key': topic_name,
            'topic_key': topic_name,
            'interpretation': interpretation_data.get('interpretation', 'Custom research topic')
        })
    return result


def analyze_single_source(
    source: Dict[str, Any],
    research_state: Dict[str, Any],
    generator: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Analyze a single source document for topic suggestions.

    Args:
        source: Source dict with uploaded PDF
        research_state: Research state dict (for custom topics)
        generator: Optional pre-built Mistral generator

    Returns:
        Dict with: has_structure, suggestions, status, error_message
    """
    from functionalities.extraction.utils.toc_extractor import get_document_structure
    from functionalities.extraction.agents.document_topic_analyzer import DocumentTopicAnalyzer
    from core.registries.topic_registry import StandardTopicRegistry

    pdf_bytes = source.get('uploaded_pdf')
    if not pdf_bytes:
        return {
            'has_structure': False,
            'suggestions': {},
            'status': 'failed',
            'error_message': 'No PDF uploaded'
        }

    toc_text = get_document_structure(pdf_bytes)
    if not toc_text:
        return {
            'has_structure': False,
            'suggestions': {},
            'status': 'failed',
            'error_message': 'No document structure found (no TOC, abstract, or keywords)'
        }

    if generator is None:
        generator = _build_generator()

    analyzer = DocumentTopicAnalyzer(generator=generator)
    standard_topics = [t for t in StandardTopicRegistry.TOPICS.values() if t.key != 'taxonomic_identity']
    custom_topics = _load_custom_topics(research_state)

    analysis_result = analyzer.run(
        toc_text=toc_text,
        standard_topics=standard_topics,
        custom_topics=custom_topics
    )

    return {
        'has_structure': True,
        'suggestions': analysis_result['topic_suggestions'],
        'status': analysis_result['analysis_status'],
        'error_message': analysis_result.get('error_message')
    }
