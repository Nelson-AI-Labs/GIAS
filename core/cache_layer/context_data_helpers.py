# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Context Data Helpers
====================

Functions for loading and working with contextual extraction data.
Context extractions capture a 7-field management triage card (paper_type,
key_finding, management_relevance, data_or_specimen_origin, study_scale,
study_period, publication_venue) to support rapid paper selection by IAS
researchers and managers.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional
from core.utils.cache_manager import get_extracted_data_dir


def load_context_data_by_id(universal_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Load all context extraction files for a species, grouped by source.

    Returns a dictionary structure like:
    {
        "source_id_1": [
            {
                "context_type": "paper_summary",
                "extracted_data": {...},
                "metadata": {...}
            }
        ],
        "source_id_2": [...]
    }

    Args:
        universal_id: Universal species ID

    Returns:
        Dict mapping source IDs to lists of context extraction results
    """
    extracted_dir = get_extracted_data_dir() / universal_id

    if not extracted_dir.exists():
        return {}

    context_by_source = {}

    # Search recursively through per-source subdirectories for context files
    for file_path in extracted_dir.glob('**/context_*_extraction.json'):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            metadata = data.get('metadata', {})

            # Verify this is actually a context file
            if metadata.get('extraction_type') != 'context':
                continue

            source_id = metadata.get('source_id', 'unknown')
            context_type = metadata.get('research_topic', 'unknown')
            extracted_data = data.get('extracted_data', {})

            # Initialize source entry if needed
            if source_id not in context_by_source:
                context_by_source[source_id] = []

            # Add this context extraction to the source's list
            context_by_source[source_id].append({
                'context_type': context_type,
                'extracted_data': extracted_data,
                'metadata': metadata
            })

        except Exception as e:
            print(f"Error reading context file {file_path}: {e}")
            continue

    return context_by_source


def get_context_display_name(context_type: str) -> str:
    """
    Get a human-readable display name for a context type.

    Args:
        context_type: Context key (e.g., "paper_summary")

    Returns:
        Display name (e.g., "Paper Summary")
    """
    from core.registries.context_registry import ContextPromptRegistry

    try:
        context_def = ContextPromptRegistry.get_context_definition(context_type)
        return context_def.display_name
    except ValueError:
        # Fallback: convert underscore to title case
        return context_type.replace('_', ' ').title()


def get_context_icon(context_type: str) -> str:
    """
    Get an emoji icon for a context type.

    Args:
        context_type: Context key (e.g., "paper_summary")

    Returns:
        Emoji string
    """
    icon_mapping = {
        'paper_summary': '📋',
    }

    return icon_mapping.get(context_type, '📄')
