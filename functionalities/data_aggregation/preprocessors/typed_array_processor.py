# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Typed Array Processor for Database Field Mapping

This module handles splitting of typed arrays (like GBIF descriptions or WRiMS attributes)
based on discriminator fields and routing items to appropriate schema categories.
"""

from typing import Dict, List, Any, Tuple
import logging

logger = logging.getLogger(__name__)


class TypedArrayProcessor:
    """
    Processes typed arrays by splitting them based on discriminator fields
    and routing items to appropriate categories using database_field_mapping.json
    """

    def __init__(self):
        """Initialize the typed array processor."""
        pass

    def split_typed_array(
        self,
        array_data: List[Dict[str, Any]],
        array_config: Dict[str, Any],
        database_name: str,
        field_name: str
    ) -> Dict[str, Any]:
        """
        Split array by discriminator field and route to categories.

        Args:
            array_data: List of items (descriptions or attributes)
            array_config: Config from database_field_mapping.json typed_arrays section
            database_name: Source database (GBIF, WRiMS, etc.)
            field_name: Original field name (descriptions, attributes, etc.)

        Returns:
            Dictionary with structure:
            {
                'categorized': {
                    'category_name': [(item, metadata), ...],
                    ...
                },
                'unmapped': [(item, discriminator_value), ...],
                'multi_category': [(item, categories_list, discriminator_value), ...]
            }
        """
        discriminator = array_config.get('discriminator')
        mappings = array_config.get('mappings', {})

        if not discriminator:
            logger.error(f"No discriminator specified for typed array: {field_name}")
            return {
                'categorized': {},
                'unmapped': [(item, None) for item in array_data],
                'multi_category': []
            }

        categorized = {}
        unmapped = []
        multi_category = []

        for item in array_data:
            disc_value = item.get(discriminator)

            if disc_value is None:
                logger.warning(
                    f"Item in {database_name}.{field_name} missing discriminator "
                    f"field '{discriminator}': {item}"
                )
                unmapped.append((item, None))
                continue

            if disc_value not in mappings:
                # Unknown type - needs AI categorization
                logger.debug(
                    f"Unmapped {discriminator} value in {database_name}.{field_name}: "
                    f"'{disc_value}'"
                )
                unmapped.append((item, disc_value))
            elif isinstance(mappings[disc_value], list):
                # Multi-category mapping - send to AI to decide
                logger.debug(
                    f"Multi-category mapping for {database_name}.{field_name} "
                    f"'{disc_value}': {mappings[disc_value]}"
                )
                multi_category.append((item, mappings[disc_value], disc_value))
            else:
                # Single category mapping - route directly
                category = mappings[disc_value]

                # Create metadata for this item
                metadata = self._create_item_metadata(
                    database_name,
                    field_name,
                    disc_value
                )

                if category not in categorized:
                    categorized[category] = []

                categorized[category].append((item, metadata))

        logger.info(
            f"Split {database_name}.{field_name}: "
            f"{sum(len(items) for items in categorized.values())} categorized, "
            f"{len(unmapped)} unmapped, "
            f"{len(multi_category)} multi-category"
        )

        return {
            'categorized': categorized,
            'unmapped': unmapped,
            'multi_category': multi_category
        }

    def _create_item_metadata(
        self,
        database_name: str,
        field_name: str,
        discriminator_value: str
    ) -> Dict[str, str]:
        """
        Create metadata tracking object for a categorized item.

        Args:
            database_name: Source database (GBIF, WRiMS, etc.)
            field_name: Original field name before splitting
            discriminator_value: The discriminator value used for routing

        Returns:
            Metadata dictionary with source tracking info
        """
        return {
            'source': database_name,
            'original_field': field_name,
            'discriminator_type': discriminator_value
        }

    def handle_special_cases(
        self,
        array_data: List[Dict[str, Any]],
        special_handling_config: Dict[str, Any],
        database_name: str,
        field_name: str,
        discriminator_field: str
    ) -> Tuple[List[Tuple[Dict, Dict]], List[Dict]]:
        """
        Handle special handling cases defined in database_field_mapping.json

        Args:
            array_data: Array of items to check
            special_handling_config: special_handling section from mapping
            database_name: Source database
            field_name: Field name
            discriminator_field: Name of discriminator field (e.g., 'type')

        Returns:
            Tuple of (special_items_with_metadata, remaining_items)
            special_items_with_metadata: List of (item, metadata) tuples for special cases
            remaining_items: Items that don't match special handling rules
        """
        special_items = []
        remaining_items = []

        action = special_handling_config.get('action', '')
        condition = special_handling_config.get('condition', '')

        # Parse condition - currently supports simple equality checks
        # Format: "type == 'Introduced species remark' OR type == 'Notes'"
        special_types = self._parse_special_condition(condition, discriminator_field)

        for item in array_data:
            disc_value = item.get(discriminator_field)

            if disc_value in special_types:
                # Determine target category from action
                target_category = self._parse_action_category(action)

                metadata = self._create_item_metadata(
                    database_name,
                    field_name,
                    disc_value
                )
                metadata['note'] = 'Mixed content - flagged by special_handling rules'
                metadata['special_handling'] = True

                special_items.append((item, metadata, target_category))
                logger.debug(
                    f"Special handling: {database_name}.{field_name} "
                    f"'{disc_value}' → {target_category}"
                )
            else:
                remaining_items.append(item)

        return special_items, remaining_items

    def _parse_special_condition(
        self,
        condition: str,
        discriminator_field: str
    ) -> List[str]:
        """
        Parse special_handling condition string to extract values.

        Args:
            condition: Condition string (e.g., "type == 'Notes' OR type == 'Remark'")
            discriminator_field: Field name to match against

        Returns:
            List of discriminator values that match the condition
        """
        # Simple parser for equality conditions
        # Supports: "field == 'value1' OR field == 'value2'"
        values = []

        if not condition:
            return values

        parts = condition.split(' OR ')
        for part in parts:
            part = part.strip()
            if '==' in part:
                field, value = part.split('==', 1)
                field = field.strip()
                value = value.strip().strip("'\"")

                if field == discriminator_field:
                    values.append(value)

        return values

    def _parse_action_category(self, action: str) -> str:
        """
        Parse action string to extract target category.

        Args:
            action: Action string (e.g., "map_to_impacts" or "Map to 'impacts' (primary)...")

        Returns:
            Category name
        """
        # Handle different action formats
        if action.startswith('map_to_'):
            return action.replace('map_to_', '')

        # Handle format: "Map to 'category' (primary)..."
        if "Map to '" in action or 'Map to "' in action:
            start = action.find("'") if "'" in action else action.find('"')
            if start != -1:
                end = action.find("'", start + 1) if "'" in action else action.find('"', start + 1)
                if end != -1:
                    return action[start + 1:end]

        # Default to impacts for unrecognized format
        logger.warning(f"Could not parse action category from: {action}, defaulting to 'impacts'")
        return 'impacts'


def create_typed_array_processor() -> TypedArrayProcessor:
    """
    Factory function to create a TypedArrayProcessor instance.

    Returns:
        TypedArrayProcessor instance
    """
    return TypedArrayProcessor()
