# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Research Data Renderers Module
===============================

This module provides rendering functions specifically for research mode extracted data.
This data has a different format from categorized data:

Extracted Data Format (from research mode):
    {
        "field_name": {
            "value": <actual_data>,
            "reasoning": "AI explanation of where/how this was extracted"
        },
        ...
    }

Categorized Data Format (from database pipeline):
    {
        "field_name": [
            {
                "value": <actual_data>,
                "data_type": "string|dict|list|...",
                "source": "GBIF|AquaNIS|...",
                "categorization_method": "ai|direct_mapping"
            },
            ...
        ],
        ...
    }

Usage Example:
    ```python
    from frontend.ui_components.research_renderers import render_extracted_data_category

    import json
    with open('cache/extracted_data/.../extraction.json') as f:
        data = json.load(f)

    render_extracted_data_category(data['extracted_data'], data['metadata'])
    ```
"""

from typing import Any, Dict, List, Optional
from pathlib import Path
import json
import streamlit as st

# Import utilities from field_structure (shared between categorized and research renderers)
from frontend.ui_components.field_structure import humanize_field_name, SourceEntry

# Type alias for extracted field data
ExtractedFieldData = Dict[str, Any]  # Contains: value, reasoning


def render_extracted_field(field_name: str, field_data: ExtractedFieldData, source_title: str = "Research Source") -> None:
    """
    Render a single extracted field from research mode extraction.

    Handles the {value, reasoning} structure from extracted_data JSON files.

    Args:
        field_name: Raw field name (e.g., "adult_carapace_length_range")
        field_data: Dictionary with 'value' and 'reasoning' keys
        source_title: Title of the source (e.g., PDF filename or source name)

    Example:
        >>> field_data = {
        ...     "value": "Postorbital carapace length ranges from 16.8 to 51.5 mm",
        ...     "reasoning": "Page 9, Section 3.2 provides explicit measurements"
        ... }
        >>> render_extracted_field("adult_carapace_length_range", field_data, "animals-14-03558.pdf")
    """
    if not field_data or not isinstance(field_data, dict):
        return

    value = field_data.get('value')
    reasoning = field_data.get('reasoning')

    # Humanize field name
    human_name = humanize_field_name(field_name)

    # Create expandable section for each field
    with st.expander(f"**{human_name}**", expanded=False):
        # Display the value
        st.markdown("##### Value")
        if isinstance(value, str):
            st.markdown(value)
        elif isinstance(value, (list, dict)):
            st.json(value)
        else:
            st.write(value)

        # Display reasoning if available
        if reasoning:
            st.markdown("##### AI Reasoning")
            st.caption(reasoning)

        # Display source
        st.caption(f":material/description: Source: {source_title}")


def render_extracted_data_category(extracted_data: Dict[str, ExtractedFieldData], source_metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Render all extracted fields from a single extraction JSON file.

    Args:
        extracted_data: Dictionary of field_name -> {value, reasoning}
        source_metadata: Optional metadata about the extraction (source_title, research_topic, etc.)

    Example:
        >>> import json
        >>> with open('cache/extracted_data/.../extraction.json') as f:
        ...     data = json.load(f)
        >>> render_extracted_data_category(data['extracted_data'], data['metadata'])
    """
    if not extracted_data:
        st.info("No extracted data available.")
        return

    # Display metadata header if provided
    if source_metadata:
        source_title = source_metadata.get('source_title', 'Unknown Source')
        research_topic = source_metadata.get('research_topic', 'Unknown Topic')
        fields_count = source_metadata.get('fields_extracted', len(extracted_data))

        st.markdown(f"### :material/description: {source_title}")
        st.caption(f"**Topic:** {research_topic} | **Fields Extracted:** {fields_count}")
        st.markdown("---")
    else:
        source_title = "Research Source"

    # Render each field
    for field_name, field_data in extracted_data.items():
        render_extracted_field(field_name, field_data, source_title)


def render_all_extracted_data_for_topic(species_name: str, universal_id: str, research_topic: str) -> None:
    """
    Render all extracted data files for a specific research topic.

    Scans the extracted_data folder and displays all extractions for the given topic.

    Args:
        species_name: Scientific name of the species
        universal_id: Universal species identifier (e.g., "2227300_procambarus_clarkii")
        research_topic: Research topic name (e.g., "morphological_traits")

    Example:
        >>> render_all_extracted_data_for_topic("Procambarus clarkii", "2227300_procambarus_clarkii", "morphological_traits")
    """
    # Get extracted data directory (session-aware)
    from core.utils.cache_manager import get_extracted_data_dir
    extracted_dir = get_extracted_data_dir() / universal_id

    if not extracted_dir.exists():
        st.info(f"No extracted data found for {species_name}. Run research mode to extract information from sources.")
        return

    # Find all extraction files for this topic (searches per-source subdirectories)
    topic_underscore = research_topic.lower().replace(' ', '_').replace('&', '').replace('__', '_')
    extraction_files = list(extracted_dir.glob(f'**/{topic_underscore}_*_extraction.json'))

    if not extraction_files:
        st.info(f"No extracted data found for topic: {research_topic}")
        return

    st.markdown(f"### :material/science: Extracted Data for {research_topic.replace('_', ' ').title()}")
    st.caption(f"Found {len(extraction_files)} extraction(s)")
    st.markdown("---")

    # Render each extraction file
    for extraction_file in sorted(extraction_files, key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(extraction_file, 'r', encoding='utf-8') as f:
                extraction_data = json.load(f)

            metadata = extraction_data.get('metadata', {})
            extracted_data = extraction_data.get('extracted_data', {})

            # Render with collapsible container per source
            with st.container():
                render_extracted_data_category(extracted_data, metadata)
                st.markdown("---")

        except Exception as e:
            st.error(f"Error loading {extraction_file.name}: {e}")


def convert_extracted_to_categorized_format(extracted_data: Dict[str, ExtractedFieldData], source_metadata: Dict[str, Any]) -> Dict[str, List[SourceEntry]]:
    """
    Convert extracted data format to categorized data format for use with render_field.

    Transforms {field: {value, reasoning}} -> {field: [{value, source, data_type, ...}]}

    This is useful when you want to render research-extracted data using the
    standard categorized data renderers from field_renderers.py.

    Args:
        extracted_data: Dictionary of field_name -> {value, reasoning}
        source_metadata: Metadata about the extraction (source_title, source_domain, etc.)

    Returns:
        Dictionary in categorized format compatible with render_field

    Example:
        >>> from frontend.ui_components.field_renderers import render_field
        >>> extracted = {"species_name": {"value": "Procambarus clarkii", "reasoning": "..."}}
        >>> metadata = {"source_title": "paper.pdf", "source_domain": "Manual Upload"}
        >>> categorized = convert_extracted_to_categorized_format(extracted, metadata)
        >>> render_field("species_name", categorized["species_name"])
    """
    categorized = {}

    source_title = source_metadata.get('source_title', 'Research Source')
    source_domain = source_metadata.get('source_domain', 'Research')

    for field_name, field_data in extracted_data.items():
        if not isinstance(field_data, dict):
            continue

        value = field_data.get('value')
        reasoning = field_data.get('reasoning', '')

        # Detect data type
        if value is None:
            data_type = "null"
        elif isinstance(value, bool):
            data_type = "boolean"
        elif isinstance(value, (int, float)):
            data_type = "number"
        elif isinstance(value, str):
            data_type = "string"
        elif isinstance(value, list):
            data_type = "list"
        elif isinstance(value, dict):
            data_type = "dict"
        else:
            data_type = "string"

        # Create categorized format entry
        categorized[field_name] = [
            {
                "value": value,
                "data_type": data_type,
                "source": source_domain,
                "categorization_method": "ai",
                "ai_reasoning": reasoning,
                "original_field": field_name,
                "source_title": source_title,
                "is_research_data": True
            }
        ]

    return categorized
