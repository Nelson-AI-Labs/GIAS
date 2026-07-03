#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
JSON Loader Component
=====================

Haystack component that loads categorized species data from JSON files.
"""

from typing import Dict, List, Any
from haystack import component


@component
class JSONLoaderComponent:
    """
    Loads categorized species data from JSON cache.

    This component retrieves the categorized_fields JSON for a species,
    which contains all extracted and categorized data from databases and research papers.
    """

    def __init__(self):
        """Initialize the JSON loader component."""
        pass

    @component.output_types(
        categorized_data=Dict[str, Any],
        all_categories=List[str],
        sources=List[str],
        species_name=str,
        universal_id=str
    )
    def run(self, species_name: str, universal_id: str) -> Dict[str, Any]:
        """
        Load categorized JSON data for a species.

        Args:
            species_name: Scientific name of the species
            universal_id: Universal species identifier

        Returns:
            Dict with:
                - categorized_data: Full categorized_fields dict
                - all_categories: List of all category names
                - sources: List of data sources
                - species_name: Echo of input species name
                - universal_id: Echo of input universal ID
        """
        from core.dashboard.dashboard_tools import load_categorized_species_json

        try:
            # Load categorized data from JSON
            full_data = load_categorized_species_json(species_name, universal_id=universal_id)

            if not full_data:
                return {
                    'categorized_data': {},
                    'all_categories': [],
                    'sources': [],
                    'species_name': species_name,
                    'universal_id': universal_id
                }

            # Extract categorized fields
            categorized_fields = full_data.get('categorized_fields', {})
            sources = full_data.get('sources', [])
            all_categories = list(categorized_fields.keys())

            return {
                'categorized_data': categorized_fields,
                'all_categories': all_categories,
                'sources': sources,
                'species_name': species_name,
                'universal_id': universal_id
            }

        except Exception as e:
            print(f"ERROR JSONLoaderComponent: Failed to load data: {e}")
            import traceback
            traceback.print_exc()

            return {
                'categorized_data': {},
                'all_categories': [],
                'sources': [],
                'species_name': species_name,
                'universal_id': universal_id
            }


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Testing JSONLoaderComponent")
    print("=" * 40)

    loader = JSONLoaderComponent()

    # Test with a known species
    test_species = "Procambarus clarkii"
    test_id = "urn:lsid:marinespecies.org:taxname:606418"

    result = loader.run(species_name=test_species, universal_id=test_id)

    print(f"\nLoaded {len(result['all_categories'])} categories")
    print(f"Categories: {result['all_categories']}")
    print(f"Sources: {result['sources']}")
    print("\nJSONLoaderComponent test completed!")
