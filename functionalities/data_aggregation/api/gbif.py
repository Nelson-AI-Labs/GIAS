#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
GBIF Core Species Data Retrieval Module
A streamlined module to retrieve core taxonomic data, synonyms, vernacular names,
habitat details, distribution records, and a sample of occurrence records
from the GBIF API. Wrapped for Haystack integration.
"""

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Optional
from haystack.tools import Tool
import json
import sys

from functionalities.data_aggregation.api.api_data_utils import flatten_nested_fields
from core.services.locality_blob_splitter import split_locality_blob
from core.utils.species_name_utils import get_binomial_name, get_author_string
from core.utils.config_loader import get_contact_email

# ============================================================================
# GBIF API CONFIGURATION
# ============================================================================
GBIF_API_BASE = "https://api.gbif.org/v1"
# Set a user-agent to be a good internet citizen.
HEADERS = {
    "User-Agent": f"GuardIAS/1.0 (contact: {get_contact_email()})"
}
# Standard timeout for all API requests to prevent hanging
REQUEST_TIMEOUT = 15

# ============================================================================
# INTERNAL HELPER FUNCTIONS
# ============================================================================

def _get_gbif_species_match(species_name: str) -> Optional[Dict[str, Any]]:
    """Internal helper to match a species name and get its core data and usageKey."""
    try:
        match_url = f"{GBIF_API_BASE}/species/match"
        match_params = {"name": species_name, "verbose": True}
        
        match_response = requests.get(match_url, params=match_params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        match_response.raise_for_status()
        match_data = match_response.json()

        if match_data.get("matchType") == "NONE" or not match_data.get("usageKey"):
            return None
        
        return match_data

    except requests.exceptions.RequestException as e:
        print(f"Error matching species '{species_name}': {e}")
        return None

# ============================================================================
# RELIABLE DATA-FETCHING SUB-FUNCTIONS
# ============================================================================

def get_species_distributions(usage_key: int) -> list:
    """Fetches curated distribution records, focusing on locality-based statuses."""
    distributions = []
    try:
        dist_url = f"{GBIF_API_BASE}/species/{usage_key}/distributions"
        dist_response = requests.get(dist_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        dist_response.raise_for_status()
        dist_data = dist_response.json()
        
        if isinstance(dist_data, dict) and 'results' in dist_data:
            results = dist_data['results']
        elif isinstance(dist_data, list):
            results = dist_data
        else:
            results = []

        for dist in results:
            locality = dist.get('locality')
            if locality:
                # Some sources (Catalogue of Life / WCVP via GBIF) pack an entire
                # range into one locality string. Split blobs into atomic records;
                # an atomic locality passes through as a single record unchanged.
                #
                # GBIF is an aggregator: 'database' is the authority we queried,
                # 'source' is the contributing dataset that asserted the record
                # (e.g. "Catalogue of Life"). Keeping them separate lets the report
                # show provenance clearly instead of dumping a raw dataset title.
                base = {
                    'database': 'GBIF',
                    'country': dist.get('country'),
                    'countryCode': dist.get('countryCode'),
                    'establishment_status': dist.get('status'),
                    'establishment_means': dist.get('establishmentMeans'),
                    'threatStatus': dist.get('threatStatus'),
                    'source': dist.get('source', 'GBIF')
                }
                distributions.extend(split_locality_blob(locality, base))

        return distributions
    except requests.exceptions.RequestException:
        return []

def get_habitat_from_profiles(usage_key: int) -> str:
    """
    Fetches habitat information from species profiles and returns it as a clean,
    comma-separated string of unique values.
    """
    try:
        profiles_url = f"{GBIF_API_BASE}/species/{usage_key}/speciesProfiles"
        profiles_response = requests.get(profiles_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        profiles_response.raise_for_status()
        profiles_data = profiles_response.json().get("results", [])

        unique_habitats = set()
        for profile in profiles_data:
            if 'habitat' in profile and profile['habitat']:
                habitats = profile['habitat'].split('|')
                for hab in habitats:
                    if hab.strip():
                        unique_habitats.add(hab.strip().lower())

        if not unique_habitats:
            return "No habitat details available."

        return ", ".join(sorted(list(unique_habitats)))

    except requests.exceptions.RequestException:
        return "Could not fetch habitat details."

def get_species_synonyms(usage_key: int) -> list:
    """Fetches synonyms for a species."""
    try:
        synonyms_url = f"{GBIF_API_BASE}/species/{usage_key}/synonyms"
        synonyms_response = requests.get(synonyms_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        synonyms_response.raise_for_status()
        synonyms_data = synonyms_response.json().get("results", [])
        
        return [s.get("scientificName") for s in synonyms_data if s.get("scientificName")]
    
    except requests.exceptions.RequestException:
        return []

def get_vernacular_names(usage_key: int) -> list:
    """Fetches raw vernacular/common names for a species."""
    try:
        vernacular_url = f"{GBIF_API_BASE}/species/{usage_key}/vernacularNames"
        vernacular_response = requests.get(vernacular_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        vernacular_response.raise_for_status()
        vernacular_data = vernacular_response.json().get("results", [])
        
        names_list = []
        for name_entry in vernacular_data:
            if name_entry.get("vernacularName"):
                names_list.append({
                    'name': name_entry.get("vernacularName"),
                    'language': name_entry.get("language", "unknown")
                })
        return names_list
    
    except requests.exceptions.RequestException:
        return []

def get_occurrence_sample(usage_key: int, limit: int = 50) -> list:
    """Gets a sample of occurrence records with comprehensive data fields.

    Filters to coordinate-bearing PRESENT records only — no-coordinate records
    carry no geographic signal for an invasive species intelligence system.
    Limit raised from 5 → 50 for meaningful geographic coverage.
    """
    try:
        search_url = f"{GBIF_API_BASE}/occurrence/search"
        params = {
            "taxonKey": usage_key,
            "limit": limit,
            "hasCoordinate": True,
            "occurrenceStatus": "PRESENT"
        }
        search_response = requests.get(search_url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        search_response.raise_for_status()
        results = search_response.json().get("results", [])

        occurrences = []
        for occ in results:
            occurrences.append({
                'key': occ.get('key'),
                'decimalLatitude': occ.get('decimalLatitude'),
                'decimalLongitude': occ.get('decimalLongitude'),
                'coordinateUncertaintyInMeters': occ.get('coordinateUncertaintyInMeters'),
                'depth': occ.get('depth'),
                'depthAccuracy': occ.get('depthAccuracy'),
                'eventDate': occ.get('eventDate'),
                'year': occ.get('year'),
                'month': occ.get('month'),
                'day': occ.get('day'),
                'countryCode': occ.get('countryCode'),
                'stateProvince': occ.get('stateProvince'),
                'locality': occ.get('locality'),
                'verbatimLocality': occ.get('verbatimLocality'),
                'waterBody': occ.get('waterBody'),
                'habitat': occ.get('habitat'),
                'basisOfRecord': occ.get('basisOfRecord'),
                'samplingProtocol': occ.get('samplingProtocol'),
                'degreeOfEstablishment': occ.get('degreeOfEstablishment'),
                'pathway': occ.get('pathway'),
                'recordedBy': occ.get('recordedBy'),
                'identifiedBy': occ.get('identifiedBy'),
                'dateIdentified': occ.get('dateIdentified'),
                'institutionCode': occ.get('institutionCode'),
                'collectionCode': occ.get('collectionCode'),
                'catalogNumber': occ.get('catalogNumber'),
                'typeStatus': occ.get('typeStatus'),
                'establishmentMeans': occ.get('establishmentMeans'),
                'occurrenceStatus': occ.get('occurrenceStatus'),
                'individualCount': occ.get('individualCount')
            })
        return occurrences

    except requests.exceptions.RequestException:
        return []

def get_species_descriptions(usage_key: int) -> list:
    """Fetches taxonomic and biological descriptions for a species."""
    try:
        descriptions_url = f"{GBIF_API_BASE}/species/{usage_key}/descriptions"
        descriptions_response = requests.get(descriptions_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        descriptions_response.raise_for_status()
        descriptions_data = descriptions_response.json().get("results", [])

        descriptions = []
        for desc in descriptions_data:
            description_text = desc.get('description')
            if description_text:
                descriptions.append({
                    'description': description_text,
                    'type': desc.get('type'),
                    'language': desc.get('language'),
                    'source': desc.get('source')
                })
        return descriptions

    except requests.exceptions.RequestException:
        return []

def get_species_media(usage_key: int) -> list:
    """Fetches media (images, videos, sounds) for a species."""
    try:
        media_url = f"{GBIF_API_BASE}/species/{usage_key}/media"
        media_response = requests.get(media_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        media_response.raise_for_status()
        media_data = media_response.json().get("results", [])

        media = []
        for item in media_data:
            identifier = item.get('identifier')
            if identifier:
                media.append({
                    'identifier': identifier,
                    'type': item.get('type'),
                    'format': item.get('format'),
                    'title': item.get('title'),
                    'description': item.get('description'),
                    'creator': item.get('creator'),
                    'publisher': item.get('publisher'),
                    'license': item.get('license'),
                    'references': item.get('references')
                })
        return media

    except requests.exceptions.RequestException:
        return []

def get_species_references(usage_key: int) -> list:
    """Fetches bibliographic references for a species."""
    try:
        references_url = f"{GBIF_API_BASE}/species/{usage_key}/references"
        references_response = requests.get(references_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        references_response.raise_for_status()
        references_data = references_response.json().get("results", [])

        references = []
        for ref in references_data:
            citation = ref.get('citation')
            if citation:
                references.append({
                    'citation': citation,
                    'type': ref.get('type'),
                    'source': ref.get('source'),
                    'link': ref.get('link')
                })
        return references

    except requests.exceptions.RequestException:
        return []

def get_type_specimens(usage_key: int) -> list:
    """Fetches type specimen information for a species."""
    try:
        type_specimens_url = f"{GBIF_API_BASE}/species/{usage_key}/typeSpecimens"
        type_specimens_response = requests.get(type_specimens_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        type_specimens_response.raise_for_status()
        type_specimens_data = type_specimens_response.json().get("results", [])

        specimens = []
        for specimen in type_specimens_data:
            specimens.append({
                'typeStatus': specimen.get('typeStatus'),
                'scientificName': specimen.get('scientificName'),
                'locality': specimen.get('locality'),
                'catalogNumber': specimen.get('catalogNumber'),
                'institutionCode': specimen.get('institutionCode'),
                'collectionCode': specimen.get('collectionCode'),
                'recordedBy': specimen.get('recordedBy'),
                'source': specimen.get('source')
            })
        return specimens

    except requests.exceptions.RequestException:
        return []

def get_species_children(usage_key: int) -> list:
    """Fetches child taxa (subspecies, varieties, forms) for a species."""
    try:
        children_url = f"{GBIF_API_BASE}/species/{usage_key}/children"
        children_response = requests.get(children_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        children_response.raise_for_status()
        children_data = children_response.json().get("results", [])

        children = []
        for child in children_data:
            scientific_name = child.get('scientificName')
            if scientific_name:
                children.append({
                    'scientificName': scientific_name,
                    'rank': child.get('rank'),
                    'taxonomicStatus': child.get('taxonomicStatus'),
                    'key': child.get('key'),
                    'canonicalName': child.get('canonicalName')
                })
        return children

    except requests.exceptions.RequestException:
        return []

# ============================================================================
# MASTER FUNCTION FOR THE TOOL
# ============================================================================

def get_core_species_data(species_name: str) -> Dict[str, Any]:
    """
    Get comprehensive structured data for a species from GBIF.
    Includes taxonomy, distributions, habitat, synonyms, vernacular names,
    descriptions, media, references, type specimens, children taxa, and occurrence samples.

    Phase 1 (sequential): resolve species match → usage_key
    Phase 2 (parallel): all 10 endpoint calls fire concurrently via ThreadPoolExecutor
    """
    match_data = _get_gbif_species_match(species_name)
    if not match_data:
        return {}

    usage_key = match_data["usageKey"]
    gbif_url = f"https://www.gbif.org/species/{usage_key}" if usage_key else None
    raw_scientific_name = match_data.get('scientificName', '')

    # All 10 data-fetch calls are independent — run in parallel
    fetch_tasks = {
        'distribution_records': (get_species_distributions, usage_key),
        'habitat':              (get_habitat_from_profiles, usage_key),
        'synonyms':             (get_species_synonyms, usage_key),
        'vernacular_names':     (get_vernacular_names, usage_key),
        'descriptions':         (get_species_descriptions, usage_key),
        'media':                (get_species_media, usage_key),
        'references':           (get_species_references, usage_key),
        'type_specimens':       (get_type_specimens, usage_key),
        'children_taxa':        (get_species_children, usage_key),
        'occurrence_sample':    (get_occurrence_sample, usage_key),
    }

    results = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_key = {
            executor.submit(fn, arg): key
            for key, (fn, arg) in fetch_tasks.items()
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception:
                results[key] = [] if key != 'habitat' else "Could not fetch habitat details."

    return {
        'species_name': get_binomial_name(raw_scientific_name) if raw_scientific_name else raw_scientific_name,
        'taxonomy': {
            'kingdom': match_data.get('kingdom'),
            'phylum': match_data.get('phylum'),
            'class': match_data.get('class'),
            'order': match_data.get('order'),
            'family': match_data.get('family'),
            'genus': match_data.get('genus')
        },
        'distribution_records': results.get('distribution_records', []),
        'habitat':              results.get('habitat', 'No habitat details available.'),
        'synonyms':             results.get('synonyms', []),
        'vernacular_names':     results.get('vernacular_names', []),
        'descriptions':         results.get('descriptions', []),
        'media':                results.get('media', []),
        'references':           results.get('references', []),
        'type_specimens':       results.get('type_specimens', []),
        'children_taxa':        results.get('children_taxa', []),
        'occurrence_sample':    results.get('occurrence_sample', []),
        'metadata': {
            'gbif_key': usage_key,
            'gbif_url': gbif_url,
            'match_type': match_data.get('matchType'),
            'taxonomic_status': match_data.get('status'),
            'rank': match_data.get('rank'),
            'author': get_author_string(raw_scientific_name) if raw_scientific_name else ''
        }
    }

# ============================================================================
# DATA FLATTENING FUNCTION
# ============================================================================

# GBIF-specific configuration for flattening
_GBIF_DIRECT_FIELDS = [
    'species_name', 'habitat', 'distribution_records',
    'synonyms', 'vernacular_names', 'occurrence_sample',
    'descriptions', 'media', 'references', 'type_specimens',
    'children_taxa'
]

_GBIF_METADATA_MAPPINGS = {
    'rank': 'taxonomic_rank'  # Rename 'rank' to 'taxonomic_rank'
}


def flatten_gbif_data(gbif_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Flatten the nested GBIF data structure for better schema matching.

    Uses the shared flatten_nested_fields utility with GBIF-specific configuration.
    """
    return flatten_nested_fields(
        data=gbif_data,
        direct_fields=_GBIF_DIRECT_FIELDS,
        nested_keys=['taxonomy', 'metadata'],
        field_mappings={'metadata': _GBIF_METADATA_MAPPINGS}
    )

# ============================================================================
# HAYSTACK COMPONENT FOR PIPELINE INTEGRATION
# ============================================================================

from haystack import component

@component
class GBIFComponent:
    """
    GBIF Component that handles fetching, flattening, and caching of core species data.
    """
    
    def __init__(self, use_ai_categorization: bool = True):
        """
        Initialize GBIF component.

        Note: raw_store must be set externally by the pipeline before use.
        This ensures session-isolated, species-specific cache paths are used.
        """
        self.raw_store = None  # Must be set by pipeline before use
        self.use_ai_categorization = use_ai_categorization
    
    @component.output_types(
        cached_data=Dict[str, Any],
        gbif_data=Dict[str, Any],
        cache_status=str
    )
    def run(self, species_name: str, raw_store=None) -> Dict[str, Any]:
        """
        Fetch GBIF data and save as raw JSON for AI categorization.

        Args:
            species_name: Scientific name to query
            raw_store: RawDataStore instance (from SynonymCoordinator in synonym-aware pipeline)
        """
        try:

            # Use provided raw_store if available, otherwise use instance variable (backward compatibility)
            if raw_store is not None:
                self.raw_store = raw_store

            raw_gbif_data = get_core_species_data(species_name)

            if not raw_gbif_data:
                return {
                    "cached_data": {}, "gbif_data": {},
                    "cache_status": "no_data"
                }

            # Save raw data for AI categorization
            self.raw_store.save_raw_data(species_name, "GBIF", raw_gbif_data)

            return {
                "cached_data": raw_gbif_data, "gbif_data": raw_gbif_data,
                "cache_status": "raw_saved"
            }

        except Exception as e:
            print(f"Error in GBIFComponent: {str(e)}")
            return {
                "cached_data": {}, "gbif_data": {}, "cache_status": "error"
            }

# ============================================================================
# HAYSTACK TOOL WRAPPER (Legacy Support)
# ============================================================================

gbif_tool = Tool(
    name="get_core_species_data",
    description="Gets comprehensive species data from GBIF. Returns a dictionary with taxonomy, scientific name, habitat details, locality-based distribution statuses, synonyms, vernacular names, descriptions, media (images/videos/sounds), bibliographic references, type specimens, child taxa (subspecies/varieties), and occurrence records with detailed geographic and institutional information.",
    parameters={
        "species_name": {"type": "string", "description": "The scientific or common name of the species (e.g., 'Panthera leo', 'Lepomis gibbosus')."}
    },
    function=get_core_species_data
)

# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    # Check if a species name was provided as a command-line argument
    if len(sys.argv) > 1:
        species_to_test = sys.argv[1]
    else:
        # Use a default species that has distribution data
        species_to_test = "Lepomis gibbosus" 

    print(f"--- Running GBIF Core Data test for taxon: '{species_to_test}' ---")
    
    # Call the main function to get the data
    species_data = get_core_species_data(species_to_test)
    
    # Check if data was returned and print it in a readable format
    if species_data:
        print("--- Successfully retrieved core data from GBIF: ---")
        # Use json.dumps for pretty-printing the dictionary
        print(json.dumps(species_data, indent=4))
    else:
        print(f"--- No data found for taxon: '{species_to_test}' ---")