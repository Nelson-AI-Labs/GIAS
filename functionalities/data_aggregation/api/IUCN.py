#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
IUCN Comprehensive Species Data Retrieval Module
Standalone module for retrieving conservation status, population trends, threats,
habitats, and conservation measures from the IUCN Red List API, wrapped for Haystack.
Focuses on data essential for assessing a species' conservation profile.
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional

from functionalities.data_aggregation.api.api_data_utils import (
    flatten_nested_fields,
    flatten_with_get,
    transform_list_field
)
from core.utils.config_loader import get_secret, get_contact_email

# ============================================================================
# IUCN API CONFIGURATION
# ============================================================================
IUCN_API_BASE = "https://api.iucnredlist.org/api/v4"
# Set a user-agent to be a good internet citizen.
HEADERS = {
    "User-Agent": f"GuardIAS/1.0 (contact: {get_contact_email()})"
}
# Standard timeout for all API requests to prevent hanging
REQUEST_TIMEOUT = 15

# ============================================================================
# INTERNAL HELPER FUNCTIONS
# ============================================================================

def _get_iucn_api_key() -> Optional[str]:
    """Retrieves the IUCN API token using centralized config loader."""
    return get_secret("IUCN_API_KEY")

def _make_iucn_request(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Internal helper to make a request to the IUCN v4 API."""
    token = _get_iucn_api_key()
    if not token:
        return None

    # v4 API uses Bearer token authentication in headers
    headers = HEADERS.copy()
    headers['Authorization'] = f'Bearer {token}'
    
    if params is None:
        params = {}
    
    try:
        response = requests.get(f"{IUCN_API_BASE}/{endpoint}", params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None

# ============================================================================
# DATA-FETCHING SUB-FUNCTIONS
# ============================================================================

def _parse_genus_species(species_name: str):
    """Split scientific name into (genus, species), filtering subgenus notation.
    e.g. "Procambarus (Scapulicambarus) clarkii" → ("Procambarus", "clarkii")
    Returns (None, None) if the name has fewer than two meaningful parts.
    """
    parts = [p for p in species_name.strip().split() if not p.startswith('(')]
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]


def get_species_assessment(species_name: str) -> Dict[str, Any]:
    """Fetches the core assessment data using v4 taxa endpoint."""
    genus_name, species_name_part = _parse_genus_species(species_name)
    if not genus_name:
        return {}
    
    params = {
        'genus_name': genus_name,
        'species_name': species_name_part
    }
    
    data = _make_iucn_request("taxa/scientific_name", params)
    
    if not data:
        return {}
    
    # v4 API structure: data has 'taxon' and 'assessments'
    if "taxon" not in data or "assessments" not in data:
        return {}
    
    taxon_data = data["taxon"]
    assessments = data["assessments"]
    
    # Get the latest assessment (marked as latest=True)
    latest_assessment = None
    for assessment in assessments:
        if assessment.get("latest"):
            latest_assessment = assessment
            break
    
    # If no latest assessment found, use the first one
    if not latest_assessment and assessments:
        latest_assessment = assessments[0]
    
    if not latest_assessment:
        return {}
    
    # Combine taxon data with latest assessment data, mapping v4 field names to expected names
    combined_data = {
        # Basic species info from taxon
        'species_name': taxon_data.get('scientific_name'),
        'authority': taxon_data.get('authority'),
        
        # Taxonomy - map v4 field names
        'kingdom_name': taxon_data.get('kingdom_name'),
        'phylum_name': taxon_data.get('phylum_name'), 
        'class_name': taxon_data.get('class_name'),
        'order_name': taxon_data.get('order_name'),
        'family_name': taxon_data.get('family_name'),
        'genus_name': taxon_data.get('genus_name'),
        
        # Assessment data - map v4 field names  
        'category': latest_assessment.get('red_list_category_code'),
        'assessment_date': latest_assessment.get('year_published'),
        'assessment_id': latest_assessment.get('assessment_id'),
        
        # ID fields - map v4 field names
        'taxonid': taxon_data.get('sis_id'),  # v4 uses sis_id instead of taxonid
    }
    
    return combined_data

def get_assessment_details(assessment_id: int) -> Dict[str, Any]:
    """Fetches detailed assessment data using v4 assessment endpoint."""
    data = _make_iucn_request(f"assessment/{assessment_id}")
    
    if not data:
        return {}
        
    return data

def get_species_narrative(species_name: str) -> Dict[str, Any]:
    """Fetches narrative text - for v4, this comes from detailed assessment data."""
    # Get basic assessment first to get assessment_id
    assessment = get_species_assessment(species_name)
    if not assessment or 'assessment_id' not in assessment:
        return {}
    
    # Get detailed assessment data
    details = get_assessment_details(assessment['assessment_id'])
    
    return details if isinstance(details, dict) else {}

def get_species_threats(species_name: str) -> List[Dict[str, Any]]:
    """Fetches threats from detailed assessment data."""
    narrative = get_species_narrative(species_name)
    return narrative.get("threats", []) if narrative else []

def get_species_habitats(species_name: str) -> List[Dict[str, Any]]:
    """Fetches habitats from detailed assessment data."""
    narrative = get_species_narrative(species_name)
    return narrative.get("habitats", []) if narrative else []

def get_species_conservation_measures(species_name: str) -> List[Dict[str, Any]]:
    """Fetches conservation measures from detailed assessment data."""
    narrative = get_species_narrative(species_name)
    return narrative.get("conservation_actions", []) if narrative else []

def get_species_common_names(species_name: str, assessment_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Fetches common/vernacular names for a species.

    Args:
        species_name: Scientific name of the species
        assessment_data: Pre-fetched assessment dict (avoids redundant HTTP call if already retrieved)
    """
    # Use provided assessment data to skip redundant HTTP call
    if assessment_data is None:
        assessment_data = get_species_assessment(species_name)
    if not assessment_data or 'taxonid' not in assessment_data:
        return []

    genus_name, species_name_part = _parse_genus_species(species_name)
    if not genus_name:
        return []

    params = {
        'genus_name': genus_name,
        'species_name': species_name_part
    }

    data = _make_iucn_request("taxa/common_names", params)

    if not data:
        return []

    return data.get("common_names", [])

def get_species_synonyms(species_name: str) -> List[Dict[str, Any]]:
    """Fetches taxonomic synonyms for a species."""
    genus_name, species_name_part = _parse_genus_species(species_name)
    if not genus_name:
        return []

    params = {
        'genus_name': genus_name,
        'species_name': species_name_part
    }

    data = _make_iucn_request("taxa/synonyms", params)

    if not data:
        return []

    return data.get("synonyms", [])

def get_species_citation(species_name: str) -> Dict[str, Any]:
    """Fetches the proper citation for a species assessment."""
    genus_name, species_name_part = _parse_genus_species(species_name)
    if not genus_name:
        return {}

    params = {
        'genus_name': genus_name,
        'species_name': species_name_part
    }

    data = _make_iucn_request("taxa/citation", params)

    if not data:
        return {}

    return data.get("citation", {})

def get_species_historical_assessments(species_name: str) -> List[Dict[str, Any]]:
    """Fetches historical assessment data to show status changes over time."""
    genus_name, species_name_part = _parse_genus_species(species_name)
    if not genus_name:
        return []

    params = {
        'genus_name': genus_name,
        'species_name': species_name_part
    }

    data = _make_iucn_request("taxa/historical", params)

    if not data:
        return []

    return data.get("assessments", [])

def get_species_countries(species_name: str) -> List[Dict[str, Any]]:
    """Fetches country occurrence data with origin and presence information."""
    genus_name, species_name_part = _parse_genus_species(species_name)
    if not genus_name:
        return []

    params = {
        'genus_name': genus_name,
        'species_name': species_name_part
    }

    data = _make_iucn_request("taxa/countries", params)

    if not data:
        return []

    return data.get("countries", [])

def extract_detailed_narrative_data(narrative_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts additional detailed information from the narrative/assessment details
    that wasn't being captured before.
    """
    extracted = {}

    # Geographic range information
    if 'range' in narrative_data:
        range_data = narrative_data['range']
        extracted['range_size_km2'] = range_data.get('range_size')
        extracted['elevation_upper'] = range_data.get('elevation_upper')
        extracted['elevation_lower'] = range_data.get('elevation_lower')
        extracted['depth_upper'] = range_data.get('depth_upper')
        extracted['depth_lower'] = range_data.get('depth_lower')

    # Population information (more detailed than just trend)
    if 'population' in narrative_data:
        pop_data = narrative_data['population']
        extracted['population_size'] = pop_data.get('population_size')
        extracted['population_severely_fragmented'] = pop_data.get('severely_fragmented')
        extracted['number_of_locations'] = pop_data.get('number_of_locations')
        extracted['number_of_mature_individuals'] = pop_data.get('number_of_mature_individuals')

    # Use and Trade
    if 'use_trade' in narrative_data:
        extracted['use_trade'] = narrative_data['use_trade']

    # Stresses (impacts of threats)
    if 'stresses' in narrative_data:
        extracted['stresses'] = narrative_data['stresses']

    # Rationale for Red List category
    extracted['rationale'] = narrative_data.get('rationale', '')

    # Additional narrative texts
    extracted['geographic_range_text'] = narrative_data.get('geographic_range', '')
    extracted['population_text'] = narrative_data.get('population', '')
    extracted['habitat_ecology_text'] = narrative_data.get('habitat_and_ecology', '')

    return extracted

# ============================================================================
# MASTER FUNCTION FOR THE TOOL
# ============================================================================

def get_comprehensive_iucn_data(species_name: str) -> Dict[str, Any]:
    """
    Get comprehensive structured conservation data for a species from the IUCN Red List.
    Includes taxonomy, conservation status, threats, habitats, conservation measures,
    common names, synonyms, historical assessments, country occurrence, use/trade,
    systems, stresses, and detailed population/range information.

    Makes 7 HTTP calls in 3 rounds (down from 15 sequential in the naive cascade):
      Round 1 (sequential): get_species_assessment      — need assessment_id before anything else
      Round 2 (sequential): get_assessment_details      — need it for threats/habitats/conservation
      Round 3 (parallel):   common_names, synonyms, countries, historical, citation — all independent
    """
    # Round 1: resolve taxon + latest assessment ID (must be sequential)
    assessment_data = get_species_assessment(species_name)
    if not assessment_data:
        return {}

    assessment_id = assessment_data.get('assessment_id')

    # Round 2: full assessment details (sequential — needed before extracting sub-fields)
    assessment_details = get_assessment_details(assessment_id) if assessment_id else {}

    # Extract all nested data from the single assessment_details response
    detailed_data = extract_detailed_narrative_data(assessment_details) if assessment_details else {}
    threats = assessment_details.get('threats', [])
    habitats_list = assessment_details.get('habitats', [])
    conservation_measures = assessment_details.get('conservation_actions', [])

    # Round 3: independent endpoints — fire in parallel
    # common_names receives pre-fetched assessment_data to skip redundant get_species_assessment call
    independent_tasks = {
        'common_names':         (get_species_common_names,           species_name),
        'synonyms':             (get_species_synonyms,               species_name),
        'countries':            (get_species_countries,              species_name),
        'historical_assessments': (get_species_historical_assessments, species_name),
        'citation':             (get_species_citation,               species_name),
    }

    ind_results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {}
        for key, (fn, arg) in independent_tasks.items():
            if key == 'common_names':
                # Pass pre-fetched assessment_data to avoid redundant HTTP call inside
                fut = executor.submit(fn, arg, assessment_data)
            else:
                fut = executor.submit(fn, arg)
            future_to_key[fut] = key
        for future in as_completed(future_to_key):
            k = future_to_key[future]
            try:
                ind_results[k] = future.result()
            except Exception:
                ind_results[k] = [] if k != 'citation' else {}

    common_names          = ind_results.get('common_names', [])
    synonyms              = ind_results.get('synonyms', [])
    countries             = ind_results.get('countries', [])
    historical_assessments = ind_results.get('historical_assessments', [])
    citation              = ind_results.get('citation', {})

    return {
        'species_name': assessment_data.get('species_name'),
        'taxonomy': {
            'kingdom': assessment_data.get('kingdom_name'),
            'phylum': assessment_data.get('phylum_name'),
            'class': assessment_data.get('class_name'),
            'order': assessment_data.get('order_name'),
            'family': assessment_data.get('family_name'),
            'genus': assessment_data.get('genus_name')
        },
        'conservation_status': {
            'iucn_category': assessment_data.get('category'),
            'population_trend': assessment_details.get('population_trend'),
            'assessment_date': assessment_data.get('assessment_date'),
            'rationale': detailed_data.get('rationale', '')
        },
        'threats': threats,
        'stresses': detailed_data.get('stresses', []),
        'habitats_list': habitats_list,
        'conservation_measures': conservation_measures,
        'common_names': common_names,
        'synonyms': synonyms,
        'countries': countries,
        'historical_assessments': historical_assessments,
        'citation': citation,
        'geographic_range': {
            'range_size_km2': detailed_data.get('range_size_km2'),
            'elevation_upper': detailed_data.get('elevation_upper'),
            'elevation_lower': detailed_data.get('elevation_lower'),
            'depth_upper': detailed_data.get('depth_upper'),
            'depth_lower': detailed_data.get('depth_lower'),
            'text': detailed_data.get('geographic_range_text', '')
        },
        'population': {
            'size': detailed_data.get('population_size'),
            'severely_fragmented': detailed_data.get('population_severely_fragmented'),
            'number_of_locations': detailed_data.get('number_of_locations'),
            'number_of_mature_individuals': detailed_data.get('number_of_mature_individuals'),
            'text': detailed_data.get('population_text', '')
        },
        'use_trade': detailed_data.get('use_trade', []),
        'habitat_ecology_text': detailed_data.get('habitat_ecology_text', ''),
        'metadata': {
            'iucn_taxon_id': assessment_data.get('taxonid'),
            'iucn_url': f"https://www.iucnredlist.org/search?searchType=species&query={species_name.replace(' ', '+')}" if species_name else None,
            'published_year': assessment_data.get('assessment_date')
        }
    }

# ============================================================================
# DATA FLATTENING FUNCTION
# ============================================================================

# IUCN-specific configuration for flattening
_IUCN_DIRECT_FIELDS = [
    'threats', 'conservation_measures', 'stresses',
    'common_names', 'synonyms', 'countries',
    'historical_assessments', 'use_trade',
    'citation', 'habitat_ecology_text'
]

_IUCN_GEOGRAPHIC_RANGE_MAPPINGS = {
    'range_size_km2': 'range_size_km2',
    'elevation_upper': 'elevation_upper',
    'elevation_lower': 'elevation_lower',
    'depth_upper': 'depth_upper',
    'depth_lower': 'depth_lower',
    'text': 'geographic_range_text'
}

_IUCN_POPULATION_MAPPINGS = {
    'size': 'population_size',
    'severely_fragmented': 'population_severely_fragmented',
    'number_of_locations': 'number_of_locations',
    'number_of_mature_individuals': 'number_of_mature_individuals',
    'text': 'population_text'
}

# Habitat field key transformations (camelCase to snake_case)
_IUCN_HABITAT_KEY_MAPPINGS = {
    'majorImportance': 'major_importance'
}


def _process_conservation_status(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    """Process IUCN conservation_status with field mappings."""
    flatten_with_get(source, target, {
        'iucn_category': 'iucn_status',
        'population_trend': 'population_trend',
        'assessment_date': 'assessment_date',
        'rationale': 'rationale'
    })


def _process_geographic_range(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    """Process IUCN geographic_range with field mappings."""
    flatten_with_get(source, target, _IUCN_GEOGRAPHIC_RANGE_MAPPINGS)


def _process_population(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    """Process IUCN population data with field mappings."""
    flatten_with_get(source, target, _IUCN_POPULATION_MAPPINGS)


def flatten_iucn_data(iucn_data: Dict[str, Any], species_name: str) -> Dict[str, Any]:
    """
    Flatten the nested IUCN data structure for better schema matching.

    Uses the shared flatten_nested_fields utility with IUCN-specific configuration
    and custom processors for complex nested structures.
    """
    # Use shared utility for basic flattening
    flattened = flatten_nested_fields(
        data=iucn_data,
        direct_fields=_IUCN_DIRECT_FIELDS,
        nested_keys=['taxonomy', 'metadata'],
        custom_processors={
            'conservation_status': _process_conservation_status,
            'geographic_range': _process_geographic_range,
            'population': _process_population
        }
    )

    # Set species_name from parameter (required field)
    flattened['species_name'] = species_name

    # Transform habitats_list with key mappings (camelCase -> snake_case)
    if 'habitats_list' in iucn_data:
        flattened['habitats_list'] = transform_list_field(
            iucn_data, 'habitats_list', _IUCN_HABITAT_KEY_MAPPINGS
        )

    return flattened

# ============================================================================
# HAYSTACK COMPONENT FOR PIPELINE INTEGRATION
# ============================================================================

from haystack import component

@component
class IUCNComponent:
    """
    IUCN Component that handles data fetching, flattening, and caching.
    """
    
    def __init__(self):
        """
        Initialize IUCN component.

        Note: raw_store must be set externally by the pipeline before use.
        This ensures session-isolated, species-specific cache paths are used.
        """
        self.raw_store = None  # Must be set by pipeline before use
    
    @component.output_types(
        cached_data=Dict[str, Any],
        iucn_data=Dict[str, Any],
        cache_status=str
    )
    def run(self, species_name: str, raw_store=None) -> Dict[str, Any]:
        """
        Fetch IUCN data and save as raw JSON for AI categorization.

        Args:
            species_name: Scientific name to query
            raw_store: RawDataStore instance (from SynonymCoordinator in synonym-aware pipeline)
        """
        try:
            # Use provided raw_store if available, otherwise use instance variable (backward compatibility)
            if raw_store is not None:
                self.raw_store = raw_store

            raw_iucn_data = get_comprehensive_iucn_data(species_name)

            if not raw_iucn_data:
                return {
                    "cached_data": {}, "iucn_data": {},
                    "cache_status": "no_data"
                }

            # Save raw data for AI categorization
            self.raw_store.save_raw_data(species_name, "IUCN", raw_iucn_data)

            return {
                "cached_data": raw_iucn_data, "iucn_data": raw_iucn_data,
                "cache_status": "raw_saved"
            }

        except Exception as e:
            return {
                "cached_data": {}, "iucn_data": {}, "cache_status": "error"
            }

# ============================================================================
# HAYSTACK TOOL WRAPPER (Legacy Support)
# ============================================================================

from haystack.tools import Tool

iucn_tool = Tool(
    name="get_comprehensive_iucn_data",
    description="Get comprehensive species conservation data from the IUCN Red List. Returns a structured dictionary with taxonomy, conservation status (category, rationale, historical assessments), population data (trend, size, fragmentation, locations), threats and stresses, habitats, conservation measures, common names, synonyms, citation, country occurrence, use/trade information, and detailed geographic range (size, elevation, depth).",
    parameters={
        "species_name": {"type": "string", "description": "The scientific name of the species (e.g., 'Loxodonta africana' or 'Apteryx mantelli')."}
    },
    function=get_comprehensive_iucn_data
)

# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

def test_v4_api_connectivity() -> bool:
    """Test basic v4 API connectivity with a simple endpoint."""
    print("Testing v4 API connectivity...")
    try:
        # Test with API version endpoint (should be simple and reliable)
        data = _make_iucn_request("information/api_version")
        if data:
            print(f"SUCCESS: v4 API connected successfully")
            print(f"   API Version: {data}")
            return True
        else:
            print("FAILED: v4 API connection failed - no response")
            return False
    except Exception as e:
        print(f"ERROR: v4 API connection error: {e}")
        return False

if __name__ == "__main__":
    import sys
    import json
    
    # Check if a species name was provided as a command-line argument
    if len(sys.argv) > 1:
        species_to_test = sys.argv[1]
    else:
        # Use a default species that should have IUCN data
        species_to_test = "Procambarus clarkii"
    
    print(f"=== Testing IUCN v4 API for: '{species_to_test}' ===\n")
    
    # First test basic connectivity
    print("1. Testing v4 API connectivity:")
    if not test_v4_api_connectivity():
        print("Stopping tests - API connectivity failed")
        exit(1)
    
    print()
    
    # Test individual API endpoints
    print("2. Testing individual API endpoints:")
    
    print("  - Getting species assessment...")
    assessment = get_species_assessment(species_to_test)
    print(f"    Assessment found: {bool(assessment)}")
    if assessment:
        print(f"    Category: {assessment.get('category', 'N/A')}")
        print(f"    Scientific name: {assessment.get('scientific_name', 'N/A')}")
    
    print("  - Getting species narrative...")
    narrative = get_species_narrative(species_to_test)
    print(f"    Narrative found: {bool(narrative)}")
    
    print("  - Getting threats...")
    threats = get_species_threats(species_to_test)
    print(f"    Threats found: {len(threats)}")
    
    print("  - Getting habitats...")
    habitats = get_species_habitats(species_to_test)
    print(f"    Habitats found: {len(habitats)}")
    
    print("  - Getting conservation measures...")
    measures = get_species_conservation_measures(species_to_test)
    print(f"    Conservation measures found: {len(measures)}")
    
    print()
    
    # Test comprehensive function
    print("3. Testing comprehensive data function:")
    comprehensive_data = get_comprehensive_iucn_data(species_to_test)
    
    if comprehensive_data:
        print("SUCCESS: Successfully retrieved comprehensive IUCN data")
        print(f"   Data keys: {list(comprehensive_data.keys())}")
        
        print("\n4. Testing data flattening:")
        flattened_data = flatten_iucn_data(comprehensive_data, species_to_test)
        print(f"   Flattened keys: {list(flattened_data.keys())}")
        
        print("\n5. Sample flattened data:")
        print(json.dumps(flattened_data, indent=2, default=str))
        
        print("\n6. Testing IUCNComponent:")
        component = IUCNComponent()
        result = component.run(species_to_test)
        print(f"   Component status: {result.get('cache_status')}")
        print(f"   IUCN data keys: {list(result.get('iucn_data', {}).keys())}")
        
    else:
        print("FAILED: No comprehensive IUCN data found")
        print("This could mean:")
        print("  - API token is missing or invalid (check Bearer auth)")
        print("  - Species name not found in IUCN database")
        print("  - v4 API endpoints have different structure")
        print("  - Network connectivity issues")