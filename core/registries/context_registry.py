# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Context Prompt Registry
========================

Centralized registry for contextual extraction prompts that run on every source paper.
These extract cross-cutting metadata that provides a quick-scan summary card for paper
selection — allowing researchers to judge relevance without reading the full paper.

Unlike StandardTopicRegistry topics, context prompts are:
- Not user-selectable (always run automatically)
- Not tied to search terms, dashboard cards, or categorization

A single context prompt ('paper_summary') replaces the previous three-prompt approach
(geographic_context, population_context, study_methodology_context) which exposed ~70
branching fields and caused resolver drift. The current fixed 7-field schema is a
management triage card:
paper_type, key_finding, management_relevance, data_or_specimen_origin,
study_scale, study_period, publication_venue.
"""

from typing import Dict, List, Any


class ContextDefinition:
    """Definition for a single contextual extraction prompt."""

    def __init__(
        self,
        key: str,
        display_name: str,
        description: str,
        prompt_file: str
    ):
        """
        Args:
            key: Internal identifier (e.g., 'paper_summary')
            display_name: Human-readable name (e.g., 'Paper Summary')
            description: What this context prompt extracts
            prompt_file: Filename in context_prompts/ directory
        """
        self.key = key
        self.display_name = display_name
        self.description = description
        self.prompt_file = prompt_file

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            'key': self.key,
            'display_name': self.display_name,
            'description': self.description,
            'prompt_file': self.prompt_file
        }


class ContextPromptRegistry:
    """
    Registry of contextual extraction prompts that always run on every source paper.

    A single 'paper_summary' prompt runs once per source and extracts a fixed
    7-field management triage card (paper_type, key_finding, management_relevance,
    data_or_specimen_origin, study_scale, study_period, publication_venue) to
    support rapid paper selection by IAS researchers and managers. Results are
    stored separately from topic extractions with the prefix 'context_' in the
    filename.
    """

    CONTEXTS = {
        'paper_summary': ContextDefinition(
            key='paper_summary',
            display_name='Paper Summary',
            description='Management triage card: paper type, key finding, '
                        'management relevance, data/specimen origin (water-body-first), '
                        'study scale, study period, and publication venue',
            prompt_file='paper_summary_prompt.md'
        ),
    }

    @classmethod
    def get_all_context_keys(cls) -> List[str]:
        """Return all context prompt keys."""
        return list(cls.CONTEXTS.keys())

    @classmethod
    def get_prompt_file_mapping(cls) -> Dict[str, str]:
        """Return mapping of context key to prompt filename."""
        return {key: ctx.prompt_file for key, ctx in cls.CONTEXTS.items()}

    @classmethod
    def get_context_definition(cls, key: str) -> ContextDefinition:
        """Get a specific context definition by key."""
        if key not in cls.CONTEXTS:
            raise ValueError(
                f"Unknown context key '{key}'. "
                f"Available: {list(cls.CONTEXTS.keys())}"
            )
        return cls.CONTEXTS[key]

    @classmethod
    def is_context_key(cls, key: str) -> bool:
        """Check if a key belongs to the context registry."""
        return key in cls.CONTEXTS

    @classmethod
    def get_all_definitions(cls) -> Dict[str, Dict[str, Any]]:
        """Return all context definitions as dictionaries."""
        return {key: ctx.to_dict() for key, ctx in cls.CONTEXTS.items()}
