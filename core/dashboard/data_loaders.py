#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Data Loaders
JSON loading and cache utilities for dashboard data access.
Reads from AI-categorized data in cache/categorized_data/
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id
from core.utils.cache_manager import get_cache_manager


# ============================================================================
# JSON CACHE UTILITIES
# ============================================================================

def load_categorized_species_json(species_name: str, universal_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Load AI-categorized species data from folder structure.

    Args:
        species_name: Scientific name of the species (not used if universal_id provided)
        universal_id: Universal species identifier (format: {gbif_key}_{name}) - REQUIRED for folder structure

    Returns:
        Categorized species data dictionary or None if not found
    """
    if not universal_id:
        print(f"Warning: universal_id required for loading species data. species_name alone is deprecated.")
        return None

    # Use session-aware cache helper function
    return load_categorized_data_by_id(universal_id)


def list_cached_species() -> List[str]:
    """
    List all species in categorized cache from folder structure (session-aware).
    """
    from core.utils.session_context import get_session_cache_subdirectory

    species_set = set()
    categorized_dir = get_session_cache_subdirectory('categorized_data')

    if not categorized_dir.exists():
        return []

    for item in categorized_dir.iterdir():
        # Only check folder structure
        if item.is_dir():
            manifest_path = item / 'manifest.json'
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                        species_name = manifest.get('species_name', '')
                        if species_name:
                            species_set.add(species_name)
                except Exception:
                    pass  # Skip folders without valid manifest

    return sorted(list(species_set))


def get_category_data(species_name: str, category: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Get data from a specific AI category.

    If universal_id is not provided, attempts to get it from Streamlit session state.

    Args:
        species_name: Scientific name
        category: Category name (taxonomic_identity, distribution, etc.)
        universal_id: Optional universal species identifier

    Returns:
        Category data dictionary or empty dict if not found
    """
    # Try to get universal_id from Streamlit session state if not provided.
    # Guard with get_script_run_ctx(suppress_warning=True) so this never emits
    # ScriptRunContext warnings when called from pipelines or CLI scripts.
    if universal_id is None:
        try:
            from streamlit.runtime.scriptrunner import get_script_run_ctx
            if get_script_run_ctx(suppress_warning=True) is not None:
                import streamlit as st
                if hasattr(st.session_state, 'universal_id'):
                    universal_id = st.session_state.universal_id
        except Exception:
            pass  # Streamlit not available or version mismatch

    categorized_data = load_categorized_species_json(species_name, universal_id)
    if not categorized_data:
        return {}

    return categorized_data.get('categorized_fields', {}).get(category, {})


# ============================================================================
# MULTI-SOURCE HELPER FUNCTIONS
# ============================================================================

def extract_multi_source_field(field_data):
    """
    Extract values from multi-source field (array format).

    Args:
        field_data: Either a list of source entries or a single dict (legacy format)

    Returns:
        Dict with:
            'values': {value_str: [source1, source2, ...]},
            'primary_value': most common value or first,
            'has_conflict': True if multiple different values exist
    """
    # Handle legacy single-source format
    if not isinstance(field_data, list):
        value = field_data.get('value') if isinstance(field_data, dict) else field_data
        source = field_data.get('source', 'Unknown') if isinstance(field_data, dict) else 'Unknown'
        return {
            'values': {str(value): [source]} if value is not None else {},
            'primary_value': value,
            'has_conflict': False
        }

    # Group values by their normalized string representation
    value_sources = {}
    for entry in field_data:
        if not isinstance(entry, dict):
            continue

        value = entry.get('value')
        source = entry.get('source', 'Unknown')

        # Normalize value for comparison (handle None, strip whitespace, case-insensitive for strings)
        if value is None:
            continue
        # Skip empty lists and empty dicts - treat them as missing data
        elif isinstance(value, list) and len(value) == 0:
            continue
        elif isinstance(value, dict) and len(value) == 0:
            continue
        elif isinstance(value, str):
            value_key = value.strip()
            # Skip empty strings
            if not value_key:
                continue
        elif isinstance(value, (dict, list)):
            # For complex types, convert to JSON string for comparison
            value_key = json.dumps(value, sort_keys=True)
        else:
            value_key = str(value)

        if value_key:
            if value_key not in value_sources:
                value_sources[value_key] = {'original_value': value, 'sources': []}
            value_sources[value_key]['sources'].append(source)

    # Determine primary value (most common, or first if tied)
    if not value_sources:
        return {'values': {}, 'primary_value': None, 'has_conflict': False}

    # Sort by number of sources (descending), then alphabetically
    sorted_values = sorted(value_sources.items(),
                          key=lambda x: (-len(x[1]['sources']), x[0]))
    primary_key = sorted_values[0][0]
    primary_value = value_sources[primary_key]['original_value']

    # Prepare values dict for output
    values_dict = {key: data['sources'] for key, data in value_sources.items()}

    return {
        'values': values_dict,
        'primary_value': primary_value,
        'has_conflict': len(value_sources) > 1
    }


def merge_multi_source_list(field_data, key_fn=None):
    """
    Union all source lists for a list-valued multi-source field.

    Unlike extract_multi_source_field() (which is built for scalar fields and
    returns only one "primary" value), list fields such as synonyms and
    vernacular names should keep every item from every source. That function
    serializes each source's whole list into a single key and discards all but
    the winning source's list — this one flattens and deduplicates instead.

    Per-source provenance is left untouched in the cache; this is a read-time
    projection used by the dashboard.

    Args:
        field_data: List of source entries, each a dict with a list 'value',
                    or a single legacy entry.
        key_fn: Optional fn(item) -> hashable dedup key. Defaults to a
                case-insensitive string key. First-seen item (original casing
                and order) wins on duplicates.

    Returns:
        A single deduplicated list of items across all sources.
    """
    if not isinstance(field_data, list):
        field_data = [field_data]

    if key_fn is None:
        key_fn = lambda item: str(item).strip().lower()

    merged = []
    seen = set()
    for entry in field_data:
        value = entry.get('value') if isinstance(entry, dict) else entry
        if not isinstance(value, list):
            continue
        for item in value:
            try:
                key = key_fn(item)
            except (TypeError, AttributeError, KeyError):
                continue
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    return merged
