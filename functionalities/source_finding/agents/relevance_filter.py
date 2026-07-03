#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Semantic Scholar Relevance Filter

Post-fetch LLM filter that scores each result against the actual research
topic + species intent, catching papers where the species is only mentioned
in passing (species lists, gut content tables, co-occurrence counts, etc.).

Marks low-scoring results with is_low_confidence=True rather than discarding
them — they still appear in the source list but are visually flagged.
"""

import json
import logging
from typing import List, Dict, Any, Optional

from haystack.dataclasses import ChatMessage

from core.utils.generator_factory import create_generator
from functionalities.extraction.utils.json_parser import recover_json_from_response

logger = logging.getLogger(__name__)

_generator = create_generator("relevance_filter")

_PROMPT_TEMPLATE = """\
You are a research paper relevance classifier.

Species under research: {species_name}
Research topic: {topic_name}
Topic description: {topic_description}
Key concepts included in this topic: {key_concepts}

Paper title: {title}
Paper abstract: {abstract}

Is this paper PRIMARILY about the research topic above for {species_name}?

Rules:
- The species must be the main study subject (not just mentioned in passing, listed in a table, or found in gut content)
- The research topic or any of its key concepts must be central to the paper (not a side note)
- Comparative studies where {species_name} is one of the main subjects: RELEVANT
- Papers where {species_name} appears only in species lists or incidentally: NOT RELEVANT

Respond with ONLY valid JSON, no other text:
{{"relevant": true}}"""

_PROMPT_TEMPLATE_MANAGEMENT = """\
You are a research paper relevance classifier.

Species under research: {species_name}
Research topic: {topic_name}
Topic description: {topic_description}
Key concepts included in this topic: {key_concepts}

Paper title: {title}
Paper abstract: {abstract}

Is this paper PRIMARILY about the research topic above for {species_name}?

Rules:
- The species must be the main study subject (not just mentioned in passing, listed in a table, or found in gut content)
- The research topic or any of its key concepts must be central to the paper (not a side note)
- Comparative studies where {species_name} is one of the main subjects: RELEVANT
- Papers where {species_name} appears only in species lists or incidentally: NOT RELEVANT

This is a management-core topic. Also assess:
Is this paper **management-applicable** — does it contain findings that could directly inform a management decision?

Positive signals: explicit management objectives, field-scale intervention, cost or feasibility data, surveillance protocol, "management implications" section, measured intervention outcomes.

Not management-applicable: papers describing ecology or mechanisms without addressing how findings would be used in practice.

Respond with ONLY valid JSON, no other text:
{{"relevant": true, "management_applicable": true}}"""


def score_relevance(
    results: List[Dict[str, Any]],
    species_name: str,
    research_topic: str,
) -> List[Dict[str, Any]]:
    """
    Score each result for relevance to species + research topic.

    Looks up the topic in StandardTopicRegistry to get a rich description
    for the judge. Falls back to the raw topic key if not found (e.g. custom topics).

    Reads _abstract from each result (set by semantic_scholar_search_json),
    calls Mistral once per result, and sets is_low_confidence=True on
    results where relevant==false.

    Strips _abstract from all results before returning regardless of outcome.
    """
    if _generator is None:
        logger.warning("Relevance filter: generator not available, skipping scoring")
        for r in results:
            r.pop("_abstract", None)
        return results

    topic_name, topic_description, key_concepts, priority_tier = _resolve_topic(research_topic)
    is_management_core = priority_tier == "management_core"

    for result in results:
        abstract = result.pop("_abstract", "") or ""
        title = result.get("title", "")

        if not title and not abstract:
            continue

        scored = _score_single(
            title, abstract, species_name, topic_name, topic_description,
            key_concepts, is_management_core=is_management_core
        )
        if scored is None or not scored.get("relevant", True):
            result["is_low_confidence"] = True
        if scored and "management_applicable" in scored:
            result["management_applicable"] = scored["management_applicable"]

    return results


def _resolve_topic(research_topic: str):
    """
    Look up the topic in StandardTopicRegistry and return
    (display_name, description, key_concepts_str, priority_tier).

    For management-core topics, returns detailed_description so the filter
    receives richer management-applicability context. Ecology-support topics
    use short_description. Falls back gracefully for custom topics or unknown keys.
    """
    try:
        from core.registries.topic_registry import StandardTopicRegistry
        topic_def = StandardTopicRegistry.get_topic(research_topic)
        if topic_def:
            concepts = topic_def.key_concepts or []
            tier = getattr(topic_def, "priority_tier", "ecology_support")
            if tier in ("management_core", "ecology_management_relevant"):
                description = topic_def.detailed_description or topic_def.short_description
            else:
                description = topic_def.short_description or topic_def.display_name
            return (
                topic_def.display_name,
                description,
                ", ".join(concepts) if concepts else topic_def.display_name,
                tier,
            )
    except Exception:
        pass

    # Fallback: humanise the raw key
    display = research_topic.replace("_", " ").title()
    return display, display, display, "ecology_support"


def _score_single(
    title: str,
    abstract: str,
    species_name: str,
    topic_name: str,
    topic_description: str,
    key_concepts: str,
    is_management_core: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Call Mistral for a single paper.

    Returns a dict with at minimum {"relevant": bool}. For management-core
    topics also includes {"management_applicable": bool}.
    Returns None on failure — callers treat None as low-confidence.
    """
    template = _PROMPT_TEMPLATE_MANAGEMENT if is_management_core else _PROMPT_TEMPLATE
    prompt = template.format(
        species_name=species_name,
        topic_name=topic_name,
        topic_description=topic_description,
        key_concepts=key_concepts,
        title=title,
        abstract=abstract or "(no abstract available)",
    )

    try:
        messages = [ChatMessage.from_user(prompt)]
        response = _generator.run(messages=messages)
        content = response["replies"][0].text

        parsed, _ = recover_json_from_response(content)
        result: Dict[str, Any] = {"relevant": bool(parsed.get("relevant", True))}
        if is_management_core and "management_applicable" in parsed:
            result["management_applicable"] = bool(parsed["management_applicable"])
        return result

    except Exception as e:
        logger.debug("Relevance scoring failed for '%s': %s", title[:60], e)
        return None
