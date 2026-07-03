# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Shared utility functions for API data processing.

This module provides centralized data flattening and transformation logic
used across all API modules (GBIF, AquaNIS, EASIN, IUCN).
"""

from typing import Any, Callable, Dict, List, Optional


def flatten_nested_fields(
    data: Dict[str, Any],
    direct_fields: List[str],
    nested_keys: List[str] = None,
    field_mappings: Dict[str, Dict[str, str]] = None,
    custom_processors: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], None]] = None
) -> Dict[str, Any]:
    """
    Centralized flattening logic for all API responses.

    This function handles the common pattern of:
    1. Copying direct top-level fields
    2. Flattening nested dictionaries into the top level
    3. Applying field name mappings during flattening
    4. Running custom processors for complex transformations

    Args:
        data: Raw API response data
        direct_fields: List of top-level fields to copy directly
        nested_keys: Keys whose dicts should be flattened into top level.
                     Defaults to ['taxonomy', 'metadata']
        field_mappings: Optional dict mapping nested_key -> {source_field: target_field}
                        for renaming fields during flattening
        custom_processors: Optional dict mapping key -> callable(source_dict, flattened_dict)
                           for complex transformations that can't be handled by simple flattening

    Returns:
        Flattened dictionary with all fields at top level

    Example:
        >>> data = {
        ...     'species_name': 'Homo sapiens',
        ...     'taxonomy': {'kingdom': 'Animalia', 'phylum': 'Chordata'},
        ...     'metadata': {'gbif_key': 123, 'url': 'https://...'}
        ... }
        >>> flatten_nested_fields(
        ...     data,
        ...     direct_fields=['species_name'],
        ...     nested_keys=['taxonomy', 'metadata']
        ... )
        {'species_name': 'Homo sapiens', 'kingdom': 'Animalia', 'phylum': 'Chordata',
         'gbif_key': 123, 'url': 'https://...'}
    """
    if nested_keys is None:
        nested_keys = ['taxonomy', 'metadata']

    flattened = {}

    # Copy direct fields
    for field in direct_fields:
        if field in data:
            flattened[field] = data[field]

    # Flatten nested dictionaries
    for key in nested_keys:
        if key in data and isinstance(data[key], dict):
            nested_dict = data[key]
            mappings = field_mappings.get(key, {}) if field_mappings else {}

            for nested_field, nested_value in nested_dict.items():
                # Apply field mapping if specified, otherwise use original name
                target_field = mappings.get(nested_field, nested_field)

                # Avoid overwriting existing keys
                if target_field not in flattened:
                    flattened[target_field] = nested_value

    # Run custom processors for complex transformations
    if custom_processors:
        for key, processor in custom_processors.items():
            if key in data and isinstance(data[key], dict):
                processor(data[key], flattened)

    return flattened


def flatten_with_get(
    source_dict: Dict[str, Any],
    target_dict: Dict[str, Any],
    field_mappings: Dict[str, str]
) -> None:
    """
    Flatten fields from source to target using .get() with specified mappings.

    This is useful for custom processors that need to extract specific fields
    with potential renaming and None as default.

    Args:
        source_dict: Source dictionary to extract from
        target_dict: Target dictionary to populate
        field_mappings: Dict mapping source_field -> target_field
    """
    for source_field, target_field in field_mappings.items():
        target_dict[target_field] = source_dict.get(source_field)


def transform_list_field(
    data: Dict[str, Any],
    field_name: str,
    key_mappings: Dict[str, str]
) -> List[Any]:
    """
    Transform a list field by renaming keys in each dict item.

    Used for cases like IUCN habitats where camelCase needs to become snake_case.

    Args:
        data: Data containing the list field
        field_name: Name of the list field to transform
        key_mappings: Dict mapping old_key -> new_key for transformation

    Returns:
        Transformed list, or empty list if field doesn't exist
    """
    items = data.get(field_name, [])
    if not isinstance(items, list):
        return items

    transformed = []
    for item in items:
        if isinstance(item, dict):
            transformed_item = {}
            for key, value in item.items():
                new_key = key_mappings.get(key, key)
                transformed_item[new_key] = value
            transformed.append(transformed_item)
        else:
            transformed.append(item)

    return transformed
