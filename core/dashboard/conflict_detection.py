#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Conflict Detection
Functions for detecting and displaying data conflicts between multiple sources.
"""

from typing import Any, Dict, List

from core.dashboard.data_loaders import load_categorized_species_json


# ============================================================================
# CONFLICT DETECTION FUNCTIONS
# ============================================================================

def detect_conflicts(species_name: str, fields_to_check: List[str]) -> Dict[str, Any]:
    """
    Detect conflicts in taxonomic classification where same field has different values from different sources.
    Now properly works with multi-source data arrays.

    Args:
        species_name: Species name to check
        fields_to_check: List of field names to check for conflicts

    Returns:
        Dict with conflict information including has_conflicts, total_conflicts, and conflicts dict
    """
    # Import here to avoid circular imports
    from core.dashboard.species_data import get_taxonomic_data

    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return {"error": f"Species '{species_name}' not found in categorized cache"}

    sources = categorized_data.get('sources', [])
    if len(sources) < 2:
        return {
            "species_name": species_name,
            "has_conflicts": False,
            "total_conflicts": 0,
            "conflicts": {}
        }

    # Get taxonomic data which now includes conflicts detected during extraction
    tax_data = get_taxonomic_data(species_name)

    return {
        "species_name": species_name,
        "has_conflicts": 'conflicts' in tax_data and len(tax_data.get('conflicts', {})) > 0,
        "total_conflicts": len(tax_data.get('conflicts', {})),
        "conflicts": tax_data.get('conflicts', {})
    }


def check_data_categories(species_name: str) -> Dict[str, bool]:
    """
    Check which data categories are available for a species.

    Args:
        species_name: Species name to check

    Returns:
        Dict mapping category display names to availability booleans
    """
    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return {}

    categorized_fields = categorized_data.get('categorized_fields', {})

    results = {
        'Taxonomic Identity': 'taxonomic_identity' in categorized_fields and bool(categorized_fields['taxonomic_identity']),
        'Distribution Records': 'distribution' in categorized_fields and bool(categorized_fields['distribution']),
        'Environmental Tolerances': 'environmental_tolerances' in categorized_fields and bool(categorized_fields['environmental_tolerances']),
        'Conservation Records': 'conservation' in categorized_fields and bool(categorized_fields['conservation']),
        'Morphological Traits': 'morphological_traits' in categorized_fields and bool(categorized_fields['morphological_traits']),
        'Physiological Traits': 'physiological_traits' in categorized_fields and bool(categorized_fields['physiological_traits']),
        'Data Metadata': 'data_metadata' in categorized_fields and bool(categorized_fields['data_metadata'])
    }

    return results


def aggregate_distribution_by_status(distribution_data: Dict[str, Any]) -> Dict[str, int]:
    """
    Aggregates distribution location counts by establishment status.

    Args:
        distribution_data: Distribution data dict from get_distribution_data()

    Returns:
        Dict with status names as keys and counts as values
        e.g., {'Native': 0, 'Established': 18, 'Uncertain': 104}
    """
    status_counts = {}

    # Get counts from the distribution data
    native_count = distribution_data.get('native_locations_count', 0)
    established_count = distribution_data.get('established_locations_count', 0)
    uncertain_count = distribution_data.get('uncertain_locations_count', 0)

    # Only include statuses with non-zero counts
    if native_count > 0:
        status_counts['Native'] = native_count
    if established_count > 0:
        status_counts['Established'] = established_count
    if uncertain_count > 0:
        status_counts['Uncertain'] = uncertain_count

    return status_counts


def prepare_conflict_display_data(conflicts_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepares conflict data for generic display component.

    Args:
        conflicts_dict: Conflicts dict from get_taxonomic_data() or detect_conflicts()
                       Format: {'field_name': [{'value': str, 'sources': list}, ...]}

    Returns:
        Dict with:
            'has_conflicts': bool
            'conflict_fields': list of field names with conflicts
            'conflicts': original conflicts dict
    """
    if not conflicts_dict:
        return {
            'has_conflicts': False,
            'conflict_fields': [],
            'conflicts': {}
        }

    return {
        'has_conflicts': len(conflicts_dict) > 0,
        'conflict_fields': list(conflicts_dict.keys()),
        'conflicts': conflicts_dict
    }
