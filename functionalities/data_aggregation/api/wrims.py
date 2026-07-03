#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
WRiMS API Module
Interface for retrieving marine species introduction data from the World Register of Introduced Marine Species (WRiMS)
"""

import requests
import json
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional
from urllib.parse import quote
from haystack.tools import Tool

import logging

from functionalities.data_aggregation.tools.standardization_utils import (
    standardize_establishment_means,
    standardize_invasiveness,
    standardize_establishment_status
)
from core.utils.species_name_utils import get_species_name_variations

logger = logging.getLogger(__name__)

# ============================================================================
# WRiMS/WoRMS API CONFIGURATION
# ============================================================================
WORMS_REST_BASE = "https://www.marinespecies.org/rest"
WRIMS_BASE = "https://www.marinespecies.org/introduced"

# Request headers
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ============================================================================
# CORE WRiMS FUNCTIONS
# ============================================================================

# Endpoint configuration: maps endpoint_type to (URL path template, data key for response)
_WORMS_ENDPOINTS = {
    'aphia_id': ('AphiaIDByName', 'data'),
    'record': ('AphiaRecordByAphiaID', 'data'),
    'distributions': ('AphiaDistributionsByAphiaID', 'distributions'),
    'classification': ('AphiaClassificationByAphiaID', 'classification'),
    'synonyms': ('AphiaSynonymsByAphiaID', 'synonyms'),
    'vernacular': ('AphiaVernacularsByAphiaID', 'vernacular'),
    'children': ('AphiaChildrenByAphiaID', 'children'),
    'attributes': ('AphiaAttributesByAphiaID', 'attributes'),
    'sources': ('AphiaSourcesByAphiaID', 'sources'),
}

# Endpoints that return "no_<type>" status instead of "not_found" for 204 responses
_ENDPOINTS_WITH_NO_STATUS = {'distributions', 'classification', 'synonyms', 'vernacular', 'children', 'attributes', 'sources'}


def _build_worms_url(endpoint_type: str, identifier: str, marine_only: Optional[bool] = None) -> Optional[str]:
    """Build WoRMS API URL for the given endpoint type.

    marine_only applies only to the name lookup (AphiaIDByName). WoRMS defaults
    to marine_only=true; pass False to also match introduced species that WoRMS
    does not flag as strictly marine (common for WRiMS estuarine/brackish taxa).
    """
    if endpoint_type not in _WORMS_ENDPOINTS:
        return None

    path_template = _WORMS_ENDPOINTS[endpoint_type][0]
    encoded_id = quote(identifier) if endpoint_type == 'aphia_id' else identifier
    url = f"{WORMS_REST_BASE}/{path_template}/{encoded_id}"
    if endpoint_type == 'aphia_id' and marine_only is not None:
        url += f"?marine_only={'true' if marine_only else 'false'}"
    return url


def _parse_aphia_id_response(response: requests.Response, identifier: str) -> Dict[str, Any]:
    """Parse response from AphiaID endpoint (can return JSON or plain text)."""
    try:
        aphia_id = response.json()
        if isinstance(aphia_id, int) and aphia_id > 0:
            return {"status": "success", "data": aphia_id}
    except json.JSONDecodeError:
        text_response = response.text.strip()
        if text_response.isdigit():
            return {"status": "success", "data": int(text_response)}

    return {"status": "not_found", "message": f"Invalid AphiaID response for {identifier}"}


def _parse_distributions_response(data: List[Dict]) -> Dict[str, Any]:
    """Parse and categorize distribution records by establishment means."""
    native_locations, introduced_locations, uncertain_locations = [], [], []

    for dist in data:
        location = dist.get('locality', 'Unknown')
        establishment_means = (dist.get('establishmentMeans') or 'unknown').lower()
        occurrence = dist.get('occurrence', '')
        invasiveness = (dist.get('invasiveness') or '').lower()

        record = {
            'location': location,
            'occurrence': occurrence,
            'invasiveness': invasiveness
        }

        if establishment_means == 'native':
            record['type'] = 'native'
            native_locations.append(record)
        elif establishment_means == 'alien':
            record['type'] = 'introduced'
            record['invasiveness'] = invasiveness or 'unknown'
            introduced_locations.append(record)
        else:
            record['type'] = establishment_means or 'uncertain'
            uncertain_locations.append(record)

    return {
        "status": "success",
        "total_records": len(data),
        "native_locations": native_locations,
        "introduced_locations": introduced_locations,
        "uncertain_locations": uncertain_locations,
        "raw_data": data
    }


def _worms_request(endpoint_type: str, identifier: str, marine_only: Optional[bool] = None) -> Dict[str, Any]:
    """
    Generic WoRMS API request function with shared error handling.

    Args:
        endpoint_type: Type of endpoint ('aphia_id', 'record', 'distributions', etc.)
        identifier: Species name or AphiaID
        marine_only: For the name lookup only, whether to restrict to marine taxa

    Returns:
        Dictionary containing request results with 'status' key
    """
    url = _build_worms_url(endpoint_type, identifier, marine_only)
    if not url:
        return {"status": "error", "message": f"Invalid endpoint type: {endpoint_type}"}

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)

        if response.status_code == 200:
            # Special handling for AphiaID endpoint
            if endpoint_type == 'aphia_id':
                return _parse_aphia_id_response(response, identifier)

            data = response.json()

            # Special handling for distributions
            if endpoint_type == 'distributions':
                return _parse_distributions_response(data)

            # Standard JSON response
            data_key = _WORMS_ENDPOINTS[endpoint_type][1]
            return {"status": "success", data_key: data}

        elif response.status_code == 204:
            status = f"no_{endpoint_type}" if endpoint_type in _ENDPOINTS_WITH_NO_STATUS else "not_found"
            return {"status": status, "message": f"No {endpoint_type} found for {identifier}"}

        return {"status": "error", "message": f"HTTP {response.status_code} getting {endpoint_type} for {identifier}"}

    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"Network error getting {endpoint_type}: {str(e)}"}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"Invalid JSON response for {endpoint_type}: {str(e)}"}


def get_aphia_id(species_name: str) -> Optional[int]:
    """Get AphiaID for a species using WoRMS REST API.

    Resolution is attempted in widening steps so a near-miss name does not
    silently drop the entire WRiMS lookup for the species:
      1. the exact name, then standardized / case variants;
      2. a marine_only=false retry, since WRiMS lists introduced species WoRMS
         may not flag as strictly marine.
    A miss is logged (with the name tried) rather than failing silently.
    """
    candidates = [species_name]
    for variation in get_species_name_variations(species_name):
        if variation not in candidates:
            candidates.append(variation)

    for name in candidates:
        result = _worms_request('aphia_id', name)
        if result.get('status') == 'success':
            return result.get('data')

    # Last resort: allow non-marine matches for the original name
    result = _worms_request('aphia_id', species_name, marine_only=False)
    if result.get('status') == 'success':
        return result.get('data')

    logger.warning(
        "WoRMS: could not resolve AphiaID for '%s' (tried %d name variant(s) + non-marine retry)",
        species_name, len(candidates),
    )
    return None


def get_species_record(aphia_id: int) -> Dict[str, Any]:
    """Get complete species record using AphiaID."""
    return _worms_request('record', str(aphia_id))


def get_species_distributions(aphia_id: int) -> Dict[str, Any]:
    """Get distribution data for a species, including introduction information."""
    return _worms_request('distributions', str(aphia_id))


def get_species_classification(aphia_id: int) -> Dict[str, Any]:
    """Get taxonomic classification for a species."""
    return _worms_request('classification', str(aphia_id))


def get_species_synonyms(aphia_id: int) -> Dict[str, Any]:
    """Get synonyms for a species."""
    return _worms_request('synonyms', str(aphia_id))


def get_species_vernacular_names(aphia_id: int) -> Dict[str, Any]:
    """Get vernacular/common names for a species."""
    return _worms_request('vernacular', str(aphia_id))


def get_species_children(aphia_id: int) -> Dict[str, Any]:
    """Get children taxa (subspecies, varieties) for a species."""
    return _worms_request('children', str(aphia_id))


def get_species_attributes(aphia_id: int) -> Dict[str, Any]:
    """Get attributes (biological/ecological traits) for a species."""
    return _worms_request('attributes', str(aphia_id))


def get_species_sources(aphia_id: int) -> Dict[str, Any]:
    """Get literature sources and bibliographic references for a species."""
    return _worms_request('sources', str(aphia_id))


def get_external_ids(aphia_id: int, id_types: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """
    Fetch cross-references to external taxonomic databases for a given AphiaID.

    Uses the AphiaExternalIDByAphiaID endpoint which takes a ?type= query parameter.
    Verified working: returns array of IDs e.g. ["164712"] for type=tsn.

    Args:
        aphia_id: WoRMS AphiaID
        id_types: List of external ID types to fetch. Defaults to tsn, gisd, ncbi, bold.
                  Available types: tsn (ITIS), bold (Barcode of Life), ncbi (NCBI Taxonomy),
                  gisd (Global Invasive Species Database), irmng, lsid, dyntaxa

    Returns:
        Dict mapping id_type → list of external IDs (empty list if not found)
    """
    if id_types is None:
        id_types = ['tsn', 'gisd', 'ncbi', 'bold']

    result = {}
    for id_type in id_types:
        url = f"{WORMS_REST_BASE}/AphiaExternalIDByAphiaID/{aphia_id}?type={id_type}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            if response.status_code == 200:
                data = response.json()
                result[id_type] = data if isinstance(data, list) else [data]
            else:
                result[id_type] = []
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            result[id_type] = []

    return result


# ============================================================================
# DATA PROCESSING FUNCTIONS FOR SQL DATABASE
# ============================================================================

def process_species_record(species_record_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract essential taxonomic data from species record for SQL database."""
    if species_record_response.get('status') != 'success':
        return {}
    
    data = species_record_response.get('data', {})
    return {
        'species_name': data.get('scientificname'),
        'authority': data.get('authority'),
        'status': data.get('status'),
        'rank': data.get('rank'),
        'kingdom': data.get('kingdom'),
        'phylum': data.get('phylum'),
        'class': data.get('class'),
        'order': data.get('order'),
        'family': data.get('family'),
        'genus': data.get('genus'),
        'aphia_id': data.get('AphiaID'),
        'is_marine': data.get('isMarine', 0) == 1,
        'is_brackish': data.get('isBrackish', 0) == 1,
        'is_freshwater': data.get('isFreshwater', 0) == 1,
        'is_terrestrial': data.get('isTerrestrial', 0) == 1,
        'is_extinct': data.get('isExtinct', 0) == 1,
        'modified': data.get('modified'),
        'worms_url': data.get('url')
    }


# WoRMS establishmentMeans (alien/native/uncertain) → the uppercase vocab GBIF
# distribution_records and the report appendix already use, so all consumers agree.
_WORMS_MEANS_TOKEN = {
    'alien': 'INTRODUCED',
    'native': 'NATIVE',
    'uncertain': 'UNCERTAIN',
    'not_specified': 'NOT_SPECIFIED',
}


def process_distribution_data(distributions_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract standardized distribution data for SQL database.

    Captures the WoRMS geographic identifiers (higher_geography, MRGID location_id,
    lat/lon) so downstream consumers can resolve a record to a country without
    geocoding the free-text locality. establishment_means is taken from the WoRMS
    establishmentMeans field (alien/native) — NOT invasiveness, which is a separate
    axis — so the introduced/native signal survives; invasiveness is kept alongside.
    """
    if distributions_response.get('status') != 'success':
        return {}

    raw_data = distributions_response.get('raw_data', [])

    distributions = []
    for record in raw_data:
        if record.get('locality') or record.get('higherGeography'):
            locality_raw = record.get('locality')
            locality = str(locality_raw).strip() if locality_raw else None
            higher_geo = record.get('higherGeography')

            distributions.append({
                'locality': locality,
                'establishment_means': _WORMS_MEANS_TOKEN[
                    standardize_establishment_means(record.get('establishmentMeans'))
                ],
                'establishment_status': standardize_establishment_status(record.get('occurrence')),
                'invasiveness': standardize_invasiveness(record.get('invasiveness')),
                'higher_geography': str(higher_geo).strip() if higher_geo else None,
                'location_id': record.get('locationID'),
                'decimalLatitude': record.get('decimalLatitude'),
                'decimalLongitude': record.get('decimalLongitude'),
                'source': 'WRiMS'
            })

    return {
        'distributions': distributions
    }


def process_classification_data(classification_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract flat taxonomic hierarchy from nested classification for SQL database."""
    if classification_response.get('status') != 'success':
        return {}
    
    classification = classification_response.get('classification', {})
    taxonomy = {}
    
    current = classification
    while current:
        rank = current.get('rank', '').lower()
        name = current.get('scientificname')
        
        if rank and name:
            if rank == 'kingdom':
                taxonomy['kingdom'] = name
            elif rank == 'phylum':
                taxonomy['phylum'] = name
            elif rank in ['class', 'subclass']:
                taxonomy['class'] = name
            elif rank in ['order', 'suborder', 'superorder']:
                taxonomy['order'] = name
            elif rank in ['family', 'subfamily', 'superfamily']:
                taxonomy['family'] = name
            elif rank == 'genus':
                taxonomy['genus'] = name
            elif rank == 'species':
                taxonomy['species'] = name
        
        current = current.get('child')
    
    return taxonomy


def process_synonyms_data(synonyms_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract synonyms list for SQL database."""
    if synonyms_response.get('status') != 'success':
        return {}
    
    synonyms_data = synonyms_response.get('synonyms', [])
    synonyms_list = [s.get('scientificname') for s in synonyms_data if s.get('scientificname')]
    
    return {'synonyms': synonyms_list}


def process_vernacular_names_data(vernacular_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract raw vernacular names for SQL database."""
    if vernacular_response.get('status') != 'success':
        return {}
    
    vernacular_data = vernacular_response.get('vernacular', [])
    vernacular_names = []
    for entry in vernacular_data:
        name = entry.get('vernacular')
        if name:
            vernacular_names.append({
                'name': name,
                'language': entry.get('language', 'unknown')
            })
    
    return {'vernacular_names': vernacular_names}


def process_children_data(children_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract children taxa information for SQL database."""
    if children_response.get('status') != 'success':
        return {}
    
    children_data = children_response.get('children', [])
    children_list = []
    for child in children_data:
        name = child.get('scientificname')
        if name:
            children_list.append({
                'name': name,
                'rank': child.get('rank'),
                'authority': child.get('authority', ''),
                'status': child.get('status', ''),
                'valid_name': child.get('valid_name')
            })
    
    return {'children_taxa': children_list}


def construct_habitat_string(species_data: Dict[str, Any]) -> str:
    """Construct habitat string from boolean habitat flags."""
    habitat_types = []
    if species_data.get('is_marine', False):
        habitat_types.append('Marine')
    if species_data.get('is_brackish', False):
        habitat_types.append('Brackish')
    if species_data.get('is_freshwater', False):
        habitat_types.append('Freshwater')
    return ', '.join(habitat_types) if habitat_types else 'Unknown'


def process_attributes_data(attributes_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract raw biological and ecological attributes for SQL database."""
    if attributes_response.get('status') != 'success':
        return {}

    attributes_data = attributes_response.get('data', [])
    attributes = []
    for attr in attributes_data:
        measurement_type = attr.get('measurementType')
        measurement_value = attr.get('measurementValue')

        if measurement_type and measurement_value:
            attributes.append({
                'type_id': attr.get('measurementTypeID'),
                'measurement_type': measurement_type,
                'value': measurement_value,
                'reference': attr.get('reference', ''),
                'quality_status': attr.get('qualitystatus', 'unknown')
            })

    return {'attributes': attributes}


def process_sources_data(sources_response: Dict[str, Any]) -> Dict[str, Any]:
    """Extract literature sources and bibliographic references for SQL database."""
    if sources_response.get('status') != 'success':
        return {}

    sources_data = sources_response.get('sources', [])
    sources = []
    for source in sources_data:
        reference = source.get('reference')
        if reference:
            sources.append({
                'reference': reference,
                'source_type': source.get('type', 'unknown'),
                'page': source.get('page', ''),
                'url': source.get('url', ''),
                'doi': source.get('doi', ''),
                'use': source.get('use', '')
            })

    return {'sources': sources}


def get_wrims_structured_data(species_name: str) -> Dict[str, Any]:
    """
    Get comprehensive WRiMS data for a species in a clean format for SQL database integration.
    """
    aphia_id = get_aphia_id(species_name)
    if not aphia_id:
        return {
            'species_name': species_name,
            'found_in_worms': False,
            'error': f"Species '{species_name}' not found in WoRMS database"
        }
    
    # All 9 data-fetch calls are independent once aphia_id is resolved — run in parallel
    fetch_tasks = {
        'species_record': (get_species_record,          aphia_id),
        'distributions':  (get_species_distributions,   aphia_id),
        'classification': (get_species_classification,  aphia_id),
        'synonyms':       (get_species_synonyms,        aphia_id),
        'vernacular':     (get_species_vernacular_names, aphia_id),
        'children':       (get_species_children,        aphia_id),
        'attributes':     (get_species_attributes,      aphia_id),
        'sources':        (get_species_sources,         aphia_id),
        'external_ids':   (get_external_ids,            aphia_id),
    }

    raw = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {
            executor.submit(fn, arg): key
            for key, (fn, arg) in fetch_tasks.items()
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                raw[key] = future.result()
            except Exception:
                raw[key] = {}

    species_record = raw.get('species_record', {})
    distributions  = raw.get('distributions', {})
    classification = raw.get('classification', {})
    synonyms       = raw.get('synonyms', {})
    vernacular     = raw.get('vernacular', {})
    children       = raw.get('children', {})
    attributes     = raw.get('attributes', {})
    sources        = raw.get('sources', {})
    external_ids   = raw.get('external_ids', {})

    processed_species = process_species_record(species_record)
    processed_distributions = process_distribution_data(distributions)
    processed_classification = process_classification_data(classification)
    processed_synonyms = process_synonyms_data(synonyms)
    processed_vernacular = process_vernacular_names_data(vernacular)
    processed_children = process_children_data(children)
    processed_attributes = process_attributes_data(attributes)
    processed_sources = process_sources_data(sources)

    structured_data = {
        'species_name': processed_species.get('species_name') or species_name,
        'found_in_worms': True,
        'authority': processed_species.get('authority'),
        'taxonomic_status': processed_species.get('status'),
        'taxonomic_rank': processed_species.get('rank'),
        'is_extinct': processed_species.get('is_extinct', False),
        'is_terrestrial': processed_species.get('is_terrestrial', False),
        'modified': processed_species.get('modified'),
        'kingdom': processed_classification.get('kingdom') or processed_species.get('kingdom'),
        'phylum': processed_classification.get('phylum') or processed_species.get('phylum'),
        'class': processed_classification.get('class') or processed_species.get('class'),
        'order': processed_classification.get('order') or processed_species.get('order'),
        'family': processed_classification.get('family') or processed_species.get('family'),
        'genus': processed_classification.get('genus') or processed_species.get('genus'),
        'habitat': construct_habitat_string(processed_species),
        'distribution_records': processed_distributions.get('distributions', []),
        'synonyms': processed_synonyms.get('synonyms', []),
        'vernacular_names': processed_vernacular.get('vernacular_names', []),
        'children_taxa': processed_children.get('children_taxa', []),
        'attributes': processed_attributes.get('attributes', []),
        'sources': processed_sources.get('sources', []),
        'external_references': external_ids,
        'metadata': {
            'aphia_id': aphia_id,
            'worms_url': processed_species.get('worms_url'),
            'data_source': 'WRiMS'
        }
    }

    return structured_data

# ============================================================================
# HAYSTACK COMPONENT FOR PIPELINE INTEGRATION
# ============================================================================

from haystack import component

@component
class WRiMSComponent:
    """
    WRiMS Component that handles data fetching, processing, and caching.
    """
    
    def __init__(self, use_ai_categorization: bool = False):
        """
        Initialize WRiMS component.

        Note: raw_store must be set externally by the pipeline before use.
        This ensures session-isolated, species-specific cache paths are used.
        """
        self.use_ai_categorization = use_ai_categorization
        self.raw_store = None  # Must be set by pipeline before use
        self.use_ai = use_ai_categorization
    
    @component.output_types(
        cached_data=Dict[str, Any],
        wrims_data=Dict[str, Any],
        cache_status=str
    )
    def run(self, species_name: str, raw_store=None) -> Dict[str, Any]:
        """
        Fetch WRiMS data and save as raw JSON for AI categorization.

        Args:
            species_name: Scientific name to query
            raw_store: RawDataStore instance (from SynonymCoordinator in synonym-aware pipeline)
        """
        try:
            # Use provided raw_store if available, otherwise use instance variable (backward compatibility)
            if raw_store is not None:
                self.raw_store = raw_store

            structured_wrims_data = get_wrims_structured_data(species_name)

            if not structured_wrims_data.get('found_in_worms'):
                return {
                    "cached_data": {}, "wrims_data": {},
                    "cache_status": "no_data"
                }

            # Save raw data for AI categorization
            self.raw_store.save_raw_data(species_name, "WRiMS", structured_wrims_data)

            return {
                "cached_data": structured_wrims_data, "wrims_data": structured_wrims_data,
                "cache_status": "raw_saved"
            }

        except Exception as e:
            logger.warning("WRiMS lookup failed for '%s': %s", species_name, e, exc_info=True)
            return {
                "cached_data": {}, "wrims_data": {}, "cache_status": "error"
            }


# ============================================================================
# HAYSTACK TOOL WRAPPER (Legacy Support)
# ============================================================================

wrims_tool = Tool(
    name="get_wrims_species_data",
    description="Get comprehensive marine species data from WRiMS (World Register of Introduced Marine Species) including taxonomy, distribution, invasion status, synonyms, common names, related taxa, biological attributes, and scientific literature references. Returns structured data ready for database integration.",
    parameters={
        "species_name": {"type": "string", "description": "Scientific name of the species (e.g., 'Carcinus maenas', 'Mytilus galloprovincialis')"}
    },
    function=get_wrims_structured_data
)

# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    # Check if a species name was provided as a command-line argument
    if len(sys.argv) > 1:
        species_to_test = sys.argv[1]
    else:
        # Use a default species if no argument is given
        species_to_test = "Carcinus maenas"

    print(f"--- Running WRiMS structured data test for: '{species_to_test}' ---")
    
    # Call the main data gathering function
    structured_data = get_wrims_structured_data(species_to_test)
    
    # Pretty-print the final result
    if structured_data.get('found_in_worms'):
        print("--- Successfully retrieved and processed data from WoRMS: ---")
        print(json.dumps(structured_data, indent=4))
    else:
        print(f"--- No data found for species: '{species_to_test}' ---")
        print(json.dumps(structured_data, indent=4))