# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Universal Identifier Generator for Species Data

This module provides utilities to create and manage cache identifiers
for species data based on search queries and timestamps.

The cache ID format is: {timestamp}_{sanitized_search_query}
Example: "20241201_143022_red_swamp_crayfish"

This creates a unique folder for each search session. Cache is cleared
between species searches, so no synonym grouping is needed.
"""

import re
from datetime import datetime
from typing import Dict, Optional


def sanitize_for_id(name: str) -> str:
    """
    Sanitize a species name for use in universal ID.

    Converts to lowercase, replaces spaces with underscores,
    and removes all non-alphanumeric characters except underscores and hyphens.

    Args:
        name: Species name to sanitize

    Returns:
        Sanitized name suitable for use in filenames and IDs

    Examples:
        >>> sanitize_for_id("Procambarus clarkii")
        'procambarus_clarkii'
        >>> sanitize_for_id("Vespa velutina nigrithorax")
        'vespa_velutina_nigrithorax'
        >>> sanitize_for_id("Red Swamp Crayfish")
        'red_swamp_crayfish'
    """
    # Convert to lowercase
    sanitized = name.lower().strip()

    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')

    # Remove parentheses, periods, commas, and other special characters
    # Keep only alphanumeric, underscores, and hyphens
    sanitized = re.sub(r'[^a-z0-9_\-]', '', sanitized)

    # Replace multiple underscores with single underscore
    sanitized = re.sub(r'_+', '_', sanitized)

    # Remove leading/trailing underscores
    sanitized = sanitized.strip('_')

    return sanitized


def generate_cache_id(search_query: str) -> str:
    """
    Generate a cache identifier for a species search.

    The cache ID combines a timestamp with the sanitized search query.
    This creates a unique folder for each search session.

    Args:
        search_query: Original search query (species name, common name, etc.)

    Returns:
        Cache ID string in format "{timestamp}_{sanitized_query}"

    Examples:
        >>> generate_cache_id("Procambarus clarkii")
        '20241201_143022_procambarus_clarkii'
        >>> generate_cache_id("Red Swamp Crayfish")
        '20241201_143022_red_swamp_crayfish'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_query = sanitize_for_id(search_query)
    return f"{timestamp}_{sanitized_query}"



def parse_cache_id(cache_id: str) -> Dict[str, str]:
    """
    Parse a cache ID back into its components.

    Args:
        cache_id: Cache ID string (e.g., "20241201_143022_procambarus_clarkii")

    Returns:
        Dictionary with 'timestamp' (str) and 'search_query' (str)

    Raises:
        ValueError: If cache_id is not in the expected format

    Examples:
        >>> parse_cache_id("20241201_143022_procambarus_clarkii")
        {'timestamp': '20241201_143022', 'search_query': 'procambarus clarkii'}
        >>> parse_cache_id("20241201_143022_red_swamp_crayfish")
        {'timestamp': '20241201_143022', 'search_query': 'red swamp crayfish'}
    """
    # Split into timestamp and query parts
    # Format: YYYYMMdd_HHmmss_query_parts
    parts = cache_id.split('_')

    if len(parts) < 3:
        raise ValueError(
            f"Invalid cache_id format: '{cache_id}'. "
            f"Expected format: 'YYYYMMdd_HHmmss_search_query'"
        )

    # First two parts are timestamp (YYYYMMdd_HHmmss)
    timestamp = f"{parts[0]}_{parts[1]}"

    # Remaining parts are the search query
    search_query = '_'.join(parts[2:])

    # Convert underscores back to spaces for display
    search_query = search_query.replace('_', ' ')

    return {
        'timestamp': timestamp,
        'search_query': search_query
    }



def get_display_name_from_id(cache_id: str) -> str:
    """
    Extract a human-readable display name from a cache ID.

    Args:
        cache_id: Cache ID string

    Returns:
        Display name with proper capitalization

    Examples:
        >>> get_display_name_from_id("20241201_143022_procambarus_clarkii")
        'Procambarus clarkii'
        >>> get_display_name_from_id("20241201_143022_red_swamp_crayfish")
        'Red Swamp Crayfish'
    """
    parsed = parse_cache_id(cache_id)
    name = parsed['search_query']

    # Apply proper capitalization
    # First word capitalized, rest lowercase (for scientific names)
    # Or title case for common names
    parts = name.split()
    if len(parts) > 0:
        # Check if it looks like a scientific name (2 parts, lowercase)
        if len(parts) == 2 and all(p.islower() for p in parts):
            # Scientific name: capitalize genus only
            parts[0] = parts[0].capitalize()
        else:
            # Common name or other: title case
            parts = [p.capitalize() for p in parts]

    return ' '.join(parts)


def is_valid_cache_id(cache_id: str) -> bool:
    """
    Check if a string is a valid cache ID.

    Args:
        cache_id: String to validate

    Returns:
        True if valid, False otherwise

    Examples:
        >>> is_valid_cache_id("20241201_143022_procambarus_clarkii")
        True
        >>> is_valid_cache_id("invalid_format")
        False
        >>> is_valid_cache_id("not_timestamp_species_name")
        False
    """
    try:
        parse_cache_id(cache_id)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    # Manual smoke test: exercise cache-ID generation and parsing from the CLI.
    print("=== Cache Identifier Examples ===\n")

    # Example 1: Scientific name
    query1 = "Procambarus clarkii"
    cache_id1 = generate_cache_id(query1)
    print(f"Input: {query1}")
    print(f"Cache ID: {cache_id1}")
    print(f"Parsed: {parse_cache_id(cache_id1)}")
    print(f"Display Name: {get_display_name_from_id(cache_id1)}")
    print()

    # Example 2: Common name
    query2 = "Red Swamp Crayfish"
    cache_id2 = generate_cache_id(query2)
    print(f"Input: {query2}")
    print(f"Cache ID: {cache_id2}")
    print(f"Parsed: {parse_cache_id(cache_id2)}")
    print(f"Display Name: {get_display_name_from_id(cache_id2)}")
    print()

    # Example 3: Another species
    query3 = "Ciona intestinalis"
    cache_id3 = generate_cache_id(query3)
    print(f"Input: {query3}")
    print(f"Cache ID: {cache_id3}")
    print(f"Parsed: {parse_cache_id(cache_id3)}")
    print()

    # Validation
    print("=== Validation Tests ===")
    print(f"Valid ID: {is_valid_cache_id('20241201_143022_procambarus_clarkii')}")
    print(f"Invalid ID: {is_valid_cache_id('invalid_format')}")
