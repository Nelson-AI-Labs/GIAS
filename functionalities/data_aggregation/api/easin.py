#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
EASIN API Module
Interface for retrieving invasive species data from the European Alien Species Information Network (EASIN)
Provides EU-specific invasion data including pathways, impacts, distribution, and regulatory status.
"""

import requests
import json
import time
from typing import Dict, List, Any, Optional
from urllib.parse import quote
from haystack.tools import Tool

from functionalities.data_aggregation.api.api_data_utils import flatten_nested_fields
from core.utils.config_loader import get_contact_email

# ============================================================================
# EASIN API CONFIGURATION
# ============================================================================
EASIN_API_BASE = "https://easin.jrc.ec.europa.eu"
EASIN_CATALOG_API = f"{EASIN_API_BASE}/apixg/catxg"

# Request headers to be a good API citizen
HEADERS = {
    'User-Agent': f'GuardIAS/1.0 (contact: {get_contact_email()})',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

REQUEST_TIMEOUT = 30

# ============================================================================
# INTERNAL HELPER FUNCTIONS
# ============================================================================

def _get_easin_species_match(species_name: str) -> Optional[Dict[str, Any]]:
    """
    Internal helper to search for a species by name and get its EASIN ID.

    Args:
        species_name: Scientific name of the species

    Returns:
        First matching species record or None if not found
    """
    try:
        # Extract genus from species name for search
        genus = species_name.split()[0] if ' ' in species_name else species_name
        search_url = f"{EASIN_CATALOG_API}/term/{quote(genus)}"


        response = requests.get(search_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        if response.status_code == 200:
            results = response.json()

            if isinstance(results, list) and len(results) > 0:
                # Find exact match only - don't return data for a different species
                species_lower = species_name.lower().strip()
                for result in results:
                    if result.get('Name', '').lower().strip() == species_lower:
                        return result

                # If no exact match, return None to avoid returning data for wrong species
                return None

        return None

    except requests.exceptions.RequestException as e:
        print(f"Error searching EASIN for '{species_name}': {e}")
        return None
    except Exception as e:
        print(f"Unexpected error in EASIN search: {e}")
        return None


def _get_easin_species_by_id(easin_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed species information by EASIN ID.

    Args:
        easin_id: EASIN species identifier (format: R#####)

    Returns:
        Species data dictionary or None
    """
    try:
        id_url = f"{EASIN_CATALOG_API}/easinid/{easin_id}"


        response = requests.get(id_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        if response.status_code == 200:
            data = response.json()

            # API returns a list with single item
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            elif isinstance(data, dict):
                return data

        return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching EASIN ID {easin_id}: {e}")
        return None


# ============================================================================
# DATA EXTRACTION FUNCTIONS
# ============================================================================

def get_core_easin_data(species_name: str) -> Dict[str, Any]:
    """
    Get comprehensive invasive species data from EASIN.

    Includes:
    - Taxonomic information
    - EU regulatory status (EU Concern, Member State Concern)
    - Distribution in Europe
    - Introduction pathways (CBD classification)
    - Impact assessments by sector
    - First introduction data
    - Native range information

    Args:
        species_name: Scientific name of the species

    Returns:
        Dictionary with comprehensive EASIN data
    """
    # First, search for the species
    match_data = _get_easin_species_match(species_name)

    if not match_data:
        return {}

    easin_id = match_data.get('EASINID')

    if not easin_id:
        return {}

    # Get detailed data by ID (this ensures we have all fields)
    detailed_data = _get_easin_species_by_id(easin_id)

    if not detailed_data:
        # Fall back to match data if detailed fetch fails
        detailed_data = match_data

    # Debug logging
    easin_url = f"https://easin.jrc.ec.europa.eu/spexplorer/species/factsheet/{easin_id}" if easin_id else None

    # Structure the data
    result = {
        'species_name': detailed_data.get('Name'),
        'authorship': detailed_data.get('Authorship'),
        'easin_id': easin_id,
        'easin_url': easin_url,

        # Taxonomy
        'taxonomy': {
            'kingdom': detailed_data.get('Kingdom'),
            'phylum': detailed_data.get('Phylum'),
            'class': detailed_data.get('Class'),
            'order': detailed_data.get('Order'),
            'family': detailed_data.get('Family')
        },

        # Invasion status
        'status': detailed_data.get('Status'),  # A = Alien
        'has_impact': detailed_data.get('HasImpact', False),

        # EU regulatory status
        'is_eu_concern': detailed_data.get('IsEUConcern', False),
        'is_outermost_concern': detailed_data.get('IsOutermostConcern', False),
        'concerned_outermost_regions': detailed_data.get('ConcernedOutermostRegions', []),
        'is_ms_concern': detailed_data.get('IsMSConcern', False),
        'concerned_member_states': detailed_data.get('ConcernedMS', []),
        'is_horizon_scanning': detailed_data.get('IsHorizonScanning', False),

        # Distribution
        'first_introductions_in_eu': detailed_data.get('FirstIntroductionsInEU', []),
        'present_in_countries': detailed_data.get('PresentInCountries', []),
        'is_part_native': detailed_data.get('IsPartNative', False),
        'native_range': detailed_data.get('NativeRange'),

        # Introduction pathways
        'cbd_pathways': detailed_data.get('CBD_Pathways', []),

        # Impact data
        'impact_sources': detailed_data.get('ImpactSources', []),
        'impact_on_sectors': detailed_data.get('ImpactOnSectors', []),

        # Common names and synonyms
        'common_names': detailed_data.get('CommonNames', []),
        'synonyms': detailed_data.get('Synonyms', []),

        # Metadata
        'last_revision_date': detailed_data.get('LastRevisionDate'),

        # Keep full raw data for reference
        'raw_easin_data': detailed_data
    }

    return result


# ============================================================================
# DATA FLATTENING FUNCTION
# ============================================================================

# EASIN-specific configuration for flattening
_EASIN_DIRECT_FIELDS = [
    'species_name', 'authorship', 'easin_id', 'easin_url',
    'status', 'has_impact', 'is_eu_concern', 'is_outermost_concern',
    'concerned_outermost_regions', 'is_ms_concern', 'concerned_member_states',
    'is_horizon_scanning', 'first_introductions_in_eu', 'present_in_countries',
    'is_part_native', 'native_range', 'cbd_pathways', 'impact_sources',
    'impact_on_sectors', 'common_names', 'synonyms', 'last_revision_date'
]


def flatten_easin_data(easin_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten the EASIN data structure for better schema matching.

    Uses the shared flatten_nested_fields utility with EASIN-specific configuration.

    Args:
        easin_data: Raw EASIN data from get_core_easin_data()

    Returns:
        Flattened dictionary
    """
    return flatten_nested_fields(
        data=easin_data,
        direct_fields=_EASIN_DIRECT_FIELDS,
        nested_keys=['taxonomy']  # EASIN doesn't have a metadata dict to flatten
    )


# ============================================================================
# HAYSTACK COMPONENT FOR PIPELINE INTEGRATION
# ============================================================================

from haystack import component

@component
class EASINComponent:
    """
    EASIN Component that handles fetching and caching of European invasive species data.
    Provides EU-specific information on invasion status, pathways, impacts, and regulations.
    """

    def __init__(self, use_ai_categorization: bool = True):
        """
        Initialize EASIN component.

        Note: raw_store must be set externally by the pipeline before use.
        This ensures session-isolated, species-specific cache paths are used.
        """
        self.raw_store = None  # Must be set by pipeline before use
        self.use_ai_categorization = use_ai_categorization

    @component.output_types(
        cached_data=Dict[str, Any],
        easin_data=Dict[str, Any],
        cache_status=str
    )
    def run(self, species_name: str, raw_store=None) -> Dict[str, Any]:
        """
        Fetch EASIN data and save as raw JSON for AI categorization.

        Args:
            species_name: Scientific name to query
            raw_store: RawDataStore instance (from SynonymCoordinator)

        Returns:
            Dictionary with cached_data, easin_data, and cache_status
        """
        try:

            # Use provided raw_store if available
            if raw_store is not None:
                self.raw_store = raw_store

            raw_easin_data = get_core_easin_data(species_name)

            if not raw_easin_data:
                return {
                    "cached_data": {},
                    "easin_data": {},
                    "cache_status": "no_data"
                }

            # Save raw data for AI categorization
            self.raw_store.save_raw_data(species_name, "EASIN", raw_easin_data)

            return {
                "cached_data": raw_easin_data,
                "easin_data": raw_easin_data,
                "cache_status": "raw_saved"
            }

        except Exception as e:
            print(f"Error in EASINComponent: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "cached_data": {},
                "easin_data": {},
                "cache_status": "error"
            }


# ============================================================================
# HAYSTACK TOOL WRAPPER (Legacy Support)
# ============================================================================

easin_tool = Tool(
    name="get_easin_species_data",
    description="Get invasive species information from EASIN (European Alien Species Information Network) including EU regulatory status, invasion pathways (CBD classification), impact assessments by sector, distribution in Europe, first introduction dates, and native range information",
    parameters={
        "species_name": {"type": "string", "description": "Scientific name of the species (e.g., 'Procambarus clarkii')"}
    },
    function=get_core_easin_data
)


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    import sys

    # Check if a species name was provided
    if len(sys.argv) > 1:
        species_to_test = sys.argv[1]
    else:
        # Default: red swamp crayfish (known to be in EASIN)
        species_to_test = "Procambarus clarkii"

    print(f"--- Running EASIN Data test for: '{species_to_test}' ---\n")

    # Call the main function
    species_data = get_core_easin_data(species_to_test)

    # Print results
    if species_data:
        print("\n--- Successfully retrieved data from EASIN: ---")
        print(json.dumps(species_data, indent=4))
    else:
        print(f"\n--- No data found for: '{species_to_test}' ---")
