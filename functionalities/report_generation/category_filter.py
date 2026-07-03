#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Category Filter Component
=========================

Haystack component that filters categorized data to selected categories.
"""

from typing import Dict, List, Any
from haystack import component


@component
class CategoryFilterComponent:
    """
    Filters categorized species data to only selected categories.

    This component takes the full categorized_fields dict and returns only
    the categories that the user has selected for the report.
    """

    def __init__(self):
        """Initialize the category filter component."""
        pass

    @component.output_types(
        filtered_data=Dict[str, Any],
        categories_included=List[str]
    )
    def run(self, categorized_data: Dict[str, Any], selected_categories: List[str]) -> Dict[str, Any]:
        """
        Filter categorized data to selected categories.

        Args:
            categorized_data: Full categorized_fields dict (all categories)
            selected_categories: List of category names to include in report

        Returns:
            Dict with:
                - filtered_data: Dict containing only selected categories
                - categories_included: List of categories that were found and included
        """
        try:
            if not selected_categories:
                return {
                    'filtered_data': {},
                    'categories_included': []
                }

            if not categorized_data:
                return {
                    'filtered_data': {},
                    'categories_included': []
                }

            # Filter to only selected categories
            filtered_data = {}
            categories_included = []

            for category in selected_categories:
                if category in categorized_data:
                    filtered_data[category] = categorized_data[category]
                    categories_included.append(category)

            return {
                'filtered_data': filtered_data,
                'categories_included': categories_included
            }

        except Exception as e:
            print(f"ERROR CategoryFilterComponent: Filtering failed: {e}")
            import traceback
            traceback.print_exc()

            return {
                'filtered_data': {},
                'categories_included': []
            }


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Testing CategoryFilterComponent")
    print("=" * 40)

    # Create mock data
    mock_data = {
        'taxonomic_identity': {'field1': ['data']},
        'morphological_traits': {'field2': ['data']},
        'distribution': {'field3': ['data']},
        'impacts': {'field4': ['data']}
    }

    filter_component = CategoryFilterComponent()

    # Test 1: Filter to subset
    result = filter_component.run(
        categorized_data=mock_data,
        selected_categories=['taxonomic_identity', 'distribution', 'impacts']
    )

    print(f"\nTest 1: Filtered to {len(result['categories_included'])} categories")
    print(f"Included: {result['categories_included']}")

    # Test 2: Empty selection
    result2 = filter_component.run(
        categorized_data=mock_data,
        selected_categories=[]
    )

    print(f"\nTest 2: Empty selection -> {len(result2['categories_included'])} categories")

    print("\nCategoryFilterComponent test completed!")
