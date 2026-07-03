# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Field Structure Module
======================

Provides utility functions for detecting and analyzing field data structures
in the categorized JSON data format.

This module handles:
- Field structure detection (simple values, dicts, lists, etc.)
- Language text extraction from language-coded dictionaries
- Field name humanization
- Source extraction from field data
"""

from typing import Any, Dict, List, Literal

# Type definitions
FieldDataType = Literal["string", "dict", "list", "boolean", "null", "number"]
StructureType = Literal[
    "simple_value",
    "dict_value",
    "list_of_dicts",
    "list_of_strings",
    "boolean",
    "null",
    "nested_complex"
]

SourceEntry = Dict[str, Any]  # Contains: value, data_type, source, categorization_method, etc.


def extract_language_text(value: Any) -> Any:
    """
    Extract text from language-coded dictionaries, or return value as-is.

    Language-coded dicts have format: {'en': 'text'} or {'eng': 'text'}
    This function extracts the text value, preferring English.
    Recursively processes nested structures.

    Args:
        value: Any value (typically dict, string, list, etc.)

    Returns:
        - If dict with language codes: extracted text string
        - If dict with nested language codes: recursively extracted
        - Otherwise: original value unchanged

    Examples:
        >>> extract_language_text({'en': 'Wetlands'})
        'Wetlands'
        >>> extract_language_text({'eng': 'Fresh water', 'fra': 'Eau douce'})
        'Fresh water'
        >>> extract_language_text({'description': {'en': 'Text'}})
        {'description': 'Text'}  # Recursively extracts nested
        >>> extract_language_text({'key': 'value', 'other': 'data'})
        {'key': 'value', 'other': 'data'}  # Not a language dict
        >>> extract_language_text("plain text")
        'plain text'
    """
    if isinstance(value, dict):
        # Language codes to check (in order of preference)
        lang_codes = ['en', 'eng', 'en-US', 'en_US', 'en-GB', 'en_GB']

        # Check if this looks like a language-coded dict
        # (keys are short and look like language codes)
        dict_keys = list(value.keys())
        if len(dict_keys) > 0 and all(len(str(k)) <= 5 for k in dict_keys):
            # Try preferred language codes
            for lang_code in lang_codes:
                if lang_code in value:
                    return value[lang_code]

            # If single key, assume it's a language dict and return that value
            if len(value) == 1:
                return list(value.values())[0]

        # Not a language dict itself, but might contain nested language dicts
        # Recursively process values
        result = {}
        for k, v in value.items():
            result[k] = extract_language_text(v)
        return result
    elif isinstance(value, list):
        # Recursively process list items
        return [extract_language_text(item) for item in value]

    # Not a dict or list, return as-is
    return value


def humanize_field_name(field_name: str) -> str:
    """
    Convert snake_case field names to human-readable titles.

    Args:
        field_name: Snake case field name (e.g., "species_name")

    Returns:
        Human-readable title (e.g., "Species Name")

    Examples:
        >>> humanize_field_name("species_name")
        'Species Name'
        >>> humanize_field_name("common_names_list")
        'Common Names List'
        >>> humanize_field_name("iucn_category")
        'IUCN Category'
    """
    # Handle common acronyms
    acronyms = {"iucn", "gbif", "id", "url", "api", "easin"}

    words = field_name.split('_')
    humanized_words = []

    for word in words:
        if word.lower() in acronyms:
            humanized_words.append(word.upper())
        else:
            humanized_words.append(word.capitalize())

    return ' '.join(humanized_words)


def extract_sources(field_data: List[SourceEntry]) -> List[str]:
    """
    Extract unique sources from field data entries.

    Args:
        field_data: List of source-attributed value wrappers

    Returns:
        List of unique source names

    Examples:
        >>> data = [
        ...     {"value": "X", "source": "AquaNIS"},
        ...     {"value": "Y", "source": "GBIF"}
        ... ]
        >>> extract_sources(data)
        ['AquaNIS', 'GBIF']
    """
    return list(set(entry.get("source", "Unknown") for entry in field_data))


def detect_field_structure(field_data: List[SourceEntry]) -> StructureType:
    """
    Analyze a field's data and determine its structure type.

    This function examines the first non-null entry to determine the overall
    structure pattern. It handles:
    - Simple values (strings, numbers)
    - Boolean values
    - Null/missing values
    - Dictionary values (nested objects)
    - Lists (of dicts or strings)
    - Complex nested structures

    Args:
        field_data: List of source-attributed value wrappers

    Returns:
        Structure type identifier for routing to appropriate renderer

    Examples:
        >>> detect_field_structure([{"value": "Text", "data_type": "string"}])
        'simple_value'
        >>> detect_field_structure([{"value": {"key": "val"}, "data_type": "dict"}])
        'dict_value'
        >>> detect_field_structure([{"value": [{"name": "X"}], "data_type": "list"}])
        'list_of_dicts'
    """
    if not field_data:
        return "null"

    # Find first non-null entry to determine structure
    sample_entry = None
    for entry in field_data:
        if entry.get("value") is not None:
            sample_entry = entry
            break

    if sample_entry is None:
        return "null"

    data_type = sample_entry.get("data_type", "string")
    value = sample_entry.get("value")

    # Boolean type
    if data_type == "boolean":
        return "boolean"

    # Null type
    if data_type == "null" or value is None:
        return "null"

    # Simple value types (string, number)
    if data_type in ("string", "number"):
        return "simple_value"

    # Dictionary type
    if data_type == "dict":
        if isinstance(value, dict):
            # Check if it's a nested complex structure (dict containing lists/nested dicts)
            for v in value.values():
                if isinstance(v, (list, dict)):
                    return "nested_complex"
            return "dict_value"
        return "simple_value"

    # List type - need to determine what's in the list
    if data_type == "list":
        if isinstance(value, list) and len(value) > 0:
            first_item = value[0]
            if isinstance(first_item, dict):
                return "list_of_dicts"
            else:
                return "list_of_strings"
        return "list_of_strings"

    # Default fallback
    return "simple_value"


def format_dict_as_text(value: Dict[str, Any]) -> str:
    """
    Format a dictionary as human-readable text.

    Extracts language-coded values and formats key-value pairs.

    Args:
        value: Dictionary to format

    Returns:
        Formatted text representation
    """
    extracted = extract_language_text(value)
    if isinstance(extracted, dict):
        parts = []
        for k, v in extracted.items():
            # Skip empty or None values
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            # Skip internal/metadata fields
            if k.startswith('_'):
                continue
            parts.append(f"{humanize_field_name(k)}: {v}")
        return " | ".join(parts) if parts else str(value)
    return str(extracted)


def format_list_item(item: Any) -> str:
    """
    Format a single list item for display.

    Args:
        item: Item to format (can be string, dict, or other)

    Returns:
        String representation for display
    """
    if isinstance(item, dict):
        return format_dict_as_text(item)
    return str(item)
