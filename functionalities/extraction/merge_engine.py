# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Merge Engine for Research Data
================================

This module handles merging extracted research data (from PDFs) into categorized_data JSON files.

Workflow:
1. Scan extracted_data directory for extraction files
2. Convert extracted format {value, reasoning} to categorized format
3. Deduplicate against existing entries
4. Map research topics to dashboard categories
5. Merge into categorized_data and save

"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from core.cache_layer.categorized_data_helpers import load_categorized_data_by_id, save_categorized_data_by_id

# Path configuration (session-aware via centralized cache manager)
from core.utils.cache_manager import get_extracted_data_dir, get_categorized_data_dir

# Import topic registry for normalization
from core.registries.topic_registry import StandardTopicRegistry


def detect_data_type(value: Any) -> str:
    """
    Detect the data type of a value.

    Args:
        value: The value to inspect

    Returns:
        String indicating type: "null", "boolean", "number", "string", "list", "dict"
    """
    if value is None:
        return "null"
    elif isinstance(value, bool):
        return "boolean"
    elif isinstance(value, (int, float)):
        return "number"
    elif isinstance(value, str):
        return "string"
    elif isinstance(value, list):
        return "list"
    elif isinstance(value, dict):
        return "dict"
    else:
        return "string"


def normalize_value(value: Any) -> str:
    """
    Normalize a value for comparison in deduplication.

    Args:
        value: The value to normalize

    Returns:
        Normalized string representation
    """
    if isinstance(value, str):
        return value.strip().lower()
    elif isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    else:
        return str(value)


def map_research_topic_to_category(research_topic: str, topic_type: str = "standard") -> str:
    """
    Map a research topic name to its corresponding category name.

    For standard topics, uses StandardTopicRegistry for normalization.
    For custom topics, directly converts to snake_case format.

    Args:
        research_topic: Topic name (e.g., "morphological traits" or "Economic impact")
        topic_type: "standard" or "custom" (default: "standard")

    Returns:
        Category name (e.g., "biological_traits" or "economic_impact")

    Raises:
        ValueError: If standard topic cannot be mapped
    """
    # Handle custom topics - directly normalize to snake_case
    if topic_type == "custom":
        return research_topic.lower().replace(' ', '_').replace('&', '').replace('__', '_')

    # Handle standard topics - use registry
    normalized = StandardTopicRegistry.normalize_topic_name(research_topic)

    if normalized:
        return normalized

    # Topic not recognized
    raise ValueError(
        f"Cannot map research topic '{research_topic}' to a category. "
        f"Valid topics: {StandardTopicRegistry.get_all_topic_keys()}"
    )


def convert_extracted_field_to_categorized(
    field_name: str,
    field_data: Dict[str, Any],
    metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Convert an extracted field to categorized format.

    Args:
        field_name: Name of the field
        field_data: Dict with 'value' and 'reasoning' keys
        metadata: Extraction metadata (source_title, extraction_timestamp, etc.)

    Returns:
        Dict in categorized format with value, data_type, source, etc.
    """
    value = field_data.get('value')
    reasoning = field_data.get('reasoning', '')

    entry = {
        'value': value,
        'data_type': detect_data_type(value),
        'source': metadata.get('source_title', 'Research Source'),
        'categorization_method': 'ai',
        'ai_reasoning': reasoning,
        'extraction_timestamp': metadata.get('extraction_timestamp'),
        'is_research_data': True
    }

    # Propagate verification quality metadata when available
    if 'verification_confidence' in field_data:
        entry['verification_confidence'] = field_data['verification_confidence']
    if 'verification_verdict' in field_data:
        entry['verification_verdict'] = field_data['verification_verdict']

    return entry


def is_duplicate(new_entry: Dict[str, Any], existing_entries: List[Dict[str, Any]]) -> bool:
    """
    Check if a new entry is a duplicate of existing entries.

    Duplicate = same source AND same normalized value

    Args:
        new_entry: Entry to check
        existing_entries: List of existing entries for this field

    Returns:
        True if duplicate found, False otherwise
    """
    new_source = new_entry['source']
    new_value = normalize_value(new_entry['value'])

    for existing in existing_entries:
        if existing['source'] == new_source:
            if normalize_value(existing['value']) == new_value:
                return True

    return False


def scan_extracted_data(universal_id: str, species_name: str) -> Dict[str, List[Path]]:
    """
    Scan extracted_data directory and group topic extraction files by topic.

    Skips context extraction files (extraction_type: "context") — those capture
    study metadata (geographic location, population, methodology) and are not
    merged into dashboard categories.

    Args:
        universal_id: Universal species ID
        species_name: Species name (not currently used, for future compatibility)

    Returns:
        Dict mapping topic names to list of extraction file paths
    """
    extracted_dir = get_extracted_data_dir() / universal_id

    if not extracted_dir.exists():
        return {}

    topic_files = {}

    # Search recursively through per-source subdirectories
    for file_path in extracted_dir.glob('**/*_extraction.json'):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            metadata = data.get('metadata', {})

            # Skip context extraction files — they don't map to dashboard categories
            if metadata.get('extraction_type') == 'context':
                continue

            topic = metadata.get('research_topic', 'unknown')

            if topic not in topic_files:
                topic_files[topic] = []

            topic_files[topic].append(file_path)

        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            continue

    return topic_files


def merge_extraction_file_into_categorized(
    extraction_file: Path,
    categorized_data: Dict[str, Any]
) -> Tuple[int, int]:
    """
    Merge a single extraction file into categorized data.

    Args:
        extraction_file: Path to extraction JSON file
        categorized_data: Categorized data dict (modified in place)

    Returns:
        Tuple of (fields_added, fields_skipped)

    Raises:
        ValueError: If topic cannot be mapped or file is invalid
    """
    # Load extraction file
    with open(extraction_file, 'r', encoding='utf-8') as f:
        extraction = json.load(f)

    metadata = extraction.get('metadata', {})
    extracted_data = extraction.get('extracted_data', {})

    # Map topic to category
    research_topic = metadata.get('research_topic', 'unknown')
    topic_type = metadata.get('topic_type', 'standard')  # Get topic type from metadata
    category_name = map_research_topic_to_category(research_topic, topic_type)

    # Get source name for tracking
    source_name = metadata.get('source_title', 'Research Source')

    # Update sources list if not present
    if source_name not in categorized_data.get('sources', []):
        if 'sources' not in categorized_data:
            categorized_data['sources'] = []
        categorized_data['sources'].append(source_name)

    # Ensure category exists
    if 'categorized_fields' not in categorized_data:
        categorized_data['categorized_fields'] = {}

    if category_name not in categorized_data['categorized_fields']:
        categorized_data['categorized_fields'][category_name] = {}

    category_dict = categorized_data['categorized_fields'][category_name]

    # Merge each field
    fields_added = 0
    fields_skipped = 0

    for field_name, field_data in extracted_data.items():
        # Convert to categorized format
        new_entry = convert_extracted_field_to_categorized(field_name, field_data, metadata)

        # Initialize field array if doesn't exist
        if field_name not in category_dict:
            category_dict[field_name] = []

        # Check for duplicates
        if is_duplicate(new_entry, category_dict[field_name]):
            fields_skipped += 1
        else:
            category_dict[field_name].append(new_entry)
            fields_added += 1

    return fields_added, fields_skipped


def merge_extracted_data_dict(
    extracted_data: Dict[str, Any],
    metadata: Dict[str, Any],
    categorized_data: Dict[str, Any],
    rejected_fields: set = None
) -> Tuple[int, int]:
    """
    Merge an in-memory extracted_data dict into categorized data.
    Used for per-source merges where the caller controls which fields to include.

    Args:
        extracted_data: {field_name: {value, reasoning}, ...}
        metadata: Extraction metadata (research_topic, source_title, topic_type, etc.)
        categorized_data: Categorized data dict (modified in place)
        rejected_fields: Set of field names to exclude (opt-out facts)

    Returns:
        Tuple of (fields_added, fields_skipped)
    """
    rejected_fields = rejected_fields or set()

    research_topic = metadata.get('research_topic', 'unknown')
    topic_type = metadata.get('topic_type', 'standard')
    category_name = map_research_topic_to_category(research_topic, topic_type)

    source_name = metadata.get('source_title', 'Research Source')

    if source_name not in categorized_data.get('sources', []):
        if 'sources' not in categorized_data:
            categorized_data['sources'] = []
        categorized_data['sources'].append(source_name)

    if 'categorized_fields' not in categorized_data:
        categorized_data['categorized_fields'] = {}

    if category_name not in categorized_data['categorized_fields']:
        categorized_data['categorized_fields'][category_name] = {}

    category_dict = categorized_data['categorized_fields'][category_name]

    fields_added = 0
    fields_skipped = 0

    for field_name, field_data in extracted_data.items():
        if field_name in rejected_fields:
            continue

        new_entry = convert_extracted_field_to_categorized(field_name, field_data, metadata)

        if field_name not in category_dict:
            category_dict[field_name] = []

        if is_duplicate(new_entry, category_dict[field_name]):
            fields_skipped += 1
        else:
            category_dict[field_name].append(new_entry)
            fields_added += 1

    return fields_added, fields_skipped


def merge_all_extracted_data(
    universal_id: str,
    species_name: str,
    selected_topics: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Merge all extracted data into categorized data.

    Args:
        universal_id: Universal species ID
        species_name: Species name
        selected_topics: Optional list of topics to merge (None = merge all)

    Returns:
        Dict with results: {
            'status': 'success' | 'error',
            'total_fields_added': int,
            'total_fields_skipped': int,
            'topics_processed': int,
            'topic_results': {...},
            'error': str (if error)
        }
    """
    try:
        # Load existing categorized data (session-aware - don't pass cache_dir)
        categorized_data = load_categorized_data_by_id(universal_id)

        if not categorized_data:
            return {
                'status': 'error',
                'error': f"Categorized data not found for species: {universal_id}"
            }

        # Scan for extraction files
        topic_files = scan_extracted_data(universal_id, species_name)

        if not topic_files:
            return {
                'status': 'error',
                'error': 'No extracted data files found'
            }

        # Filter by selected topics if provided
        if selected_topics:
            topic_files = {k: v for k, v in topic_files.items() if k in selected_topics}

        # Merge each file
        topic_results = {}
        total_fields_added = 0
        total_fields_skipped = 0

        for topic, files in topic_files.items():
            topic_added = 0
            topic_skipped = 0

            for file_path in files:
                try:
                    added, skipped = merge_extraction_file_into_categorized(file_path, categorized_data)
                    topic_added += added
                    topic_skipped += skipped
                except Exception as e:
                    topic_results[topic] = {
                        'status': 'error',
                        'error': str(e)
                    }
                    continue

            topic_results[topic] = {
                'status': 'success',
                'fields_added': topic_added,
                'fields_skipped': topic_skipped,
                'files_processed': len(files)
            }

            total_fields_added += topic_added
            total_fields_skipped += topic_skipped

        # Save updated categorized data (session-aware - don't pass cache_dir)
        save_categorized_data_by_id(universal_id, categorized_data)

        # Re-run geo-normalization to pick up any new distribution text from extraction
        from core.services.geo_normalizer import GeoNormalizationService
        GeoNormalizationService().normalize_distribution(universal_id)

        return {
            'status': 'success',
            'total_fields_added': total_fields_added,
            'total_fields_skipped': total_fields_skipped,
            'topics_processed': len(topic_results),
            'topic_results': topic_results
        }

    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }
