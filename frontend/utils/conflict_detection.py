# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Conflict Detection Utilities
=============================

Provides reusable functions for detecting and handling conflicts in multi-source data.
Used across the frontend to identify when different sources provide conflicting values
for the same field.
"""

from typing import Dict, List, Any, Optional, Tuple


def detect_field_conflicts(
    field_data_sources: List[Dict[str, Any]],
    normalize_case: bool = True,
    skip_none: bool = True
) -> Dict[str, Any]:
    """
    Detect conflicts in a field that has multiple source entries.

    Args:
        field_data_sources: List of source entries, each with 'value' and 'source' keys
        normalize_case: If True, normalize string values for case-insensitive comparison
        skip_none: If True, skip None/empty values

    Returns:
        Dictionary containing:
            - 'has_conflict': bool - True if multiple different values exist
            - 'values': dict - Mapping of normalized_value -> {'original_value', 'sources'}
            - 'primary_value': The most common value (or first if tied)
            - 'conflict_list': List of dicts for UI display [{'value': str, 'sources': [str]}]

    Example:
        >>> entries = [
        ...     {'value': 'Animalia', 'source': 'GBIF'},
        ...     {'value': 'Animalia', 'source': 'WoRMS'},
        ...     {'value': 'Animal', 'source': 'EASIN'}
        ... ]
        >>> result = detect_field_conflicts(entries)
        >>> result['has_conflict']
        True
        >>> len(result['conflict_list'])
        2
    """
    values_map = {}

    for entry in field_data_sources:
        if not isinstance(entry, dict):
            continue

        value = entry.get('value')
        source = entry.get('source', 'Unknown')

        # Skip None/empty values if requested
        if skip_none and not value:
            continue

        # Handle different value types
        if value is None:
            continue
        elif isinstance(value, list) and len(value) == 0:
            continue
        elif isinstance(value, dict) and len(value) == 0:
            continue
        elif isinstance(value, str):
            if normalize_case:
                normalized_key = value.strip().lower()
            else:
                normalized_key = value.strip()
            # Skip empty strings
            if not normalized_key:
                continue
        elif isinstance(value, (dict, list)):
            # For complex types, convert to JSON string for comparison
            import json
            normalized_key = json.dumps(value, sort_keys=True)
        else:
            normalized_key = str(value)

        # Store value with its sources
        if normalized_key not in values_map:
            values_map[normalized_key] = {
                'original_value': value,
                'sources': []
            }
        values_map[normalized_key]['sources'].append(source)

    # Determine primary value (most common, or first if tied)
    if not values_map:
        return {
            'has_conflict': False,
            'values': {},
            'primary_value': None,
            'conflict_list': []
        }

    # Sort by number of sources (descending), then alphabetically
    sorted_values = sorted(
        values_map.items(),
        key=lambda x: (-len(x[1]['sources']), x[0])
    )
    primary_key = sorted_values[0][0]
    primary_value = values_map[primary_key]['original_value']

    # Create conflict list for UI display
    conflict_list = [
        {'value': info['original_value'], 'sources': info['sources']}
        for info in values_map.values()
    ]

    return {
        'has_conflict': len(values_map) > 1,
        'values': values_map,
        'primary_value': primary_value,
        'conflict_list': conflict_list
    }


def merge_related_fields(
    field_data_dict: Dict[str, List[Dict[str, Any]]],
    field_names: List[str],
    normalize_case: bool = True,
    skip_none: bool = True
) -> Dict[str, Any]:
    """
    Merge multiple related fields (e.g., 'authority' and 'authorship') and detect conflicts.

    Args:
        field_data_dict: Dictionary mapping field names to their source entries
        field_names: List of field names to merge (e.g., ['authority', 'authorship'])
        normalize_case: If True, normalize string values for case-insensitive comparison
        skip_none: If True, skip None/empty values

    Returns:
        Same structure as detect_field_conflicts()

    Example:
        >>> tax_identity = {
        ...     'authority': [{'value': '(Girard, 1852)', 'source': 'WoRMS'}],
        ...     'authorship': [{'value': '(Hagen, 1870)', 'source': 'EASIN'}]
        ... }
        >>> result = merge_related_fields(tax_identity, ['authority', 'authorship'])
        >>> result['has_conflict']
        True
    """
    # Collect all entries from specified fields
    merged_entries = []
    for field_name in field_names:
        if field_name in field_data_dict:
            field_entries = field_data_dict[field_name]
            if isinstance(field_entries, list):
                merged_entries.extend(field_entries)

    # Detect conflicts in the merged data
    return detect_field_conflicts(merged_entries, normalize_case, skip_none)


def collect_name_variants(
    tax_identity: Dict[str, Any],
    accepted_name: Optional[str] = None,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Build a unified nomenclature block from species_name (one per source) and
    synonyms (a list per source), attributing every name to the source(s) that
    recognize it.

    Unlike the rank-conflict logic this is NOT framed as a conflict — synonyms are
    alternate accepted names in different taxonomic treatments, not disagreements.

    Args:
        tax_identity:  Raw taxonomic identity field dict (species_name, synonyms, …)
        accepted_name: The canonical name the user searched for (used to label which
                       variant is "accepted").  Falls back to the most-sourced name.

    Returns:
        (accepted_name_used, detect_field_conflicts_result)
        where detect_field_conflicts_result has the standard structure:
          has_conflict (ignored here), primary_value, conflict_list [{value, sources}]
    """
    entries: List[Dict[str, Any]] = []
    # Track (normalized_value, source) pairs to avoid duplicate entries from the same source
    _seen: set = set()

    def _add(value: str, source: str) -> None:
        key = (value.strip().lower(), source)
        if key not in _seen:
            _seen.add(key)
            entries.append({'value': value.strip(), 'source': source})

    # 1. Add the per-source accepted name (one per source from species_name field)
    for entry in tax_identity.get('species_name', []):
        if isinstance(entry, dict) and entry.get('value'):
            _add(str(entry['value']), entry.get('source', 'Unknown'))

    # 2. Expand synonyms lists into individual {value, source} records
    for entry in tax_identity.get('synonyms', []):
        if not isinstance(entry, dict):
            continue
        value = entry.get('value')
        source = entry.get('source', 'Unknown')
        if isinstance(value, list):
            for syn in value:
                # Synonyms often include authorship "(Girard, 1852)" — keep as-is for display
                if syn and isinstance(syn, str) and syn.strip():
                    _add(syn.strip(), source)

    result = detect_field_conflicts(entries, normalize_case=True, skip_none=True)

    # Determine which name to mark as accepted: prefer the caller-supplied name,
    # fall back to primary_value from conflict detection (most-sourced).
    resolved_accepted: Optional[str] = None
    if accepted_name:
        # Find the original-case variant that matches case-insensitively
        needle = accepted_name.strip().lower()
        for info in result['values'].values():
            orig = info['original_value']
            if isinstance(orig, str) and orig.strip().lower() == needle:
                resolved_accepted = orig
                break
    if resolved_accepted is None:
        resolved_accepted = result['primary_value']

    return resolved_accepted, result


def collect_rank_values_from_sources(
    tax_identity: Dict[str, Any],
    rank: str
) -> Dict[str, Any]:
    """
    Collect taxonomic rank values from both individual fields AND taxonomy dict.

    This function handles the special case where taxonomic rank data can come from:
    1. Individual rank fields (e.g., tax_identity['kingdom'])
    2. Taxonomy dictionary field (e.g., tax_identity['taxonomy'][0]['value']['kingdom'])

    Args:
        tax_identity: Taxonomic identity data with multi-source format
        rank: Rank name (e.g., 'kingdom', 'phylum', 'class')

    Returns:
        Same structure as detect_field_conflicts()

    Example:
        >>> tax_identity = {
        ...     'kingdom': [{'value': 'Animalia', 'source': 'GBIF'}],
        ...     'taxonomy': [{
        ...         'value': {'KINGDOM': 'Animalia', 'PHYLUM': 'Arthropoda'},
        ...         'source': 'WoRMS'
        ...     }]
        ... }
        >>> result = collect_rank_values_from_sources(tax_identity, 'kingdom')
        >>> result['primary_value']
        'Animalia'
    """
    rank_entries = []

    # Step 1: Collect values from individual fields (if present)
    if rank in tax_identity:
        individual_field_data = tax_identity[rank]
        if isinstance(individual_field_data, list):
            rank_entries.extend(individual_field_data)

    # Step 2: Collect values from taxonomy dict (if present)
    if 'taxonomy' in tax_identity:
        taxonomy_sources = tax_identity['taxonomy']
        if isinstance(taxonomy_sources, list):
            for source_entry in taxonomy_sources:
                if not isinstance(source_entry, dict):
                    continue

                source = source_entry.get('source', 'Unknown')
                taxonomy_dict = source_entry.get('value')

                if not isinstance(taxonomy_dict, dict):
                    continue

                # Try lowercase field name first, then uppercase
                value = taxonomy_dict.get(rank) or taxonomy_dict.get(rank.upper())

                if value:
                    # Create a source entry in the same format
                    rank_entries.append({
                        'value': value,
                        'source': source,
                        'data_type': 'string'
                    })

    # Detect conflicts in the collected data
    return detect_field_conflicts(rank_entries, normalize_case=True, skip_none=True)
