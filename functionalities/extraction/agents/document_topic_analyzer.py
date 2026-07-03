#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Document Topic Analyzer Agent

AI-powered component that analyzes document structure (TOC) and suggests
relevant extraction topics. Dynamically loads both standard topics from
StandardTopicRegistry and custom topics from session state.

This agent scores each topic's relevance to the document based ONLY on
the table of contents or section headings, providing confidence scores
and reasoning for each suggestion.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from haystack import component
from haystack.dataclasses import ChatMessage

from core.registries.topic_registry import StandardTopicRegistry
from functionalities.extraction.utils.json_parser import recover_json_from_response

logger = logging.getLogger(__name__)


@component
class DocumentTopicAnalyzer:
    """
    Haystack component that analyzes document TOC and suggests relevant topics.

    The analyzer dynamically loads available topics (standard + custom) and
    uses AI to score relevance based on document structure.
    """

    def __init__(self, generator: Any):
        """
        Initialize the document topic analyzer.

        Args:
            generator: Any Haystack ChatGenerator (MistralChatGenerator, etc.)
        """
        self.generator = generator
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load the document analysis prompt template."""
        prompt_file = Path(__file__).parent.parent / 'prompts' / 'document_analysis_prompt.md'

        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return self._get_default_template()

    def _get_default_template(self) -> str:
        """Return default prompt template if file not found."""
        return """You are analyzing a research document's table of contents to identify relevant extraction topics.

**Document TOC:**
{toc_text}

**Available Topics for Extraction:**
{topic_definitions}

**Your Task:**
For each topic listed above, determine relevance based ONLY on the TOC.
- Score 0.0-1.0 (0 = not relevant, 1.0 = highly relevant)
- Provide brief reasoning (which sections suggest this topic)

**Scoring Guidelines:**
- 0.9-1.0: Section directly named after topic or explicitly covers it
- 0.7-0.8: Strong indication - section clearly relates to topic
- 0.5-0.6: Moderate relevance - topic may be discussed
- 0.3-0.4: Weak relevance - tangential mention possible
- 0.0-0.2: No relevance - topic not indicated in TOC

**Output Format (JSON only):**
{{
  "topic_key": {{
    "score": 0.85,
    "reasoning": "Section 3.1 'Topic Name' directly covers this"
  }},
  ...
}}

**CRITICAL INSTRUCTIONS:**
- Return ONLY valid JSON (no text before or after)
- Score ALL topics, even if score is 0.0
- Base scores ONLY on TOC, not on general knowledge
- Be conservative - only high scores for explicit mentions"""

    @component.output_types(
        topic_suggestions=Dict[str, Any],
        analysis_status=str,
        error_message=Optional[str],
        topics_suggested=int
    )
    def run(
        self,
        toc_text: str,
        standard_topics: Optional[List[Any]] = None,
        custom_topics: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Analyze document TOC and suggest relevant topics.

        Args:
            toc_text: Formatted table of contents or section headings
            standard_topics: List of TopicDefinition objects (if None, loads from registry)
            custom_topics: List of custom topic dicts (if None, uses empty list)

        Returns:
            Dict containing:
                - topic_suggestions: Dict mapping topic_key to {score, reasoning}
                - analysis_status: "success" or "failed"
                - error_message: Error description if failed, None otherwise
                - topics_suggested: Number of topics with score > 0.5
        """
        try:
            if standard_topics is None:
                standard_topics = list(StandardTopicRegistry.TOPICS.values())

            if custom_topics is None:
                custom_topics = []

            topic_definitions = self._format_topics_for_prompt(standard_topics, custom_topics)

            prompt = self.prompt_template.format(
                toc_text=toc_text,
                topic_definitions=topic_definitions
            )

            messages = [ChatMessage.from_user(prompt)]
            result = self.generator.run(messages=messages)

            response_text = result["replies"][0].text.strip()
            topic_suggestions = self._parse_response(response_text)

            if not topic_suggestions:
                return {
                    "topic_suggestions": {},
                    "analysis_status": "failed",
                    "error_message": "AI returned empty or invalid response",
                    "topics_suggested": 0
                }

            topics_suggested = sum(1 for data in topic_suggestions.values() if data.get('score', 0) > 0.5)

            return {
                "topic_suggestions": topic_suggestions,
                "analysis_status": "success",
                "error_message": None,
                "topics_suggested": topics_suggested
            }

        except Exception as e:
            logger.error("Document topic analysis failed: %s", e, exc_info=True)
            return {
                "topic_suggestions": {},
                "analysis_status": "failed",
                "error_message": f"Analysis error: {str(e)}",
                "topics_suggested": 0
            }

    def _format_topics_for_prompt(
        self,
        standard_topics: List[Any],
        custom_topics: List[Dict[str, Any]]
    ) -> str:
        """
        Format topic definitions for inclusion in prompt.

        Args:
            standard_topics: List of TopicDefinition objects
            custom_topics: List of custom topic dicts

        Returns:
            Formatted string with all topic definitions
        """
        lines = []

        for topic in standard_topics:
            lines.append(f"- **{topic.key}**: {topic.detailed_description}")

        for custom_topic in custom_topics:
            topic_key = custom_topic.get('topic_key') or custom_topic.get('key', 'unknown')
            interpretation = custom_topic.get('interpretation', 'Custom research topic')
            lines.append(
                f"- **{topic_key}**: {interpretation}"
            )

        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse AI response into topic suggestions using shared json_parser utility."""
        try:
            suggestions, _ = recover_json_from_response(response_text)
            return {
                topic_key: {
                    "score": float(data["score"]),
                    "reasoning": data.get("reasoning", "No reasoning provided"),
                }
                for topic_key, data in suggestions.items()
                if isinstance(data, dict) and "score" in data
            }
        except Exception as e:
            logger.warning("Failed to parse topic suggestions: %s", e)
            return {}


def analyze_document_topics(
    toc_text: str,
    generator: Any,
    custom_topics: Optional[List[Dict[str, Any]]] = None
) -> Tuple[Dict[str, Any], str]:
    """
    Convenience function to analyze document topics.

    Args:
        toc_text: Formatted TOC or section headings
        generator: Haystack ChatGenerator
        custom_topics: Optional list of custom topic dicts

    Returns:
        Tuple of (topic_suggestions_dict, status)
    """
    analyzer = DocumentTopicAnalyzer(generator=generator)

    result = analyzer.run(
        toc_text=toc_text,
        custom_topics=custom_topics
    )

    return result['topic_suggestions'], result['analysis_status']
