#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
AquaNIS API Module
Interface for retrieving aquatic invasive species data from the AquaNIS database
Provides comprehensive information on introduced aquatic species with geographic and temporal data.

IMPORTANT: This module intentionally EXCLUDES taxonomy data from AquaNIS.
Rationale: AquaNIS taxonomic classifications should not be merged with other database sources.
Other databases (GBIF, WoRMS) provide more authoritative taxonomy.
By not extracting it, we ensure it never gets categorised or merged.

NEW DATA FIELDS (API v2):
- Dual pathway/vector terminology:
  * PathwaysVectorsAquaNIS: Original AquaNIS terminology (Pathway → Vectors)
  * PathwaysVectorsEASIN: Harmonised EASIN terminology for cross-database compatibility (Category → Subcategory)
- Hierarchical source region data:
  * Can contain Country, LME (Large Marine Ecosystem), Sea
  * Can contain Ocean, Ocean region
  * Multiple source regions can be associated with a single introduction record
"""

import requests
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Any, Optional
from haystack.tools import Tool

from functionalities.data_aggregation.api.api_data_utils import flatten_nested_fields
from core.utils.config_loader import get_secret, get_contact_email

# ============================================================================
# AQUANIS API CONFIGURATION
# ============================================================================
AQUANIS_API_BASE = "https://api.aquanisresearch.com"

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

def _get_aquanis_api_key() -> Optional[str]:
    """Retrieve AquaNIS API key using centralized config loader."""
    return get_secret("AQUANIS_API_KEY")


def _make_aquanis_request(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Internal helper to make a request to the AquaNIS API.
    Handles authentication and standard error handling.

    Args:
        endpoint: API endpoint path (without base URL)
        params: Optional query parameters

    Returns:
        Response JSON data or None on error
    """
    api_key = _get_aquanis_api_key()
    if not api_key:
        return None

    headers = HEADERS.copy()
    headers['Authorization'] = f'Bearer {api_key}'

    if params is None:
        params = {}

    try:
        url = f"{AQUANIS_API_BASE}/{endpoint}"
        response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making AquaNIS request to {endpoint}: {e}")
        return None


def _format_species_name_for_aquanis(species_name: str) -> str:
    """
    Format species name for AquaNIS API by replacing spaces with '+'.

    Args:
        species_name: Scientific species name (e.g., "Procambarus clarkii")

    Returns:
        Formatted name for URL (e.g., "Procambarus+clarkii")
    """
    formatted = species_name.strip().replace(' ', '+')
    return formatted


# ============================================================================
# DATA EXTRACTION FUNCTIONS
# ============================================================================

def get_species_data(species_name: str) -> Optional[Dict[str, Any]]:
    """
    Fetch basic species information from AquaNIS.

    Args:
        species_name: Scientific name of the species

    Returns:
        Species record dictionary or None if not found
    """
    try:
        formatted_name = _format_species_name_for_aquanis(species_name)
        endpoint = f"species/{formatted_name}"

        data = _make_aquanis_request(endpoint)

        if data:
            return data
        else:
            return None

    except Exception as e:
        print(f"Error fetching AquaNIS species data for {species_name}: {e}")
        return None


def _clean_introduction_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove taxonomic classification fields from a single introduction record.

    Removes 'Species' and 'Authority' fields to prevent AquaNIS taxonomy from
    being merged with authoritative sources during categorization.

    Args:
        record: Introduction record dictionary

    Returns:
        Cleaned record without taxonomic fields
    """
    cleaned = record.copy()
    # Remove taxonomic fields
    cleaned.pop('Species', None)
    cleaned.pop('Authority', None)
    return cleaned


def _clean_introduction_records(introductions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Clean introduction records by removing taxonomic classification fields.

    Handles both nested array structures and flat list structures.

    Args:
        introductions: List of introduction record dictionaries

    Returns:
        List of cleaned introduction records
    """
    cleaned_introductions = []

    for intro in introductions:
        # Handle nested structure with 'data' key (as seen in API response)
        if isinstance(intro, dict) and 'data' in intro:
            cleaned_intro = intro.copy()
            if isinstance(intro['data'], list):
                cleaned_intro['data'] = [_clean_introduction_record(rec) for rec in intro['data']]
            cleaned_introductions.append(cleaned_intro)
        # Handle flat structure (single introduction record)
        else:
            cleaned_introductions.append(_clean_introduction_record(intro))

    return cleaned_introductions


def _analyze_introduction_records(introductions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze introduction records to extract pathway and source region summary statistics.

    Args:
        introductions: List of introduction record dictionaries

    Returns:
        Dictionary with summary statistics about pathways and source regions
    """
    has_aquanis_pathways = False
    has_easin_pathways = False
    unique_source_regions = set()
    total_pathway_records = 0
    total_source_regions = 0

    for intro in introductions:
        # Check for PathwaysVectorsAquaNIS
        if 'PathwaysVectorsAquaNIS' in intro and intro['PathwaysVectorsAquaNIS']:
            has_aquanis_pathways = True
            total_pathway_records += len(intro['PathwaysVectorsAquaNIS'])

        # Check for PathwaysVectorsEASIN
        if 'PathwaysVectorsEASIN' in intro and intro['PathwaysVectorsEASIN']:
            has_easin_pathways = True

        # Check for SourceRegion
        if 'SourceRegion' in intro and intro['SourceRegion']:
            source_regions = intro['SourceRegion']
            if isinstance(source_regions, list):
                total_source_regions += len(source_regions)
                # Track unique regions (by converting each to a frozen representation)
                for region in source_regions:
                    if isinstance(region, dict):
                        # Create a hashable representation
                        region_key = tuple(sorted(region.items()))
                        unique_source_regions.add(region_key)

    return {
        'has_aquanis_pathways': has_aquanis_pathways,
        'has_easin_pathways': has_easin_pathways,
        'total_pathway_records': total_pathway_records,
        'total_source_regions': total_source_regions,
        'unique_source_regions_count': len(unique_source_regions)
    }


def get_introduction_records(species_name: str) -> List[Dict[str, Any]]:
    """
    Fetch introduction records for a species from AquaNIS.

    Each introduction record now includes enhanced data fields:
    - PathwaysVectorsAquaNIS: Original AquaNIS pathway terminology (Pathway → Vectors)
    - PathwaysVectorsEASIN: Harmonised EASIN terminology (Category → Subcategory)
    - SourceRegion: Array of hierarchical source regions (can contain Country, LME, Sea, Ocean, Ocean region)

    Args:
        species_name: Scientific name of the species

    Returns:
        List of introduction records with pathway and source region data (empty list if none found)
    """
    try:
        formatted_name = _format_species_name_for_aquanis(species_name)
        endpoint = f"introductions/{formatted_name}"

        data = _make_aquanis_request(endpoint)

        if data:
            # API returns {"data": [{...record1...}, ...]}
            if isinstance(data, list):
                introductions = data
            elif isinstance(data, dict):
                if 'data' in data and isinstance(data['data'], list):
                    # Standard API response: unwrap the nested data array
                    introductions = data['data']
                else:
                    introductions = data.get('introductions', [])
            else:
                introductions = []

            return introductions

        return []

    except Exception as e:
        print(f"Error fetching AquaNIS introduction records for {species_name}: {e}")
        return []


def _extract_introduction_subfields(introductions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extract categorically distinct sub-fields from introduction records into
    flat top-level lists. This allows direct_mappings in database_field_mapping.json
    to route them to the correct categories without AI involvement.

    Sub-fields extracted:
    - HabitatType     → strings, goes to habitat_ecology
    - Ports           → objects {PortName, DateFrom, DateTo}, goes to introduction_pathways
    - PortsVicinity   → objects {PortName, DateFrom, DateTo}, goes to introduction_pathways
    - SourceRegion    → objects {Country/LME/Sea/Ocean}, goes to distribution_and_status
    - PathwaysVectorsAquaNIS → objects, goes to introduction_pathways
    - PathwaysVectorsEASIN   → objects, goes to introduction_pathways

    Args:
        introductions: Cleaned introduction records

    Returns:
        Dict with one flat list per sub-field (only keys with data are included)
    """
    extracted: Dict[str, list] = {
        'habitat_types': [],
        'introduction_ports': [],
        'introduction_ports_vicinity': [],
        'source_regions': [],
        'pathways_aquanis': [],
        'pathways_easin': [],
    }

    for record in introductions:
        # HabitatType is a list of strings
        for val in record.get('HabitatType') or []:
            if val and val not in extracted['habitat_types']:
                extracted['habitat_types'].append(val)

        # Ports — array of {PortName, DateFrom, DateTo}
        extracted['introduction_ports'].extend(record.get('Ports') or [])

        # PortsVicinity — same structure as Ports
        extracted['introduction_ports_vicinity'].extend(record.get('PortsVicinity') or [])

        # SourceRegion — hierarchical geographic objects
        extracted['source_regions'].extend(record.get('SourceRegion') or [])

        # PathwaysVectorsAquaNIS
        extracted['pathways_aquanis'].extend(record.get('PathwaysVectorsAquaNIS') or [])

        # PathwaysVectorsEASIN
        extracted['pathways_easin'].extend(record.get('PathwaysVectorsEASIN') or [])

    # Drop empty lists so the output stays clean
    return {k: v for k, v in extracted.items() if v}


def get_comprehensive_aquanis_data(species_name: str) -> Dict[str, Any]:
    """
    Get comprehensive structured aquatic invasive species data from AquaNIS.

    IMPORTANT: Taxonomy data is intentionally EXCLUDED. AquaNIS taxonomy should not be
    merged with other authoritative sources (GBIF, WoRMS).

    Includes:
    - Basic species information (name, authority)
    - Array of introduction records (full nested structure preserved)
    - Flat extracted sub-fields from introduction records:
      * habitat_types        → list of habitat type strings (→ habitat_ecology)
      * introduction_ports   → list of port objects {PortName, DateFrom, DateTo} (→ introduction_pathways)
      * introduction_ports_vicinity → same structure as ports (→ introduction_pathways)
      * source_regions       → list of geographic source objects (→ distribution_and_status)
      * pathways_aquanis     → AquaNIS-terminology pathway objects (→ introduction_pathways)
      * pathways_easin       → EASIN-harmonised pathway objects (→ introduction_pathways)
    - Native range information
    - Invasion status and risk assessment
    - Metadata with pathway/source region summary statistics

    Args:
        species_name: Scientific name of the species

    Returns:
        Dictionary with comprehensive AquaNIS data (empty dict if species not found)
    """
    # Both calls take species_name directly — no ID needed from the first call
    # so they can run in parallel
    with ThreadPoolExecutor(max_workers=2) as executor:
        species_future = executor.submit(get_species_data, species_name)
        intros_future  = executor.submit(get_introduction_records, species_name)
        species_data   = species_future.result()
        introductions  = intros_future.result()

    if not species_data:
        return {}

    # Unwrap {"data": [{...}]} envelope — API wraps all responses in a data array
    species_record = species_data
    if isinstance(species_data.get('data'), list) and species_data['data']:
        species_record = species_data['data'][0]
    elif isinstance(species_data.get('data'), list) and not species_data['data']:
        return {}  # API responded but species not found

    # Clean introduction records to remove taxonomic fields
    # This prevents AquaNIS species names from being merged during categorization
    cleaned_introductions = _clean_introduction_records(introductions)

    aquanis_id = species_record.get('id') or species_record.get('AquaNISID')
    aquanis_url = species_record.get('Reference')
    if not aquanis_url and aquanis_id:
        aquanis_url = f"https://aquanisresearch.com/aquanis/species/view/id/{aquanis_id}"

    species_scientific_name = (species_record.get('Species') or
                               species_record.get('name') or
                               species_record.get('scientificName') or
                               species_name)

    # Analyze introduction records for pathway and source region data
    intro_analysis = _analyze_introduction_records(cleaned_introductions)

    # Extract categorically distinct sub-fields from introduction records into
    # flat top-level fields so direct_mappings can route them without AI
    intro_subfields = _extract_introduction_subfields(cleaned_introductions)

    # Structure the comprehensive data
    result = {
        'species_name': species_scientific_name,
        'authority': species_record.get('Authority'),

        # Distribution and invasion data
        'native_range': species_record.get('nativeRange') or species_record.get('NativeRange'),
        'introduction_records': cleaned_introductions,  # Use cleaned records without Species/Authority

        # Extracted introduction sub-fields (flat, for direct categorization)
        **intro_subfields,
        'invasion_status': species_record.get('invasionStatus') or species_record.get('InvasionStatus'),
        'risk_level': species_record.get('riskLevel') or species_record.get('RiskLevel'),
        'is_established': species_record.get('isEstablished', False) or species_record.get('IsEstablished', False),

        # Metadata
        'metadata': {
            'aquanis_id': aquanis_id,
            'aphia_id': species_record.get('AphiaID'),
            'aquanis_url': aquanis_url,
            'last_updated': species_record.get('lastUpdated') or species_record.get('LastUpdated'),
            'data_source': 'AquaNIS',
            'total_introductions': len(cleaned_introductions),
            # New pathway and source region summary statistics
            'has_aquanis_pathways': intro_analysis['has_aquanis_pathways'],
            'has_easin_pathways': intro_analysis['has_easin_pathways'],
            'total_pathway_records': intro_analysis['total_pathway_records'],
            'total_source_regions': intro_analysis['total_source_regions'],
            'unique_source_regions_count': intro_analysis['unique_source_regions_count']
        },

        # Keep full raw data for reference
        'raw_aquanis_data': species_data
    }

    return result


# ============================================================================
# DATA FLATTENING FUNCTION
# ============================================================================

# AquaNIS-specific configuration for flattening
_AQUANIS_DIRECT_FIELDS = [
    'species_name', 'authority', 'native_range', 'introduction_records',
    'invasion_status', 'risk_level', 'is_established'
]


def flatten_aquanis_data(aquanis_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten the AquaNIS data structure for better schema matching.

    Uses the shared flatten_nested_fields utility with AquaNIS-specific configuration.

    NOTE: Taxonomy data is intentionally excluded from AquaNIS extraction and flattening.
    Introduction records containing PathwaysVectorsAquaNIS, PathwaysVectorsEASIN, and
    SourceRegion arrays are preserved in their nested structure within 'introduction_records'.

    Args:
        aquanis_data: Raw AquaNIS data from get_comprehensive_aquanis_data()

    Returns:
        Flattened dictionary with metadata fields promoted to top level.
        Introduction records remain nested to preserve hierarchical pathway/source data.
    """
    return flatten_nested_fields(
        data=aquanis_data,
        direct_fields=_AQUANIS_DIRECT_FIELDS,
        nested_keys=['metadata']  # Removed 'taxonomy' from nested_keys
    )


# ============================================================================
# HAYSTACK COMPONENT FOR PIPELINE INTEGRATION
# ============================================================================

from haystack import component

@component
class AquaNISComponent:
    """
    AquaNIS Component that handles fetching and caching of aquatic invasive species data.
    Provides European aquatic invasion data including introduction records and risk assessment.
    """

    def __init__(self, use_ai_categorization: bool = True):
        """
        Initialize AquaNIS component.

        Note: raw_store must be set externally by the pipeline before use.
        This ensures session-isolated, species-specific cache paths are used.
        """
        self.raw_store = None  # Must be set by pipeline before use
        self.use_ai_categorization = use_ai_categorization

    @component.output_types(
        cached_data=Dict[str, Any],
        aquanis_data=Dict[str, Any],
        cache_status=str
    )
    def run(self, species_name: str, raw_store=None) -> Dict[str, Any]:
        """
        Fetch AquaNIS data and save as raw JSON for AI categorization.

        Args:
            species_name: Scientific name to query
            raw_store: RawDataStore instance (from SynonymCoordinator)

        Returns:
            Dictionary with cached_data, aquanis_data, and cache_status
        """
        try:

            # Use provided raw_store if available, otherwise use instance variable
            if raw_store is not None:
                self.raw_store = raw_store

            raw_aquanis_data = get_comprehensive_aquanis_data(species_name)

            if not raw_aquanis_data:
                return {
                    "cached_data": {},
                    "aquanis_data": {},
                    "cache_status": "no_data"
                }

            # Save raw data for AI categorization
            self.raw_store.save_raw_data(species_name, "AquaNIS", raw_aquanis_data)

            return {
                "cached_data": raw_aquanis_data,
                "aquanis_data": raw_aquanis_data,
                "cache_status": "raw_saved"
            }

        except Exception as e:
            print(f"Error in AquaNISComponent: {str(e)}")
            import traceback
            traceback.print_exc()
            return {
                "cached_data": {},
                "aquanis_data": {},
                "cache_status": "error"
            }


# ============================================================================
# HAYSTACK TOOL WRAPPER (Legacy Support)
# ============================================================================

aquanis_tool = Tool(
    name="get_aquanis_species_data",
    description="Get aquatic invasive species information from AquaNIS (Aquatic Neobiota Information System) including taxonomy, native range, introduction records with geographic and temporal data, invasion status, risk assessment, and establishment data. Returns structured data ready for database integration.",
    parameters={
        "species_name": {"type": "string", "description": "Scientific name of the aquatic species (e.g., 'Procambarus clarkii', 'Dreissena polymorpha')"}
    },
    function=get_comprehensive_aquanis_data
)
