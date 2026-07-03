#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Categorized Data Helper Functions

Provides generic, flexible tools for extracting data from AI-categorized species JSON files.

Design Philosophy:
    - These helpers provide TOOLS for navigating the JSON structure
    - They do NOT transform, flatten, or make assumptions about field names
    - The CALLER decides what to extract, the helpers just provide efficient access
    - Source attribution is preserved throughout all operations

JSON Structure Overview:
    All fields follow this universal pattern:
    "field_name": [
        {
            "value": <actual_data>,
            "data_type": "string|number|boolean|list|dict",
            "ai_reasoning": "Why AI categorized this field here",
            "source": "GBIF|WRiMS|IUCN"
        },
        ... more sources if applicable
    ]

Categories (11-category schema):
    - taxonomic_identity: Scientific names, taxonomic ranks, taxonomy hierarchy, synonyms, common names, authority
    - morphological_traits: Physical characteristics, size, colour patterns, anatomical features, life stages, diagnostic features
    - physiological_traits: Growth rates, longevity, reproduction strategy, fecundity, diet, feeding behaviour, dispersal mechanisms
    - distribution: Native range, introduced range, occurrence records, establishment status, invasion history, spread rates, pathways
    - habitat_ecology: Habitat types, environmental requirements, temperature/salinity/pH/depth ranges, substrate preferences, ecological role
    - species_interactions: Predator-prey relationships, competition, mutualism, parasites, diseases, habitat modification effects
    - impacts: Ecological impacts on natives/ecosystems, economic costs/damage, social/health impacts, impact mechanisms
    - management_biosecurity: Prevention measures, control methods, eradication attempts, regulations, legal status, biosecurity
    - conservation_status: IUCN category, population trends, threats, conservation actions, protected area presence
    - economic_utilisation: Commercial use, fisheries, aquaculture, ornamental trade, subsistence use, market value
    - detection_monitoring: Identification methods, survey protocols, eDNA markers, early detection indicators
    - data_metadata: Source URLs, database IDs, data quality indicators, timestamps, geographic scope, image URLs

Helper Function Types:
    1. Utility Functions - Load data, navigate categories and fields
    2. Array Wrapper Handlers - Unwrap the universal array structure
    3. Pattern Detection - Identify value types (string, list, dict, nested, etc.)
    4. Generic Extractors - Extract values based on type
    5. Nested Navigation - Navigate into nested dicts by path
    6. Source Database Helpers - Cross-reference to original database sources (specialized)
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

# ============================================================================
# CONSTANTS
# ============================================================================

def get_default_cache_dir() -> Path:
    """
    Get session-aware default cache directory.

    Returns the categorized_data cache directory for the current user session.
    This enables multi-user cache isolation.

    Returns:
        Path: Session-specific categorized data directory
              (e.g., cache/{session_id}/categorized_data)
    """
    from core.utils.cache_manager import get_categorized_data_dir
    return get_categorized_data_dir()


# NOTE: DO NOT create a DEFAULT_CACHE_DIR constant here!
# Constants are evaluated at module import time, before Streamlit session exists
# Always call get_default_cache_dir() dynamically instead

# Manifest and category filenames for folder structure
MANIFEST_FILENAME = "manifest.json"

def _generate_category_filenames() -> dict:
    """
    Generate category filenames from StandardTopicRegistry (single source of truth).

    This ensures category names are consistent across the entire codebase.
    All topic keys come from the registry, eliminating hardcoded duplicates.

    Returns:
        Dict mapping category_key -> filename.json
    """
    from core.registries.topic_registry import StandardTopicRegistry

    filenames = {}

    # Generate filenames for all standard topics from registry
    for key in StandardTopicRegistry.get_all_topic_keys():
        filenames[key] = f"{key}.json"

    # Add system categories (not user-facing topics, but needed for backend)
    filenames["data_metadata"] = "data_metadata.json"
    filenames["unknown"] = "unknown.json"
    filenames["needs_review"] = "needs_review.json"

    return filenames

# Generate category filenames from registry (single source of truth)
CATEGORY_FILENAMES = _generate_category_filenames()


# ============================================================================
# UTILITY FUNCTIONS - Foundation for all other functions
# ============================================================================

def load_categorized_data(species_name: str, cache_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Load the categorized JSON file for a species.

    Args:
        species_name: Scientific name of the species
        cache_dir: Optional custom cache directory path

    Returns:
        Full categorized data structure, or None if file doesn't exist

    Example:
        >>> data = load_categorized_data("Procambarus clarkii")
        >>> data.keys()
        dict_keys(['species_name', 'timestamp', 'sources', 'categorized_fields'])
    """
    if cache_dir is None:
        cache_dir = get_default_cache_dir()

    # Sanitize species name for filename
    safe_name = species_name.replace(' ', '_').replace('.', '').replace('/', '_')
    filename = f"{safe_name}_categorized.json"
    file_path = cache_dir / filename

    if not file_path.exists():
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading categorized data for {species_name}: {e}")
        return None


def get_species_folder(universal_id: str, cache_dir: Optional[Path] = None) -> Path:
    """
    Get the path to a species folder by universal ID.

    Args:
        universal_id: Universal species identifier (format: {gbif_key}_{name})
        cache_dir: Optional custom cache directory path

    Returns:
        Path to the species folder (may not exist yet)

    Example:
        >>> folder = get_species_folder("2227300_procambarus_clarkii")
        >>> folder
        Path('/cache/categorized_data/2227300_procambarus_clarkii')
    """
    if cache_dir is None:
        cache_dir = get_default_cache_dir()

    safe_id = universal_id.replace('/', '_')
    return cache_dir / safe_id


def load_categorized_data_by_id(universal_id: str, cache_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Load categorized data from folder structure for a universal species ID.

    Args:
        universal_id: Universal species identifier (format: {gbif_key}_{name})
        cache_dir: Optional custom cache directory path

    Returns:
        Full categorized data structure, or None if folder doesn't exist

    Examples:
        >>> data = load_categorized_data_by_id("2227300_procambarus_clarkii")
        >>> data.keys()
        dict_keys(['universal_id', 'timestamp', 'sources', 'categorized_fields'])
        >>> data['universal_id']
        '2227300_procambarus_clarkii'
    """
    if cache_dir is None:
        cache_dir = get_default_cache_dir()

    # Get species folder
    species_folder = get_species_folder(universal_id, cache_dir)
    if not species_folder.exists() or not species_folder.is_dir():
        return None

    # Check for manifest
    manifest_path = species_folder / MANIFEST_FILENAME
    if not manifest_path.exists():
        return None

    try:
        # Load manifest
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        # Initialize result with manifest metadata
        result = {
            'universal_id': manifest.get('universal_id', ''),
            'species_name': manifest.get('species_name', ''),
            'timestamp': manifest.get('timestamp', ''),
            'sources': manifest.get('sources', []),
            'categorized_fields': {}
        }

        # Load each available category
        available_categories = manifest.get('available_categories', [])
        for category_name in available_categories:
            # Use known filename or derive from category name (supports custom topics)
            category_file = CATEGORY_FILENAMES.get(category_name, f"{category_name}.json")
            category_path = species_folder / category_file
            if category_path.exists():
                with open(category_path, 'r', encoding='utf-8') as f:
                    category_data = json.load(f)
                    result['categorized_fields'][category_name] = category_data.get('fields', {})

        return result

    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading categorized data from folder {species_folder}: {e}")
        return None


def load_category_file(universal_id: str, category_name: str, cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load a single category file directly without loading other categories.

    This is efficient for when you only need one category's data.

    Args:
        universal_id: Universal species identifier
        category_name: Name of the category to load
        cache_dir: Optional custom cache directory path

    Returns:
        Category dictionary (the fields within that category), or {} if not found

    Example:
        >>> distribution = load_category_file("2227300_procambarus_clarkii", "distribution")
        >>> 'distribution_records' in distribution
        True
    """
    if cache_dir is None:
        cache_dir = get_default_cache_dir()

    # Get category file path (supports custom topics via fallback)
    species_folder = get_species_folder(universal_id, cache_dir)
    category_file = CATEGORY_FILENAMES.get(category_name, f"{category_name}.json")

    category_path = species_folder / category_file
    if not category_path.exists():
        return {}

    try:
        with open(category_path, 'r', encoding='utf-8') as f:
            category_data = json.load(f)
            return category_data.get('fields', {})
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading category {category_name} from {category_path}: {e}")
        return {}


def load_categories(universal_id: str, category_names: List[str], cache_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """
    Load multiple specific categories efficiently.

    Args:
        universal_id: Universal species identifier
        category_names: List of category names to load
        cache_dir: Optional custom cache directory path

    Returns:
        Dictionary mapping category_name -> category_data (fields within that category)

    Example:
        >>> categories = load_categories("2227300_procambarus_clarkii", ["distribution", "impacts"])
        >>> categories.keys()
        dict_keys(['distribution', 'impacts'])
        >>> 'distribution_records' in categories['distribution']
        True
    """
    if cache_dir is None:
        cache_dir = get_default_cache_dir()

    result = {}
    species_folder = get_species_folder(universal_id, cache_dir)

    # Load each category file individually
    for category_name in category_names:
        result[category_name] = load_category_file(universal_id, category_name, cache_dir)

    return result


def get_available_categories(universal_id: str, cache_dir: Optional[Path] = None) -> List[str]:
    """
    Get the list of available categories for a species from manifest.json.

    Args:
        universal_id: Universal species identifier
        cache_dir: Optional custom cache directory path

    Returns:
        List of available category names

    Example:
        >>> categories = get_available_categories("2227300_procambarus_clarkii")
        >>> 'distribution' in categories
        True
    """
    if cache_dir is None:
        cache_dir = get_default_cache_dir()

    species_folder = get_species_folder(universal_id, cache_dir)
    manifest_path = species_folder / MANIFEST_FILENAME

    if not manifest_path.exists():
        return []

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
            return manifest.get('available_categories', [])
    except (json.JSONDecodeError, IOError):
        # Fallback: scan folder for category files
        available = []
        for category_name, filename in CATEGORY_FILENAMES.items():
            category_path = species_folder / filename
            if category_path.exists():
                available.append(category_name)
        return available


def get_category(categorized_data: Optional[Dict[str, Any]], category_name: str) -> Dict[str, Any]:
    """
    Get a specific category from categorized data.

    Args:
        categorized_data: Full categorized JSON structure
        category_name: One of the 11 categories (taxonomic_identity, morphological_traits,
                      physiological_traits, distribution, habitat_ecology, species_interactions,
                      impacts, management_biosecurity, conservation_status, economic_utilisation,
                      detection_monitoring, data_metadata)

    Returns:
        Category dictionary, or {} if category doesn't exist or data is None

    Example:
        >>> data = load_categorized_data("Procambarus clarkii")
        >>> taxonomy = get_category(data, 'taxonomic_identity')
        >>> 'species_name' in taxonomy
        True
    """
    if categorized_data is None:
        return {}

    categorized_fields = categorized_data.get('categorized_fields', {})
    return categorized_fields.get(category_name, {})


def get_field(category_data: Dict[str, Any], field_name: str) -> List[Dict[str, Any]]:
    """
    Get a specific field from a category.

    Args:
        category_data: Category dictionary
        field_name: Name of the field to extract

    Returns:
        Field array (list of source entries), or [] if field doesn't exist

    Example:
        >>> taxonomy = get_category(data, 'taxonomic_identity')
        >>> authority = get_field(taxonomy, 'authority')
        >>> authority[0]['source']
        'WRiMS'
    """
    if category_data is None:
        return []

    field_data = category_data.get(field_name, [])

    # Ensure it's a list (defensive programming)
    if not isinstance(field_data, list):
        return []

    return field_data


# ============================================================================
# ARRAY WRAPPER HANDLERS
# ============================================================================

def unwrap_field(field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Unwraps the array wrapper and returns all source entries.

    This is the most basic extractor - it simply validates and returns the array.

    Args:
        field_data: Field array from categorized JSON

    Returns:
        List of all source entries, or [] if invalid/empty

    Example:
        >>> authority = get_field(taxonomy, 'authority')
        >>> entries = unwrap_field(authority)
        >>> entries[0].keys()
        dict_keys(['value', 'data_type', 'ai_reasoning', 'source'])
    """
    if not isinstance(field_data, list):
        return []

    return field_data


def get_all_values_with_sources(field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract all values with their sources from a field.

    Returns the complete data including value, source, data_type, and ai_reasoning.

    Args:
        field_data: Field array from categorized JSON

    Returns:
        List of all entries with full metadata, or [] if empty

    Example:
        >>> authority = get_field(taxonomy, 'authority')
        >>> values = get_all_values_with_sources(authority)
        >>> values[0]
        {'value': '(Girard, 1852)', 'source': 'WRiMS', 'data_type': 'string', ...}
    """
    entries = unwrap_field(field_data)

    # Filter out malformed entries
    valid_entries = []
    for entry in entries:
        if isinstance(entry, dict) and 'value' in entry and 'source' in entry:
            valid_entries.append(entry)

    return valid_entries


# ============================================================================
# PATTERN DETECTION
# ============================================================================

def detect_value_pattern(field_entry: Dict[str, Any]) -> str:
    """
    Detect the pattern type of the value inside a field entry.

    Args:
        field_entry: Single entry from unwrapped array
                    (must have 'value' and 'data_type' keys)

    Returns:
        Pattern type string:
            - "simple_string"
            - "simple_number"
            - "simple_boolean"
            - "simple_null"
            - "list_flat" (list of primitives)
            - "list_objects" (list of dicts)
            - "dict_flat" (simple dict)
            - "dict_nested" (dict with nested objects)
            - "unknown"

    Example:
        >>> entry = {'value': '(Girard, 1852)', 'data_type': 'string', 'source': 'WRiMS'}
        >>> detect_value_pattern(entry)
        'simple_string'
    """
    if not isinstance(field_entry, dict) or 'value' not in field_entry:
        return "unknown"

    value = field_entry['value']
    data_type = field_entry.get('data_type', '')

    # Handle null
    if value is None:
        return "simple_null"

    # Handle simple types
    if isinstance(value, str):
        return "simple_string"
    if isinstance(value, (int, float)):
        return "simple_number"
    if isinstance(value, bool):
        return "simple_boolean"

    # Handle lists
    if isinstance(value, list):
        if len(value) == 0:
            return "list_flat"
        # Check first element
        if isinstance(value[0], dict):
            return "list_objects"
        else:
            return "list_flat"

    # Handle dicts
    if isinstance(value, dict):
        # Check if any value is a dict or list (nested)
        has_nested = any(isinstance(v, (dict, list)) for v in value.values())
        if has_nested:
            return "dict_nested"
        else:
            return "dict_flat"

    return "unknown"


# ============================================================================
# GENERIC EXTRACTION FUNCTIONS
# ============================================================================

def extract_simple_values(field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract simple values (strings, numbers, booleans) with sources.

    Args:
        field_data: Field array from categorized JSON

    Returns:
        List of {"value": <primitive>, "source": <source>}, or [] if empty

    Example:
        >>> authority = get_field(taxonomy, 'authority')
        >>> values = extract_simple_values(authority)
        >>> values
        [{'value': '(Girard, 1852)', 'source': 'WRiMS'}]
    """
    entries = get_all_values_with_sources(field_data)

    results = []
    for entry in entries:
        value = entry.get('value')
        source = entry.get('source')

        # Only include simple types
        if isinstance(value, (str, int, float, bool)) or value is None:
            results.append({
                'value': value,
                'source': source
            })

    return results


def extract_list_values(field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract list values with sources.

    Args:
        field_data: Field array from categorized JSON

    Returns:
        List of {"value": <list>, "source": <source>}, or [] if empty

    Example:
        >>> synonyms = get_field(taxonomy, 'synonyms')
        >>> values = extract_list_values(synonyms)
        >>> values[0]['value']
        ['Cambarus clarkii Girard, 1852']
    """
    entries = get_all_values_with_sources(field_data)

    results = []
    for entry in entries:
        value = entry.get('value')
        source = entry.get('source')

        if isinstance(value, list):
            results.append({
                'value': value,
                'source': source
            })

    return results


def extract_dict_values(field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract dictionary values with sources.

    Args:
        field_data: Field array from categorized JSON

    Returns:
        List of {"value": <dict>, "source": <source>}, or [] if empty

    Example:
        >>> taxonomy_field = get_field(taxonomy, 'taxonomy')
        >>> values = extract_dict_values(taxonomy_field)
        >>> values[0]['value']['kingdom']
        'Animalia'
    """
    entries = get_all_values_with_sources(field_data)

    results = []
    for entry in entries:
        value = entry.get('value')
        source = entry.get('source')

        if isinstance(value, dict):
            results.append({
                'value': value,
                'source': source
            })

    return results


# ============================================================================
# NESTED NAVIGATION FUNCTIONS
# ============================================================================

def extract_nested_field(field_data: List[Dict[str, Any]], nested_path: List[str]) -> List[Dict[str, Any]]:
    """
    Generic nested field extractor - navigates into nested dicts.

    Args:
        field_data: Field array from categorized JSON
        nested_path: List of keys to navigate (e.g., ['iucn_category'])

    Returns:
        List of {"value": <extracted_value>, "source": <source>}, or [] if not found

    Example:
        >>> conservation_status = get_field(conservation, 'conservation_status')
        >>> iucn_cat = extract_nested_field(conservation_status, ['iucn_category'])
        >>> iucn_cat[0]['value']
        'LC'
    """
    entries = get_all_values_with_sources(field_data)

    results = []
    for entry in entries:
        value = entry.get('value')
        source = entry.get('source')

        # Navigate the nested path
        current = value
        try:
            for key in nested_path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    current = None
                    break

            if current is not None:
                results.append({
                    'value': current,
                    'source': source
                })
        except (KeyError, TypeError):
            # Path navigation failed, skip this entry
            continue

    return results


def extract_all_nested_fields(field_data: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract ALL nested fields from dict values, flattening one level.

    Takes nested dicts and creates a flat dictionary where each nested key
    becomes a top-level key with its own source attribution.

    Args:
        field_data: Field array from categorized JSON (containing dict values)

    Returns:
        Dictionary where keys are nested field names, values are lists of
        {"value": <value>, "source": <source>}, or {} if empty

    Example:
        >>> metadata_field = get_field(metadata_cat, 'metadata')
        >>> all_fields = extract_all_nested_fields(metadata_field)
        >>> all_fields['gbif_key']
        [{'value': 2227300, 'source': 'GBIF'}]
        >>> all_fields['iucn_taxon_id']
        [{'value': 153877, 'source': 'IUCN'}]
    """
    entries = get_all_values_with_sources(field_data)

    result = {}

    for entry in entries:
        value = entry.get('value')
        source = entry.get('source')

        if not isinstance(value, dict):
            continue

        # Iterate through all keys in the nested dict
        for nested_key, nested_value in value.items():
            if nested_key not in result:
                result[nested_key] = []

            result[nested_key].append({
                'value': nested_value,
                'source': source
            })

    return result


# ============================================================================
# SPECIALIZED PATTERN EXTRACTORS
# ============================================================================

def extract_metadata_ids(metadata_category: Dict[str, Any]) -> Dict[str, Any]:
    """
    Specialized extractor for the 'data_metadata' category.

    Extracts all database IDs and URLs from both:
    - Nested 'metadata' field (contains gbif_key, iucn_taxon_id, etc.)
    - Top-level fields (aphia_id, worms_url, etc.)

    Args:
        metadata_category: The entire 'data_metadata' category dict

    Returns:
        Dictionary with all IDs and URLs found, with sources listed, or {} if empty

    Example:
        >>> metadata_cat = get_category(data, 'data_metadata')
        >>> ids = extract_metadata_ids(metadata_cat)
        >>> ids['gbif_key']
        2227300
        >>> ids['aphia_id']
        465540
        >>> ids['sources']
        ['GBIF', 'IUCN', 'WRiMS']
    """
    result = {}
    sources = set()

    # Extract from nested 'metadata' field
    metadata_field = get_field(metadata_category, 'metadata')
    if metadata_field:
        all_fields = extract_all_nested_fields(metadata_field)
        for field_name, entries in all_fields.items():
            if entries:
                result[field_name] = entries[0]['value']
                sources.add(entries[0]['source'])

    # Extract top-level ID fields
    id_fields = ['aphia_id', 'worms_url', 'gbif_url', 'iucn_url', 'data_source', 'found_in_worms']
    for field_name in id_fields:
        field_data = get_field(metadata_category, field_name)
        if field_data:
            values = extract_simple_values(field_data) if field_name in ['aphia_id', 'found_in_worms'] else get_all_values_with_sources(field_data)
            if values:
                result[field_name] = values[0]['value']
                sources.add(values[0]['source'])

    result['sources'] = sorted(list(sources))

    return result


def get_source_database_key(metadata_category: Dict[str, Any], source_name: str) -> Optional[Union[int, str]]:
    """
    Get the database key/ID for a specific source.

    Handles the complex lookup logic for different sources:
    - GBIF: Looks in nested 'metadata' field for 'gbif_key'
    - WRiMS: Looks in top-level 'aphia_id' field
    - IUCN: Looks in nested 'metadata' field for 'iucn_taxon_id'

    Args:
        metadata_category: The 'data_metadata' category dict
        source_name: Source name - "GBIF", "WRiMS", or "IUCN" (case-insensitive)

    Returns:
        The database key/ID, or None if not found

    Example:
        >>> metadata_cat = get_category(data, 'data_metadata')
        >>> gbif_key = get_source_database_key(metadata_cat, 'GBIF')
        >>> # Returns: 2227300
        >>> aphia_id = get_source_database_key(metadata_cat, 'WRiMS')
        >>> # Returns: 465540
        >>> iucn_id = get_source_database_key(metadata_cat, 'IUCN')
        >>> # Returns: 153877
    """
    source_upper = source_name.upper()

    # WRiMS uses top-level aphia_id field
    if source_upper == 'WRIMS':
        aphia_field = get_field(metadata_category, 'aphia_id')
        if aphia_field:
            values = extract_simple_values(aphia_field)
            if values:
                return values[0]['value']
        return None

    # GBIF and IUCN use nested metadata field
    metadata_field = get_field(metadata_category, 'metadata')
    all_fields = extract_all_nested_fields(metadata_field)

    if source_upper == 'GBIF':
        gbif_key_entries = all_fields.get('gbif_key', [])
        if gbif_key_entries:
            return gbif_key_entries[0]['value']

    elif source_upper == 'IUCN':
        iucn_id_entries = all_fields.get('iucn_taxon_id', [])
        if iucn_id_entries:
            return iucn_id_entries[0]['value']

    return None


def get_source_database_url(metadata_category: Dict[str, Any], source_name: str) -> Optional[str]:
    """
    Get the database URL for a specific source.

    Handles the complex lookup logic for different sources:
    - GBIF: Looks in nested 'metadata' field for 'gbif_url'
    - WRiMS: Looks in top-level 'worms_url' field
    - IUCN: Looks in nested 'metadata' field for 'iucn_url'

    Args:
        metadata_category: The 'data_metadata' category dict
        source_name: Source name - "GBIF", "WRiMS", or "IUCN" (case-insensitive)

    Returns:
        The database URL, or None if not found

    Example:
        >>> metadata_cat = get_category(data, 'data_metadata')
        >>> gbif_url = get_source_database_url(metadata_cat, 'GBIF')
        >>> # Returns: "https://www.gbif.org/species/2227300"
        >>> worms_url = get_source_database_url(metadata_cat, 'WRiMS')
        >>> # Returns: "https://www.marinespecies.org/aphia.php?p=taxdetails&id=465540"
        >>> iucn_url = get_source_database_url(metadata_cat, 'IUCN')
        >>> # Returns: "https://www.iucnredlist.org/search?searchType=species&query=..."
    """
    source_upper = source_name.upper()

    # WRiMS uses top-level worms_url field
    if source_upper == 'WRIMS':
        worms_url_field = get_field(metadata_category, 'worms_url')
        if worms_url_field:
            values = get_all_values_with_sources(worms_url_field)
            if values:
                return values[0]['value']
        return None

    # GBIF and IUCN use nested metadata field
    metadata_field = get_field(metadata_category, 'metadata')
    all_fields = extract_all_nested_fields(metadata_field)

    if source_upper == 'GBIF':
        gbif_url_entries = all_fields.get('gbif_url', [])
        if gbif_url_entries:
            return gbif_url_entries[0]['value']

    elif source_upper == 'IUCN':
        iucn_url_entries = all_fields.get('iucn_url', [])
        if iucn_url_entries:
            return iucn_url_entries[0]['value']

    return None


# ============================================================================
# CONVENIENCE WRAPPERS - Common use cases
# ============================================================================

def count_topic_stats(cat_data: dict) -> tuple:
    """
    Count data points and unique sources for one topic's field map.

    Args:
        cat_data: One topic's {field_name: [entry, ...]} dict, as returned by
                  categorized_fields.get(category_key, {}).

    Returns:
        (data_points: int, unique_sources: int)

    Example:
        >>> cat_data = categorized_fields.get("distribution", {})
        >>> pts, srcs = count_topic_stats(cat_data)
        >>> # Same numbers the KB dashboard shows for that topic card
    """
    pts = sum(len(v) for v in cat_data.values() if v)
    n_srcs = len({
        e.get("source", "")
        for vals in cat_data.values()
        for e in (vals if isinstance(vals, list) else [])
        if e and e.get("source")
    })
    return pts, n_srcs


def get_field_values(categorized_data: Optional[Dict[str, Any]],
                     category_name: str,
                     field_name: str) -> List[Dict[str, Any]]:
    """
    Convenience function to get field values in one call.

    Combines get_category + get_field + get_all_values_with_sources.

    Args:
        categorized_data: Full categorized JSON
        category_name: Category name
        field_name: Field name

    Returns:
        List of value entries with sources, or [] if not found

    Example:
        >>> data = load_categorized_data("Procambarus clarkii")
        >>> authorities = get_field_values(data, 'taxonomic_identity', 'authority')
        >>> authorities[0]['value']
        '(Girard, 1852)'
    """
    category = get_category(categorized_data, category_name)
    field = get_field(category, field_name)
    return get_all_values_with_sources(field)


# ============================================================================
# MODULE INFO
# ============================================================================

__all__ = [
    # Utility functions
    'load_categorized_data',
    'load_categorized_data_by_id',
    'get_category',
    'get_field',
    'get_species_folder',
    'load_category_file',
    'load_categories',
    'get_available_categories',
    # Array wrapper handlers
    'unwrap_field',
    'get_all_values_with_sources',
    # Pattern detection
    'detect_value_pattern',
    # Generic extractors
    'extract_simple_values',
    'extract_list_values',
    'extract_dict_values',
    # Nested navigation
    'extract_nested_field',
    'extract_all_nested_fields',
    # Source database helpers (specialized)
    'get_source_database_key',
    'get_source_database_url',
    # Convenience wrappers
    'get_field_values',
    'count_topic_stats',
    # Manual classification helpers
    'get_unknown_fields',
    'count_unknown_fields',
    'move_field_to_category',
    'save_categorized_data_by_id',
]


# =============================================================================
# MANUAL CLASSIFICATION HELPERS
# =============================================================================

def get_unknown_fields(categorized_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract all fields from the 'unknown' category for manual classification.

    Args:
        categorized_data: Full categorized JSON structure

    Returns:
        List of unknown fields with metadata:
        [
            {
                "field_name": str,
                "field_data": List[Dict],  # Original field array with value/source/etc
                "preview": str,  # Truncated preview of value for display
                "sources": List[str],  # List of sources (GBIF, WRiMS, IUCN)
                "data_type": str  # Type of first value
            },
            ...
        ]

    Example:
        >>> data = load_categorized_data("Procambarus clarkii")
        >>> unknown = get_unknown_fields(data)
        >>> len(unknown)
        5
        >>> unknown[0]['field_name']
        'authority'
    """
    if categorized_data is None:
        return []

    unknown_category = get_category(categorized_data, 'unknown')
    if not unknown_category:
        return []

    unknown_fields = []

    for field_name, field_data in unknown_category.items():
        if not isinstance(field_data, list) or not field_data:
            continue

        # Get first value for preview and type
        first_entry = field_data[0]
        value = first_entry.get('value', '')
        data_type = first_entry.get('data_type', 'unknown')

        # Create preview (truncate if needed)
        if value is None:
            preview = "null"
        elif isinstance(value, (list, dict)):
            preview_str = json.dumps(value)
            preview = preview_str[:100] + "..." if len(preview_str) > 100 else preview_str
        else:
            value_str = str(value)
            preview = value_str[:100] + "..." if len(value_str) > 100 else value_str

        # Collect all sources
        sources = [entry.get('source', 'Unknown') for entry in field_data if 'source' in entry]

        unknown_fields.append({
            "field_name": field_name,
            "field_data": field_data,
            "preview": preview,
            "sources": sources,
            "data_type": data_type
        })

    return unknown_fields


def count_unknown_fields(categorized_data: Optional[Dict[str, Any]]) -> int:
    """
    Count the number of fields in the 'unknown' category.

    Args:
        categorized_data: Full categorized JSON structure

    Returns:
        Number of uncategorized fields

    Example:
        >>> data = load_categorized_data("Procambarus clarkii")
        >>> count_unknown_fields(data)
        5
    """
    unknown_category = get_category(categorized_data, 'unknown')
    if not unknown_category:
        return 0
    return len([k for k, v in unknown_category.items() if isinstance(v, list) and v])


def move_field_to_category(
    categorized_data: Dict[str, Any],
    field_name: str,
    target_category: str
) -> Dict[str, Any]:
    """
    Move a field from 'unknown' category to a specific target category.
    Preserves source attribution and all metadata.

    Args:
        categorized_data: Full categorized JSON structure
        field_name: Name of field in unknown category to move
        target_category: Target category name (e.g., 'morphological_traits')

    Returns:
        Updated categorized_data structure

    Raises:
        ValueError: If field doesn't exist in unknown or target category is invalid

    Example:
        >>> data = load_categorized_data("Procambarus clarkii")
        >>> data = move_field_to_category(data, 'authority', 'taxonomic_identity')
        >>> 'authority' in get_category(data, 'unknown')
        False
        >>> 'authority' in get_category(data, 'taxonomic_identity')
        True
    """
    # Validate target category exists
    categorized_fields = categorized_data.get('categorized_fields', {})
    if target_category not in categorized_fields:
        raise ValueError(f"Invalid target category: {target_category}")

    # Get unknown category
    unknown_category = categorized_fields.get('unknown', {})
    if field_name not in unknown_category:
        raise ValueError(f"Field '{field_name}' not found in unknown category")

    # Get the field data
    field_data = unknown_category[field_name]

    # Move to target category
    if target_category not in categorized_fields:
        categorized_fields[target_category] = {}

    categorized_fields[target_category][field_name] = field_data

    # Remove from unknown
    del unknown_category[field_name]

    return categorized_data


def save_categorized_data_by_id(
    universal_id: str,
    categorized_data: Dict[str, Any],
    cache_dir: Optional[Path] = None
) -> bool:
    """
    Save categorized data using the new folder structure.

    Creates a species folder with manifest.json and separate category files.
    Only saves categories that have actual data (non-empty).

    Args:
        universal_id: Universal species identifier
        categorized_data: Full categorized data structure to save
        cache_dir: Optional custom cache directory path

    Returns:
        True if successful, False otherwise

    Example:
        >>> data = load_categorized_data_by_id("2227300_procambarus_clarkii")
        >>> data = move_field_to_category(data, 'authority', 'taxonomic_identity')
        >>> save_categorized_data_by_id("2227300_procambarus_clarkii", data)
        True
    """
    try:
        # Determine cache directory
        if cache_dir is None:
            cache_dir = get_default_cache_dir()

        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Create species folder
        species_folder = get_species_folder(universal_id, cache_dir)
        species_folder.mkdir(parents=True, exist_ok=True)

        # Extract metadata
        species_name = categorized_data.get('species_name', '')
        if not species_name:
            # Try to get from taxonomic_identity category
            taxonomic = categorized_data.get('categorized_fields', {}).get('taxonomic_identity', {})
            species_name_field = taxonomic.get('species_name', [])
            if species_name_field and isinstance(species_name_field, list) and species_name_field:
                species_name = species_name_field[0].get('value', '')

        timestamp = categorized_data.get('timestamp', '')
        sources = categorized_data.get('sources', [])
        categorized_fields = categorized_data.get('categorized_fields', {})

        # Determine which categories have data
        available_categories = []
        for category_name, category_fields in categorized_fields.items():
            if category_fields:  # Only include non-empty categories
                available_categories.append(category_name)

        # Create manifest.json
        manifest = {
            'universal_id': universal_id,
            'species_name': species_name,
            'timestamp': timestamp,
            'sources': sources,
            'available_categories': available_categories
        }

        manifest_path = species_folder / MANIFEST_FILENAME
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # Save each category to its own file (only non-empty ones)
        # Supports custom topics via fallback filename derivation
        for category_name in available_categories:
            category_file = CATEGORY_FILENAMES.get(category_name, f"{category_name}.json")
            category_path = species_folder / category_file
            category_content = {
                'category_name': category_name,
                'fields': categorized_fields[category_name]
            }
            with open(category_path, 'w', encoding='utf-8') as f:
                json.dump(category_content, f, indent=2, ensure_ascii=False)

        return True

    except Exception as e:
        print(f"Error saving categorized data: {e}")
        import traceback
        traceback.print_exc()
        return False
