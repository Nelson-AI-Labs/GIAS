# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Field Renderers Module
======================

This module provides dynamic rendering functions for categorized JSON data fields.
Each field in the categorized data follows a pattern where it contains an array of
source-attributed values, each wrapped with metadata.

Structure:
    field_name: [
        {
            "value": <actual_data>,
            "data_type": "string" | "dict" | "list" | "boolean" | "null",
            "source": "AquaNIS" | "GBIF" | "EASIN" | etc.,
            "categorization_method": "ai" | "direct_mapping",
            "ai_reasoning": "...",  # optional
            "original_field": "..."  # optional
        },
        ...
    ]

This module is organized into submodules for better maintainability:
- field_structure.py: Structure detection and utility functions
- source_attribution.py: Source badge rendering

Usage Example:
    ```python
    from frontend.ui_components.field_renderers import render_field

    category_data = {
        "species_name": [
            {
                "value": "Procambarus clarkii",
                "data_type": "string",
                "source": "AquaNIS",
                "categorization_method": "ai"
            }
        ],
        "taxonomy": [
            {
                "value": {"kingdom": "Animalia", "phylum": "Arthropoda"},
                "data_type": "dict",
                "source": "GBIF",
                "categorization_method": "direct_mapping"
            }
        ]
    }

    for field_name, field_values in category_data.items():
        render_field(field_name, field_values)
    ```
"""

from typing import Any, Dict, List, Optional
import streamlit as st

# Import from submodules
from frontend.ui_components.field_structure import (
    FieldDataType,
    StructureType,
    SourceEntry,
    extract_language_text,
    humanize_field_name,
    extract_sources,
    detect_field_structure,
    format_dict_as_text,
    format_list_item,
)

from frontend.ui_components.source_attribution import render_source_badge
from frontend.utils.icons import glyph_svg

# Type alias for extracted field data
ExtractedFieldData = Dict[str, Any]  # Contains: value, reasoning

# Note: The following utility functions are now imported from field_structure.py:
# - extract_language_text
# - humanize_field_name
# - extract_sources
# - detect_field_structure
# - format_dict_as_text
# - format_list_item
#
# And render_source_badge is imported from source_attribution.py

# ============================================================================
# VALUE RENDERERS
# ============================================================================


def render_simple_value(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render simple value types (strings, numbers).

    Displays each source's value with attribution. If multiple sources provide
    different values, they are all shown with their respective source badges.

    Args:
        field_name: Human-readable field name
        field_data: List of source-attributed values

    Examples:
        >>> data = [
        ...     {"value": "Procambarus clarkii", "source": "AquaNIS",
        ...      "categorization_method": "ai"}
        ... ]
        >>> render_simple_value("Species Name", data)
        # Displays: "Species Name: Procambarus clarkii [AquaNIS • AI]"
    """
    st.markdown(f"**{field_name}:**")

    # Group by value to detect conflicts
    value_groups: Dict[Any, List[SourceEntry]] = {}
    for entry in field_data:
        value = entry.get("value")
        if value is not None:
            if value not in value_groups:
                value_groups[value] = []
            value_groups[value].append(entry)

    if not value_groups:
        st.markdown("_No data available_")
        return

    # Show each unique value with its sources
    for value, entries in value_groups.items():
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"• {value}")
        with col2:
            for entry in entries:
                render_source_badge(
                    entry.get("source", "Unknown"),
                    entry.get("categorization_method", "unknown"),
                    entry.get("is_research_data", False),
                    entry.get("query_names")
                )

    # Show conflict warning if multiple different values
    if len(value_groups) > 1:
        st.warning("Conflicting values from different sources", icon=":material/warning:")


def render_boolean_value(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render boolean values with visual indicators.

    Args:
        field_name: Human-readable field name
        field_data: List of source-attributed boolean values

    Examples:
        >>> data = [{"value": True, "source": "GBIF", "data_type": "boolean"}]
        >>> render_boolean_value("Is Invasive", data)
        # Displays: "Is Invasive: ✓ Yes [GBIF]"
    """
    st.markdown(f"**{field_name}:**")

    for entry in field_data:
        value = entry.get("value")
        if value is None:
            continue

        icon = glyph_svg("check" if value else "close", size=15)
        color = "green" if value else "red"
        text = "Yes" if value else "No"

        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(
                f'<span style="color: {color}; font-weight: bold;">{icon} {text}</span>',
                unsafe_allow_html=True
            )
        with col2:
            render_source_badge(
                entry.get("source", "Unknown"),
                entry.get("categorization_method", "unknown"),
                entry.get("is_research_data", False),
                entry.get("query_names")
            )


def render_null_value(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render null/missing values gracefully.

    Args:
        field_name: Human-readable field name
        field_data: List of source entries (all null)

    Examples:
        >>> data = [{"value": null, "source": "AquaNIS"}]
        >>> render_null_value("Description", data)
        # Displays: "Description: No data available"
    """
    st.markdown(f"**{field_name}:** _No data available_")


def render_dict_value(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render dictionary values (like taxonomy hierarchies).

    Displays nested key-value pairs in a structured format. Handles multiple
    sources by showing each dict separately with source attribution.

    Special handling: If the dict has a single "data" key containing a list,
    unwraps and routes to the list renderer instead.

    Args:
        field_name: Human-readable field name
        field_data: List of source-attributed dict values

    Examples:
        >>> data = [{
        ...     "value": {"kingdom": "Animalia", "phylum": "Arthropoda"},
        ...     "source": "GBIF",
        ...     "data_type": "dict"
        ... }]
        >>> render_dict_value("Taxonomy", data)
        # Displays structured taxonomy with source badge

        >>> # Nested data pattern (gets unwrapped)
        >>> data = [{
        ...     "value": {"data": [{"AquaNISID": 2153, ...}, ...]},
        ...     "source": "AquaNIS"
        ... }]
        >>> render_dict_value("Records", data)
        # Unwraps and displays as list of records
    """
    st.markdown(f"**{field_name}:**")

    for entry in field_data:
        value = entry.get("value")
        if not isinstance(value, dict) or not value:
            continue

        # PATTERN DETECTION: Check for nested data wrapper
        # Pattern: {"data": [list of items]}
        if (len(value) == 1 and
            "data" in value and
            isinstance(value["data"], list) and
            len(value["data"]) > 0):

            # Unwrap the nested list and route to list renderer
            unwrapped_list = value["data"]

            # Source badge (shown before unwrapped content)
            render_source_badge(
                entry.get("source", "Unknown"),
                entry.get("categorization_method", "unknown"),
                entry.get("is_research_data", False),
                entry.get("query_names")
            )

            # Detect if it's a list of dicts or simple values
            if isinstance(unwrapped_list[0], dict):
                # Route to list_of_dicts renderer
                display_type = detect_dict_display_type(unwrapped_list)

                if display_type == "tabular_records":
                    _render_tabular_records(unwrapped_list, entry.get("source", "Unknown"))
                elif display_type == "occurrence_records":
                    _render_occurrence_records(unwrapped_list, entry.get("source", "Unknown"))
                else:  # simple_descriptive
                    _render_simple_descriptive_dicts(unwrapped_list)
            else:
                # Route to simple list renderer
                for item in unwrapped_list:
                    st.markdown(f"  • {item}")

            continue  # Skip normal dict rendering

        # NORMAL DICT RENDERING (for flat key-value pairs)
        # Source badge
        render_source_badge(
            entry.get("source", "Unknown"),
            entry.get("categorization_method", "unknown"),
            query_names=entry.get("query_names")
        )

        # Render dict items as nested list
        for key, val in value.items():
            humanized_key = humanize_field_name(key)
            # Extract language-coded text if applicable
            display_value = extract_language_text(val)
            st.markdown(f"  • **{humanized_key}:** {display_value}")


def detect_dict_display_type(list_of_dicts: List[Dict]) -> str:
    """
    Detect the most appropriate display type for a list of dictionaries.

    Heuristics:
    - Tabular records: >8 keys, structured data (IDs, dates, regions)
    - Occurrence records: Has location fields (lat/long, country, coordinates)
    - Simple descriptive: <5 keys, has description/narrative fields

    Args:
        list_of_dicts: List of dictionary items to analyze

    Returns:
        "tabular_records", "occurrence_records", or "simple_descriptive"
    """
    if not list_of_dicts or not isinstance(list_of_dicts[0], dict):
        return "simple_descriptive"

    first_dict = list_of_dicts[0]
    keys = set(k.lower() for k in first_dict.keys())
    num_keys = len(keys)

    # Check for occurrence/location data
    location_indicators = {
        'decimallat', 'decimallong', 'latitude', 'longitude', 'coordinates',
        'countrycode', 'stateprovince', 'locality', 'eventdate', 'basisofrecord',
        'occurrenceid', 'year', 'month', 'day'
    }
    if len(keys & location_indicators) >= 3:
        return "occurrence_records"

    # Check for tabular/database records (many structured fields)
    tabular_indicators = {
        'id', 'aquanisid', 'recipientregion', 'recipientcountry', 'datefrom',
        'dateto', 'status', 'introduction', 'donor', 'vector', 'category'
    }
    if num_keys > 8 or len(keys & tabular_indicators) >= 3:
        return "tabular_records"

    # Default to simple descriptive
    return "simple_descriptive"


def _render_tabular_records(
    records: List[Dict],
    source: str,
    preview_limit: int = None
) -> None:
    """
    Render tabular/database records with key fields highlighted.

    Shows all records directly without expandable dropdown.
    Prioritizes: Country, Region, Date, Status fields.
    """
    # Priority fields to show (in order)
    priority_fields = [
        'recipientcountry', 'recipientregion', 'country', 'region',
        'datefrom', 'dateto', 'date', 'year',
        'status', 'introduction', 'category'
    ]

    def format_record(record: Dict) -> str:
        """Format a single record as a compact string."""
        parts = []

        # Extract priority fields first
        record_lower = {k.lower(): (k, v) for k, v in record.items()}

        for priority_key in priority_fields:
            if priority_key in record_lower:
                original_key, value = record_lower[priority_key]
                if value and str(value).strip():
                    # Format dates nicely
                    if 'date' in priority_key or priority_key in ('datefrom', 'dateto', 'year'):
                        parts.append(f"**{value}**")
                    else:
                        parts.append(f"{value}")

        return " • ".join(parts) if parts else "No key information"

    # Show all records
    for i, record in enumerate(records, 1):
        formatted = format_record(record)
        st.markdown(f":material/location_on: {formatted}")


def _render_occurrence_records(
    occurrences: List[Dict],
    source: str,
    preview_limit: int = None
) -> None:
    """
    Render occurrence/location records with geographic emphasis.

    Shows all records directly without expandable dropdown.
    Prioritizes: Country, State/Province, Coordinates, Date, Basis.
    """
    def format_occurrence(occ: Dict) -> tuple:
        """Extract key fields from occurrence record."""
        occ_lower = {k.lower(): v for k, v in occ.items()}

        # Location
        location_parts = []
        if 'countrycode' in occ_lower or 'country' in occ_lower:
            country = occ_lower.get('countrycode') or occ_lower.get('country', '')
            if country:
                location_parts.append(country)

        if 'stateprovince' in occ_lower:
            state = occ_lower.get('stateprovince', '')
            if state:
                location_parts.append(state)

        if 'locality' in occ_lower and len(location_parts) < 2:
            locality = occ_lower.get('locality', '')
            if locality and len(str(locality)) < 30:
                location_parts.append(locality)

        location = ", ".join(location_parts) if location_parts else "Unknown location"

        # Date
        date_str = None
        if 'eventdate' in occ_lower:
            date_str = occ_lower['eventdate']
        elif 'year' in occ_lower:
            year = occ_lower['year']
            month = occ_lower.get('month', '')
            day = occ_lower.get('day', '')
            date_parts = [str(year)]
            if month:
                date_parts.append(str(month).zfill(2))
            if day:
                date_parts.append(str(day).zfill(2))
            date_str = "-".join(date_parts)

        # Basis of record
        basis = occ_lower.get('basisofrecord', '')

        return location, date_str, basis

    # Show all occurrences
    for i, occ in enumerate(occurrences, 1):
        location, date, basis = format_occurrence(occ)

        # Build display string
        display_parts = [f":material/public: **{location}**"]
        if date:
            display_parts.append(f"({date})")

        st.markdown(" ".join(display_parts))

        if basis:
            st.markdown(f"   _Basis: {basis}_")


def _render_simple_descriptive_dicts(items: List[Dict]) -> None:
    """
    Render simple descriptive dictionaries as bullet list.

    For items with few keys and descriptive content.
    Applies language extraction to values.
    """
    for i, item in enumerate(items, 1):
        if isinstance(item, dict):
            # Create a compact representation
            item_parts = []
            for k, v in item.items():
                if v:  # Only show non-empty values
                    # Extract language-coded text if applicable
                    display_value = extract_language_text(v)
                    item_parts.append(f"{humanize_field_name(k)}: {display_value}")

            if item_parts:
                st.markdown(f"  {i}. {' | '.join(item_parts)}")
        else:
            st.markdown(f"  {i}. {item}")


def render_list_of_dicts(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render lists of dictionaries with intelligent display type detection.

    This function analyzes the structure of dict items and routes to the
    appropriate specialized renderer:
    - Tabular records (database exports): Compact cards with key fields
    - Occurrence records (GBIF data): Location-focused display
    - Simple descriptive: Bullet list format

    Special handling: If the list contains a single dict with a "data" key,
    unwraps the nested structure first.

    Args:
        field_name: Human-readable field name
        field_data: List of source-attributed list values

    Examples:
        >>> # Tabular data (AquaNIS records)
        >>> data = [{
        ...     "value": [
        ...         {"AquaNISID": 2153, "RecipientCountry": "Italy", "DateFrom": 2007},
        ...         ...
        ...     ],
        ...     "source": "AquaNIS"
        ... }]
        >>> render_list_of_dicts("Distribution Records", data)

        >>> # Nested wrapper pattern (gets unwrapped)
        >>> data = [{
        ...     "value": [{"data": [{"AquaNISID": 2153, ...}, ...]}],
        ...     "source": "AquaNIS"
        ... }]
        >>> render_list_of_dicts("Introduction Records", data)
        # Unwraps [{"data": [...]}] to access the actual records
    """
    st.markdown(f"**{field_name}:**")

    for entry in field_data:
        value = entry.get("value")
        if not isinstance(value, list) or not value:
            continue

        source = entry.get("source", "Unknown")

        # Source badge
        render_source_badge(
            source,
            entry.get("categorization_method", "unknown"),
            query_names=entry.get("query_names")
        )

        # PATTERN DETECTION: Check for nested data wrapper
        # Pattern: [{"data": [actual items]}] - unwrap to get actual items
        if (len(value) == 1 and
            isinstance(value[0], dict) and
            len(value[0]) == 1 and
            "data" in value[0] and
            isinstance(value[0]["data"], list)):

            # Unwrap the nested structure
            value = value[0]["data"]

        # Detect display type
        display_type = detect_dict_display_type(value)

        # Route to appropriate renderer
        if display_type == "tabular_records":
            _render_tabular_records(value, source)
        elif display_type == "occurrence_records":
            _render_occurrence_records(value, source)
        else:  # simple_descriptive
            _render_simple_descriptive_dicts(value)


def render_list_of_strings(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render lists of simple values (strings, numbers).

    Args:
        field_name: Human-readable field name
        field_data: List of source-attributed list values

    Examples:
        >>> data = [{
        ...     "value": ["Europe", "Asia", "North America"],
        ...     "source": "GBIF",
        ...     "data_type": "list"
        ... }]
        >>> render_list_of_strings("Regions", data)
        # Displays: bullet list of regions
    """
    st.markdown(f"**{field_name}:**")

    for entry in field_data:
        value = entry.get("value")
        if not isinstance(value, list) or not value:
            continue

        # Source badge
        render_source_badge(
            entry.get("source", "Unknown"),
            entry.get("categorization_method", "unknown"),
            query_names=entry.get("query_names")
        )

        # Render as bullet list
        for item in value:
            st.markdown(f"  • {item}")


def render_nested_complex(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Render complex nested structures (dicts containing lists/nested dicts).

    Handles deeply nested data by recursively rendering sub-structures.

    Args:
        field_name: Human-readable field name
        field_data: List of source-attributed complex values

    Examples:
        >>> data = [{
        ...     "value": {
        ...         "data": [
        ...             {"Species": "P. clarkii", "AphiaID": 465540}
        ...         ],
        ...         "meta": {"total": 1}
        ...     },
        ...     "source": "WoRMS",
        ...     "data_type": "dict"
        ... }]
        >>> render_nested_complex("Species Data", data)
    """
    st.markdown(f"**{field_name}:**")

    for entry in field_data:
        value = entry.get("value")
        if not isinstance(value, dict):
            continue

        # Source badge
        render_source_badge(
            entry.get("source", "Unknown"),
            entry.get("categorization_method", "unknown"),
            query_names=entry.get("query_names")
        )

        # Use expander for complex nested data
        with st.expander("View detailed data", expanded=False):
            _render_nested_dict(value, level=0)


def _render_nested_dict(data: Dict[str, Any], level: int = 0) -> None:
    """
    Helper function to recursively render nested dictionaries.

    Applies language extraction to values.

    Args:
        data: Dictionary to render
        level: Current nesting level (for indentation)
    """
    indent = "  " * level

    for key, value in data.items():
        humanized_key = humanize_field_name(key)

        if isinstance(value, dict):
            st.markdown(f"{indent}**{humanized_key}:**")
            _render_nested_dict(value, level + 1)
        elif isinstance(value, list):
            st.markdown(f"{indent}**{humanized_key}:**")
            for i, item in enumerate(value, 1):
                if isinstance(item, dict):
                    st.markdown(f"{indent}  {i}.")
                    _render_nested_dict(item, level + 2)
                else:
                    # Extract language-coded text if applicable
                    display_value = extract_language_text(item)
                    st.markdown(f"{indent}  • {display_value}")
        else:
            # Extract language-coded text if applicable
            display_value = extract_language_text(value)
            st.markdown(f"{indent}• **{humanized_key}:** {display_value}")


def render_field(field_name: str, field_data: List[SourceEntry]) -> None:
    """
    Main entry point for rendering any field type.

    This function:
    1. Detects the structure type of the field data
    2. Humanizes the field name
    3. Routes to the appropriate specialized renderer
    4. Handles edge cases (empty data, errors)

    Args:
        field_name: Raw field name (e.g., "species_name")
        field_data: List of source-attributed value wrappers

    Examples:
        >>> # Simple string value
        >>> render_field("species_name", [
        ...     {"value": "Procambarus clarkii", "source": "AquaNIS", "data_type": "string"}
        ... ])

        >>> # Dictionary value
        >>> render_field("taxonomy", [
        ...     {"value": {"kingdom": "Animalia"}, "source": "GBIF", "data_type": "dict"}
        ... ])

        >>> # List of dicts
        >>> render_field("common_names", [
        ...     {"value": [{"name": "Crayfish"}], "source": "EASIN", "data_type": "list"}
        ... ])
    """
    if not field_data:
        return

    # Humanize field name
    human_name = humanize_field_name(field_name)

    # Detect structure
    structure_type = detect_field_structure(field_data)

    # Route to appropriate renderer
    renderers = {
        "simple_value": render_simple_value,
        "boolean": render_boolean_value,
        "null": render_null_value,
        "dict_value": render_dict_value,
        "list_of_dicts": render_list_of_dicts,
        "list_of_strings": render_list_of_strings,
        "nested_complex": render_nested_complex
    }

    renderer = renderers.get(structure_type, render_simple_value)

    try:
        renderer(human_name, field_data)
    except Exception as e:
        st.error(f"Error rendering {human_name}: {str(e)}")
        # Fallback: show raw data
        with st.expander("View raw data", expanded=False):
            st.json(field_data)


def render_category_section(
    category_name: str,
    category_data: Dict[str, List[SourceEntry]],
    icon: str = ":material/insights:"
) -> None:
    """
    Render an entire category section with all its fields.

    This is a convenience function for rendering a complete category,
    including a header and all fields within that category.

    Args:
        category_name: Name of the category (e.g., "impacts", "taxonomy")
        category_data: Dictionary of field_name -> field_data mappings
        icon: Material Symbols token for the category header (e.g. ":material/eco:")

    Examples:
        >>> category_data = {
        ...     "species_name": [{"value": "P. clarkii", "source": "GBIF"}],
        ...     "authority": [{"value": "(Girard, 1852)", "source": "GBIF"}]
        ... }
        >>> render_category_section("Basic Information", category_data, ":material/description:")
    """
    st.subheader(f"{icon} {humanize_field_name(category_name)}")

    if not category_data:
        st.info("No data available for this category")
        return

    # Render each field
    for field_name, field_values in category_data.items():
        render_field(field_name, field_values)
        st.markdown("---")  # Separator between fields


# ============================================================================
# RESEARCH DATA RENDERERS (Re-exported for backward compatibility)
# ============================================================================
# Research data renderers have been moved to research_renderers.py since they
# handle a different data format (extracted data) from categorized data.
# They are re-exported here for backward compatibility.

from frontend.ui_components.research_renderers import (
    render_extracted_field,
    render_extracted_data_category,
    render_all_extracted_data_for_topic,
    convert_extracted_to_categorized_format,
)
