# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Vernacular Name Utilities
Deduplication and processing functions for vernacular names.
"""

from typing import Dict, List, Set
from frontend.utils.flags import get_language_flag


def deduplicate_names(names: List[str]) -> List[str]:
    """
    Remove duplicate names while preserving original casing and order.

    Args:
        names: List of vernacular names that may contain duplicates

    Returns:
        List of unique names, preserving the first occurrence's casing
    """
    if not names or not isinstance(names, list):
        return []

    seen_names: Set[str] = set()
    unique_names: List[str] = []

    for name in names:
        if not name or not isinstance(name, str):
            continue

        # Normalize for comparison (lowercase, stripped)
        normalized = name.lower().strip()

        # Skip empty names or already seen names
        if not normalized or normalized in seen_names:
            continue

        # Add to results with original casing
        seen_names.add(normalized)
        unique_names.append(name.strip())

    # Sort alphabetically for consistent display
    return sorted(unique_names, key=str.lower)


def process_vernacular_names(vernacular_data: Dict[str, List[str]], max_names_per_language: int = 4) -> Dict[str, List[str]]:
    """
    Process vernacular names data: deduplicate, limit, and clean.

    Args:
        vernacular_data: Dictionary with language codes as keys and name lists as values
        max_names_per_language: Maximum number of names to show per language

    Returns:
        Processed dictionary with deduplicated and limited names
    """
    if not vernacular_data or not isinstance(vernacular_data, dict):
        return {}

    processed_data = {}

    for language_code, names in vernacular_data.items():
        if not language_code or not names:
            continue

        # Deduplicate names
        unique_names = deduplicate_names(names)

        # Limit number of names per language
        if len(unique_names) > max_names_per_language:
            unique_names = unique_names[:max_names_per_language]

        # Only add if we have names
        if unique_names:
            processed_data[language_code] = unique_names

    return processed_data


def format_vernacular_display(language_code: str, names: List[str]) -> tuple[str, str, List[str]]:
    """
    Format vernacular names for display with appropriate flag - NO TRUNCATION.

    Args:
        language_code: ISO language code
        names: List of unique vernacular names

    Returns:
        Tuple of (flag_emoji, language_name, names_list)
    """
    if not names:
        return "🌐", language_code.capitalize(), []

    # Get flag
    flag = get_language_flag(language_code)

    # Format language name
    language_name = language_code.capitalize()

    # Return all names without truncation
    return flag, language_name, names


def get_vernacular_summary(language_code: str, names: List[str]) -> tuple[str, str, str]:
    """
    Get a summary for vernacular names display (for accordion headers).

    Args:
        language_code: ISO language code
        names: List of unique vernacular names

    Returns:
        Tuple of (flag_emoji, language_name, summary_string)
    """
    if not names:
        return "🌐", language_code.capitalize(), "No names available"

    # Get flag
    flag = get_language_flag(language_code)

    # Format language name
    language_name = language_code.capitalize()

    # Create summary
    if len(names) == 1:
        summary = names[0]
    elif len(names) <= 3:
        summary = ", ".join(names)
    else:
        summary = f"{', '.join(names[:2])}... ({len(names)} total)"

    return flag, language_name, summary
