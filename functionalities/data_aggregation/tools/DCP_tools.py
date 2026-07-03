#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
DCP Tools
JSON-based agent tools for querying species data.
Reads from AI-categorized data in cache/categorized_data/
"""

import os
import json
from typing import Dict, List, Any, Optional
from pathlib import Path

# ============================================================================
# CONSTANTS (Session-aware via centralized cache manager)
# ============================================================================

from core.utils.cache_manager import get_categorized_data_dir

# Note: Always use get_categorized_data_dir() function for session-aware paths

# ============================================================================
# JSON CACHE UTILITIES (Session-aware)
# ============================================================================

def load_categorized_species_json(species_name: str) -> Optional[Dict[str, Any]]:
    """Load AI-categorized species data from JSON cache (session-aware)."""
    categorized_dir = get_categorized_data_dir()
    safe_name = species_name.replace(' ', '_').replace('.', '').replace('/', '_')
    filename = f"{safe_name}_categorized.json"
    file_path = categorized_dir / filename

    if file_path.exists():
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def list_all_species() -> List[str]:
    """List all species in the JSON cache (session-aware)."""
    categorized_dir = get_categorized_data_dir()
    species_set = set()

    if categorized_dir.exists():
        for filename in os.listdir(categorized_dir):
            if filename.endswith('_categorized.json'):
                species_name = filename.replace('_categorized.json', '').replace('_', ' ')
                species_set.add(species_name)

    return sorted(list(species_set))

# ============================================================================
# AGENT QUERY FUNCTIONS
# ============================================================================

def get_species_overview(species_name: str) -> str:
    """Get a comprehensive overview of a species from AI-categorized data."""
    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return f"No categorized data found for species '{species_name}'."

    overview = [f"=== Species Overview: {species_name} ===\n"]
    overview.append(f"Data sources: {', '.join(categorized_data.get('sources', []))}")
    overview.append(f"Categorization timestamp: {categorized_data.get('timestamp', 'Unknown')}\n")

    # Taxonomic Identity
    tax_identity = categorized_data.get('categorized_fields', {}).get('taxonomic_identity', {})
    if tax_identity and 'taxonomy' in tax_identity:
        taxonomy = tax_identity['taxonomy'].get('value', {})
        if taxonomy:
            overview.append("--- Taxonomic Classification ---")
            for rank in ['kingdom', 'phylum', 'class', 'order', 'family', 'genus']:
                rank_upper = rank.upper()
                if rank_upper in taxonomy:
                    overview.append(f"  {rank.capitalize()}: {taxonomy[rank_upper]}")

    # Distribution
    distribution = categorized_data.get('categorized_fields', {}).get('distribution', {})
    if distribution and 'distribution_records' in distribution:
        records = distribution['distribution_records'].get('value', [])
        if records:
            overview.append(f"\n--- Distribution ---")
            overview.append(f"  {len(records)} location records")

    # Conservation
    conservation = categorized_data.get('categorized_fields', {}).get('conservation', {})
    if conservation and 'iucn_status' in conservation:
        status = conservation['iucn_status'].get('value')
        if status:
            overview.append(f"\n--- Conservation ---")
            overview.append(f"  IUCN Status: {status}")

    # EU IAS Regulation status
    # Fields are stored as lists by the multi-source categorizer: [{'value': True, ...}]
    def _get_field_value(field_data):
        if isinstance(field_data, list) and field_data:
            return field_data[0].get('value')
        if isinstance(field_data, dict):
            return field_data.get('value')
        return None

    management = categorized_data.get('categorized_fields', {}).get('management_biosecurity', {})
    if management:
        eu_flags = []
        if _get_field_value(management.get('is_eu_concern')):
            eu_flags.append("EU IAS Union Concern")
        if _get_field_value(management.get('is_ms_concern')):
            eu_flags.append("Member State Concern")
        if _get_field_value(management.get('is_horizon_scanning')):
            eu_flags.append("EU Horizon Scanning")
        if eu_flags:
            overview.append(f"\n--- EU Regulatory Status ---")
            for flag in eu_flags:
                overview.append(f"  {flag}")

    return "\n".join(overview)

def get_species_distribution(species_name: str) -> str:
    """Get distribution information for a species."""
    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return f"No categorized data found for species '{species_name}'."

    result = [f"=== Distribution: {species_name} ===\n"]

    distribution = categorized_data.get('categorized_fields', {}).get('distribution', {})
    if distribution and 'distribution_records' in distribution:
        records = distribution['distribution_records'].get('value', [])
        if isinstance(records, list):
            result.append("Locations:")
            for i, record in enumerate(records[:20]):  # Limit to first 20
                if isinstance(record, dict):
                    location = record.get('locality', 'Unknown')
                    status = record.get('establishment_status', 'Unknown')
                    result.append(f"  - {location} ({status})")
            
            if len(records) > 20:
                result.append(f"  ... and {len(records) - 20} more locations")
        else:
            result.append("No distribution data available.")
    else:
        result.append("No distribution data available.")

    return "\n".join(result)

def get_species_taxonomy(species_name: str) -> str:
    """Get taxonomic classification for a species."""
    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return f"No categorized data found for species '{species_name}'."

    result = [f"=== Taxonomy: {species_name} ===\n"]

    tax_identity = categorized_data.get('categorized_fields', {}).get('taxonomic_identity', {})

    if 'taxonomy' in tax_identity:
        taxonomy = tax_identity['taxonomy'].get('value', {})
        result.append("Classification:")
        for rank in ['kingdom', 'phylum', 'class', 'order', 'family', 'genus']:
            rank_upper = rank.upper()
            if rank_upper in taxonomy:
                result.append(f"  {rank.capitalize()}: {taxonomy[rank_upper]}")

    if 'synonyms' in tax_identity:
        synonyms = tax_identity['synonyms'].get('value', [])
        if synonyms:
            result.append(f"\nSynonyms ({len(synonyms)}):")
            for syn in synonyms[:10]:
                result.append(f"  - {syn}")
            if len(synonyms) > 10:
                result.append(f"  ... and {len(synonyms) - 10} more")

    return "\n".join(result)

def get_species_conservation(species_name: str) -> str:
    """Get conservation status for a species."""
    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return f"No categorized data found for species '{species_name}'."

    result = [f"=== Conservation Status: {species_name} ===\n"]

    conservation = categorized_data.get('categorized_fields', {}).get('conservation', {})
    found_data = False

    if 'iucn_status' in conservation:
        status = conservation['iucn_status'].get('value')
        if status:
            result.append(f"IUCN Status: {status}")
            found_data = True

    if 'population_trend' in conservation:
        trend = conservation['population_trend'].get('value')
        if trend:
            result.append(f"Population Trend: {trend}")
            found_data = True

    if 'threats' in conservation:
        threats = conservation['threats'].get('value', [])
        if threats:
            result.append(f"\nThreats ({len(threats)}):")
            for threat in threats[:5]:
                result.append(f"  - {threat}")
            found_data = True

    if not found_data:
        result.append("No conservation data available.")

    return "\n".join(result)

def search_species_by_keyword(keyword: str) -> str:
    """Search for species containing a keyword in their name."""
    all_species = list_all_species()
    keyword_lower = keyword.lower()

    matches = [sp for sp in all_species if keyword_lower in sp.lower()]

    if not matches:
        return f"No species found matching keyword '{keyword}'."

    result = [f"=== Species matching '{keyword}' ({len(matches)}) ===\n"]

    for species in matches[:20]:
        result.append(f"  - {species}")

    if len(matches) > 20:
        result.append(f"\n... and {len(matches) - 20} more species")

    return "\n".join(result)

def get_all_species_list() -> str:
    """Get a list of all cached species."""
    all_species = list_all_species()

    if not all_species:
        return "No species found in categorized cache."

    result = [f"=== All Categorized Species ({len(all_species)}) ===\n"]

    for species in all_species[:50]:
        result.append(f"  - {species}")

    if len(all_species) > 50:
        result.append(f"\n... and {len(all_species) - 50} more species")
        result.append(f"\nTotal: {len(all_species)} species")

    return "\n".join(result)

def get_species_habitat(species_name: str) -> str:
    """Get habitat information for a species."""
    categorized_data = load_categorized_species_json(species_name)

    if not categorized_data:
        return f"No categorized data found for species '{species_name}'."

    result = [f"=== Habitat: {species_name} ===\n"]

    env_tolerances = categorized_data.get('categorized_fields', {}).get('environmental_tolerances', {})
    found_data = False

    if 'habitat' in env_tolerances:
        habitat = env_tolerances['habitat'].get('value')
        if habitat:
            result.append(f"Habitat: {habitat}")
            found_data = True

    if 'habitats_list' in env_tolerances:
        habitats = env_tolerances['habitats_list'].get('value', [])
        if habitats:
            result.append(f"\nDetailed Habitats ({len(habitats)}):")
            for habitat in habitats[:10]:
                if isinstance(habitat, dict) and 'description' in habitat:
                    result.append(f"  - {habitat['description']}")
                elif isinstance(habitat, str):
                    result.append(f"  - {habitat}")
            found_data = True

    if not found_data:
        result.append("No habitat data available.")

    return "\n".join(result)

def get_cache_statistics() -> str:
    """Get statistics about the categorized JSON cache (session-aware)."""
    categorized_dir = get_categorized_data_dir()

    if not categorized_dir.exists():
        return "Categorized cache directory does not exist."

    species_count = len(list_all_species())
    total_files = 0
    total_size = 0

    for filename in os.listdir(categorized_dir):
        if filename.endswith('_categorized.json'):
            total_files += 1
            file_path = categorized_dir / filename
            total_size += os.path.getsize(file_path)

    size_mb = total_size / (1024 * 1024)

    result = []
    result.append("=== Categorized Cache Statistics ===\n")
    result.append(f"Total species: {species_count}")
    result.append(f"Total files: {total_files}")
    result.append(f"Cache size: {size_mb:.2f} MB")

    return "\n".join(result)
