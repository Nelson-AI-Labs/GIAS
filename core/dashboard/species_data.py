#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Data Functions
Core data retrieval functions for species information across all categories.
This module contains the actual implementations for all get_*_data() functions.
"""

import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from core.dashboard.data_loaders import (
    load_categorized_species_json,
    get_category_data,
    extract_multi_source_field,
    merge_multi_source_list,
)
from core.utils.cache_manager import get_cache_manager


def get_taxonomic_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get complete structured taxonomic data from AI-categorized JSON with multi-source support."""
    default_data = {
        "species_name": species_name,
        "kingdom": "Unknown",
        "phylum": "Unknown",
        "class": "Unknown",
        "order": "Unknown",
        "family": "Unknown",
        "genus": "Unknown",
        "authority": "Unknown",
        "taxonomic_rank": "Unknown",
        "taxonomic_status": "Unknown",
        "synonyms": [],
        "synonyms_count": 0,
        "vernacular_names": {},
        "vernacular_names_count": 0,
        "children_taxa": [],
        "children_count": 0,
        "etymology": None,
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    tax_identity = get_category_data(species_name, 'taxonomic_identity', universal_id=universal_id)

    if not tax_identity:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Process all taxonomic ranks: collect values from BOTH individual fields AND taxonomy dict
    # Then merge them and detect conflicts across ALL sources

    for field in ['kingdom', 'phylum', 'class', 'order', 'family', 'genus']:
        print(f"\n   Processing rank: {field}")
        rank_values = {}

        # Step 1: Collect values from individual fields (if present)
        if field in tax_identity:
            print(f"     Found individual field data for '{field}'")
            individual_field_data = tax_identity[field]

            if isinstance(individual_field_data, list):
                for entry in individual_field_data:
                    if not isinstance(entry, dict):
                        continue

                    value = entry.get('value')
                    source = entry.get('source', 'Unknown')

                    if value:
                        # Normalize for comparison (case-insensitive)
                        normalized_key = str(value).lower().strip()

                        if normalized_key not in rank_values:
                            rank_values[normalized_key] = {
                                'original_value': value,
                                'sources': []
                            }
                        rank_values[normalized_key]['sources'].append(source)
                        print(f"       Individual field - Source {source}: {field} = {value}")

        # Step 2: Collect values from taxonomy dict (if present)
        if 'taxonomy' in tax_identity:
            taxonomy_sources = tax_identity['taxonomy']

            for source_entry in taxonomy_sources:
                if not isinstance(source_entry, dict):
                    continue

                source = source_entry.get('source', 'Unknown')
                taxonomy_dict = source_entry.get('value')

                if not isinstance(taxonomy_dict, dict):
                    continue

                # Try lowercase field name first, then uppercase
                value = taxonomy_dict.get(field) or taxonomy_dict.get(field.upper())

                if value:
                    # Normalize for comparison (case-insensitive)
                    normalized_key = str(value).lower().strip()

                    if normalized_key not in rank_values:
                        rank_values[normalized_key] = {
                            'original_value': value,
                            'sources': []
                        }
                    rank_values[normalized_key]['sources'].append(source)
                    print(f"       Taxonomy dict - Source {source}: {field} = {value}")

        # Step 3: Analyze collected values and detect conflicts
        if rank_values:
            print(f"     Total unique values found: {len(rank_values)}")
            for norm_key, info in rank_values.items():
                print(f"       - {info['original_value']} (from {', '.join(info['sources'])})")

            # Check if there's a conflict (multiple unique values)
            if len(rank_values) > 1:
                # Conflict detected! Store it
                data['conflicts'][field] = [
                    {'value': info['original_value'], 'sources': info['sources']}
                    for info in rank_values.values()
                ]
                print(f"     CONFLICT DETECTED for {field}!")
                print(f"     Stored {len(rank_values)} conflicting values in data['conflicts']['{field}']")

            # Set primary value (most common, or first if tied)
            primary = max(rank_values.values(), key=lambda x: len(x['sources']))
            data[field] = primary['original_value']
            print(f"     Primary value set: {primary['original_value']} ({len(primary['sources'])} sources)")
        else:
            print(f"     No values found for {field}")

    # Extract other taxonomic fields with multi-source support
    for field in ['species_name', 'authority', 'taxonomic_rank', 'taxonomic_status']:
        if field in tax_identity:
            field_info = extract_multi_source_field(tax_identity[field])
            if field_info['primary_value']:
                data[field] = field_info['primary_value']

    # Extract synonyms — union across ALL sources, not just the primary one
    if 'synonyms' in tax_identity:
        data['synonyms'] = merge_multi_source_list(tax_identity['synonyms'])

    # Extract vernacular names — union across ALL sources, grouped by language.
    # Dedup on (name, language) so the same name from two sources counts once;
    # the frontend normalizes language codes/names for display.
    if 'vernacular_names' in tax_identity:
        merged = merge_multi_source_list(
            tax_identity['vernacular_names'],
            key_fn=lambda it: (it['name'].strip().lower(), str(it.get('language', '')).strip().lower()),
        )
        for item in merged:
            if isinstance(item, dict) and 'name' in item and 'language' in item:
                data['vernacular_names'].setdefault(item['language'], []).append(item['name'])

    # Extract children taxa — union across ALL sources
    if 'children_taxa' in tax_identity:
        data['children_taxa'] = merge_multi_source_list(tax_identity['children_taxa'])

    # Extract etymology data
    if 'etymology' in tax_identity:
        field_info = extract_multi_source_field(tax_identity['etymology'])
        if field_info['primary_value']:
            # Etymology is stored as a dict with classification, value, reference, and quality_status
            if isinstance(field_info['primary_value'], dict):
                data['etymology'] = field_info['primary_value']
            else:
                data['etymology'] = None
        else:
            data['etymology'] = None
    else:
        data['etymology'] = None

    # Calculate counts
    data['synonyms_count'] = len(data['synonyms'])
    data['vernacular_names_count'] = sum(len(v) for v in data['vernacular_names'].values())
    data['children_count'] = len(data['children_taxa'])

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])


    return data


def get_distribution_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get distribution data from AI-categorized JSON with multi-source support."""
    default_data = {
        "native_locations": [],
        "established_locations": [],
        "uncertain_locations": [],
        "native_locations_count": 0,
        "established_locations_count": 0,
        "uncertain_locations_count": 0,
        "total_records": 0,
        "recent_observations": [],
        "native_range_descriptions": [],
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    distribution = get_category_data(species_name, 'distribution', universal_id=universal_id)

    if not distribution:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    native_locs = set()
    established_locs = set()
    uncertain_locs = set()

    # Extract distribution records with multi-source support
    if 'distribution_records' in distribution:
        field_info = extract_multi_source_field(distribution['distribution_records'])
        records = field_info['primary_value']
        if isinstance(records, list):
            for record in records:
                if isinstance(record, dict):
                    location = record.get('locality')
                    if not location:
                        continue

                    means = (record.get('establishment_means') or '').lower()
                    status = (record.get('establishment_status') or '').lower()

                    if 'native' in means:
                        native_locs.add(location)
                    elif 'established' in status:
                        established_locs.add(location)
                    else:
                        uncertain_locs.add(location)

    # Extract occurrence samples with multi-source support
    if 'occurrence_sample' in distribution:
        field_info = extract_multi_source_field(distribution['occurrence_sample'])
        occs = field_info['primary_value']
        if isinstance(occs, list):
            for occ in occs:
                if isinstance(occ, dict):
                    country_code = occ.get('countryCode', '')
                    locality = occ.get('locality', '')
                    water_body = occ.get('waterBody', '')
                    state_province = occ.get('stateProvince', '')
                    recorded_by = occ.get('recordedBy', '')
                    event_date = occ.get('eventDate', '')

                    # Extract rich specimen metadata
                    basis_of_record = occ.get('basisOfRecord', '')
                    institution_code = occ.get('institutionCode', '')
                    catalog_number = occ.get('catalogNumber', '')
                    individual_count = occ.get('individualCount', '')

                    display_location = country_code or locality or water_body or "Unknown Location"

                    data['recent_observations'].append({
                        'country_code': country_code,
                        'location': display_location,
                        'locality': locality,
                        'water_body': water_body,
                        'state_province': state_province,
                        'date': event_date or 'Unknown date',
                        'recorded_by': recorded_by,
                        'basis_of_record': basis_of_record,
                        'institution_code': institution_code,
                        'catalog_number': catalog_number,
                        'individual_count': individual_count,
                        'coordinates': {
                            'lat': occ.get('decimalLatitude'),
                            'lon': occ.get('decimalLongitude')
                        }
                    })

    # Sort occurrences by date (newest first)
    data['recent_observations'].sort(key=lambda x: x['date'], reverse=True)

    # Group occurrences by country
    occurrences_by_country = {}
    for obs in data['recent_observations']:
        country = obs['country_code'] or 'Unknown'
        if country not in occurrences_by_country:
            occurrences_by_country[country] = []
        occurrences_by_country[country].append(obs)

    data['occurrences_by_country'] = occurrences_by_country
    data['total_occurrences'] = len(data['recent_observations'])
    data['occurrences_with_coordinates'] = sum(1 for obs in data['recent_observations']
                                               if obs['coordinates']['lat'] and obs['coordinates']['lon'])
    data['occurrences_with_water_bodies'] = sum(1 for obs in data['recent_observations']
                                                 if obs.get('water_body'))

    # Extract ALL native range descriptions (not just primary)
    if 'native_range' in distribution:
        native_range_entries = distribution['native_range']
        if isinstance(native_range_entries, list):
            for entry in native_range_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    range_value = entry['value']
                    if isinstance(range_value, dict):
                        description = range_value.get('description', '')
                        source = range_value.get('source', 'Unknown')
                        if description:
                            data['native_range_descriptions'].append({
                                'description': description,
                                'source': source
                            })

    data['native_locations'] = sorted(list(native_locs))
    data['established_locations'] = sorted(list(established_locs))
    data['uncertain_locations'] = sorted(list(uncertain_locs))
    data['native_locations_count'] = len(data['native_locations'])
    data['established_locations_count'] = len(data['established_locations'])
    data['uncertain_locations_count'] = len(data['uncertain_locations'])
    data['total_records'] = len(native_locs) + len(established_locs) + len(uncertain_locs)

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_environmental_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get habitat and ecology data from AI-categorized JSON with multi-source support."""
    default_data = {
        "habitat": "Unknown",
        "ecological_zone": "Unknown",
        "habitat_records": [],
        "water_systems": [],
        "habitat_descriptions": [],
        "habitat_types": [],
        "ecological_roles": [],
        "habitat_ecology_text": [],
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    env_tolerances = get_category_data(species_name, 'habitat_ecology', universal_id=universal_id)

    if not env_tolerances:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract habitat with multi-source support
    if 'habitat' in env_tolerances:
        field_info = extract_multi_source_field(env_tolerances['habitat'])
        if field_info['primary_value']:
            data['habitat'] = field_info['primary_value']

    # Extract habitats list with multi-source support
    if 'habitats_list' in env_tolerances:
        field_info = extract_multi_source_field(env_tolerances['habitats_list'])
        habitats = field_info['primary_value']
        if isinstance(habitats, list):
            data['habitat_records'] = habitats
            # Extract descriptions (handle dict format from IUCN data)
            for habitat in habitats:
                if isinstance(habitat, dict) and 'description' in habitat:
                    description_dict = habitat['description']
                    if isinstance(description_dict, dict):
                        # Extract English or first available language
                        description_text = description_dict.get('en') or next(iter(description_dict.values()), '')
                        data['habitat_descriptions'].append(description_text)
                    else:
                        data['habitat_descriptions'].append(str(description_dict))

    # Extract ALL EUNIS habitat types
    if 'habitat_types' in env_tolerances:
        habitat_types_entries = env_tolerances['habitat_types']
        if isinstance(habitat_types_entries, list):
            for entry in habitat_types_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    habitat_value = entry['value']
                    if isinstance(habitat_value, dict):
                        description = habitat_value.get('description', '')
                        source = habitat_value.get('source', 'Unknown')
                        if description:
                            data['habitat_types'].append({
                                'description': description,
                                'source': source
                            })

    # Extract ALL ecological roles
    if 'ecological_role' in env_tolerances:
        ecological_role_entries = env_tolerances['ecological_role']
        if isinstance(ecological_role_entries, list):
            for entry in ecological_role_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    role_value = entry['value']
                    if isinstance(role_value, dict):
                        description = role_value.get('description', '')
                        source = role_value.get('source', 'Unknown')
                        if description:
                            data['ecological_roles'].append({
                                'description': description,
                                'source': source
                            })

    # Extract habitat ecology text
    if 'habitat_ecology_text' in env_tolerances:
        field_info = extract_multi_source_field(env_tolerances['habitat_ecology_text'])
        if field_info['primary_value']:
            data['habitat_ecology_text'] = field_info['primary_value']

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_morphological_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get morphological traits data from AI-categorized JSON with multi-source support."""
    default_data = {
        "morphological_attributes": [],
        "morphological_attributes_count": 0,
        "attributes_by_type": {},
        "quality_summary": {},
        "measurement_types": [],
        "data_sources": []
    }

    data = default_data.copy()
    morph_traits = get_category_data(species_name, 'morphological_traits', universal_id=universal_id)

    if not morph_traits:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract all morphological trait fields (each field is a separate trait)
    all_attributes = []
    attributes_by_type = {}
    quality_summary = {}
    measurement_types = set()

    for field_name, field_data in morph_traits.items():
        # Extract the trait value using multi-source support
        field_info = extract_multi_source_field(field_data)
        trait_value = field_info['primary_value']

        if trait_value and isinstance(trait_value, dict):
            # Get source information from the first entry in field_data
            source = 'Unknown'
            if isinstance(field_data, list) and len(field_data) > 0:
                source = field_data[0].get('source', 'Unknown')

            # Create enhanced attribute dict with metadata
            enhanced_attr = {
                'field_name': field_name,
                'measurement_type': trait_value.get('measurement_type', 'Other'),
                'value': trait_value.get('value', 'N/A'),
                'reference': trait_value.get('reference', ''),
                'quality_status': trait_value.get('quality_status', 'unknown'),
                'type_id': trait_value.get('type_id'),
                'source': source
            }

            all_attributes.append(enhanced_attr)

            # Group by measurement type
            mtype = enhanced_attr['measurement_type']
            measurement_types.add(mtype)
            if mtype not in attributes_by_type:
                attributes_by_type[mtype] = []
            attributes_by_type[mtype].append(enhanced_attr)

            # Count quality statuses
            quality = enhanced_attr['quality_status']
            quality_summary[quality] = quality_summary.get(quality, 0) + 1

    data['morphological_attributes'] = all_attributes
    data['morphological_attributes_count'] = len(all_attributes)
    data['attributes_by_type'] = attributes_by_type
    data['quality_summary'] = quality_summary
    data['measurement_types'] = sorted(list(measurement_types))

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_physiological_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get physiological traits data from AI-categorized JSON with multi-source support."""
    default_data = {
        "physiological_attributes": [],
        "physiological_attributes_count": 0,
        "attributes_by_type": {},
        "quality_summary": {},
        "measurement_types": [],
        "data_sources": []
    }

    data = default_data.copy()
    physio_traits = get_category_data(species_name, 'physiological_traits', universal_id=universal_id)

    if not physio_traits:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract all physiological trait fields (each field is a separate trait)
    all_attributes = []
    attributes_by_type = {}
    quality_summary = {}
    measurement_types = set()

    for field_name, field_data in physio_traits.items():
        # Extract the trait value using multi-source support
        field_info = extract_multi_source_field(field_data)
        trait_value = field_info['primary_value']

        if trait_value and isinstance(trait_value, dict):
            # Get source information from the first entry in field_data
            source = 'Unknown'
            if isinstance(field_data, list) and len(field_data) > 0:
                source = field_data[0].get('source', 'Unknown')

            # Create enhanced attribute dict with metadata
            enhanced_attr = {
                'field_name': field_name,
                'measurement_type': trait_value.get('measurement_type', 'Other'),
                'value': trait_value.get('value', 'N/A'),
                'reference': trait_value.get('reference', ''),
                'quality_status': trait_value.get('quality_status', 'unknown'),
                'type_id': trait_value.get('type_id'),
                'source': source
            }

            all_attributes.append(enhanced_attr)

            # Group by measurement type
            mtype = enhanced_attr['measurement_type']
            measurement_types.add(mtype)
            if mtype not in attributes_by_type:
                attributes_by_type[mtype] = []
            attributes_by_type[mtype].append(enhanced_attr)

            # Count quality statuses
            quality = enhanced_attr['quality_status']
            quality_summary[quality] = quality_summary.get(quality, 0) + 1

    data['physiological_attributes'] = all_attributes
    data['physiological_attributes_count'] = len(all_attributes)
    data['attributes_by_type'] = attributes_by_type
    data['quality_summary'] = quality_summary
    data['measurement_types'] = sorted(list(measurement_types))

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_biological_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get morphological and physiological traits data from AI-categorized JSON with multi-source support."""
    default_data = {
        "biological_attributes": [],
        "biological_attributes_count": 0,
        "attributes_by_type": {},
        "measurements_summary": {},
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    # Combine morphological and physiological traits
    morph_traits = get_category_data(species_name, 'morphological_traits', universal_id=universal_id)
    physio_traits = get_category_data(species_name, 'physiological_traits', universal_id=universal_id)

    # Merge both categories (if both exist)
    bio_traits = {}
    if morph_traits:
        bio_traits.update(morph_traits)
    if physio_traits:
        # Merge physiological data
        for key, value in physio_traits.items():
            if key in bio_traits and isinstance(bio_traits[key], list) and isinstance(value, list):
                bio_traits[key].extend(value)
            else:
                bio_traits[key] = value

    if not bio_traits:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract attributes with multi-source support
    if 'attributes' in bio_traits:
        field_info = extract_multi_source_field(bio_traits['attributes'])
        attrs = field_info['primary_value']
        if isinstance(attrs, list):
            data['biological_attributes'] = attrs
            data['biological_attributes_count'] = len(attrs)

            # Group attributes by measurement_type
            attributes_by_type = {}
            quality_summary = {}
            measurement_types = set()

            for attr in attrs:
                if isinstance(attr, dict):
                    # Group by measurement type
                    mtype = attr.get('measurement_type', 'Other')
                    measurement_types.add(mtype)
                    if mtype not in attributes_by_type:
                        attributes_by_type[mtype] = []
                    attributes_by_type[mtype].append(attr)

                    # Count quality statuses
                    quality = attr.get('quality_status', 'unknown')
                    quality_summary[quality] = quality_summary.get(quality, 0) + 1

            data['attributes_by_type'] = attributes_by_type
            data['quality_summary'] = quality_summary
            data['measurement_types'] = sorted(list(measurement_types))

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_conservation_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get conservation status data from AI-categorized JSON with multi-source support."""
    default_data = {
        "iucn_status": "Unknown",
        "conservation_assessments": [],
        "population_trend": "Unknown",
        "assessment_date": "Unknown",
        "rationale": "",
        "threats": [],
        "stresses": [],
        "conservation_measures": [],
        "population_details": {},
        "historical_assessments": [],
        "societal_importance": [],
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    conservation = get_category_data(species_name, 'conservation_status', universal_id=universal_id)

    if not conservation:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract IUCN status from nested conservation_status field
    if 'conservation_status' in conservation:
        field_info = extract_multi_source_field(conservation['conservation_status'])
        if field_info['primary_value'] and isinstance(field_info['primary_value'], dict):
            # Extract iucn_category from nested structure
            if 'iucn_category' in field_info['primary_value']:
                data['iucn_status'] = field_info['primary_value']['iucn_category']

            # Extract population trend from nested structure
            if 'population_trend' in field_info['primary_value']:
                trend_data = field_info['primary_value']['population_trend']
                if isinstance(trend_data, dict):
                    # Handle nested description structure like {"description": {"en": "Increasing"}}
                    if 'description' in trend_data and isinstance(trend_data['description'], dict):
                        data['population_trend'] = trend_data['description'].get('en', 'Unknown')
                    elif 'description' in trend_data:
                        data['population_trend'] = trend_data['description']
                else:
                    data['population_trend'] = trend_data

            # Extract assessment date
            if 'assessment_date' in field_info['primary_value']:
                data['assessment_date'] = field_info['primary_value']['assessment_date']

            # Extract rationale
            if 'rationale' in field_info['primary_value']:
                rationale = field_info['primary_value']['rationale']
                if rationale and rationale.strip():
                    data['rationale'] = rationale

    # Extract threats with multi-source support
    if 'threats' in conservation:
        field_info = extract_multi_source_field(conservation['threats'])
        threats = field_info['primary_value']
        if isinstance(threats, list):
            data['threats'] = threats

    # Extract stresses with multi-source support
    if 'stresses' in conservation:
        field_info = extract_multi_source_field(conservation['stresses'])
        stresses = field_info['primary_value']
        if isinstance(stresses, list):
            data['stresses'] = stresses

    # Extract conservation measures with multi-source support
    if 'conservation_measures' in conservation:
        field_info = extract_multi_source_field(conservation['conservation_measures'])
        measures = field_info['primary_value']
        if isinstance(measures, list):
            data['conservation_measures'] = measures

    # Extract detailed population information
    if 'population' in conservation:
        field_info = extract_multi_source_field(conservation['population'])
        pop_data = field_info['primary_value']
        if isinstance(pop_data, dict):
            data['population_details'] = {
                'size': pop_data.get('size'),
                'severely_fragmented': pop_data.get('severely_fragmented'),
                'number_of_locations': pop_data.get('number_of_locations'),
                'number_of_mature_individuals': pop_data.get('number_of_mature_individuals'),
                'text': pop_data.get('text', '')
            }

    # Extract historical assessments
    if 'historical_assessments' in conservation:
        field_info = extract_multi_source_field(conservation['historical_assessments'])
        history = field_info['primary_value']
        if isinstance(history, list):
            data['historical_assessments'] = history

    # Extract societal importance
    if 'societal_importance' in conservation:
        societal_entries = conservation['societal_importance']
        if isinstance(societal_entries, list):
            for entry in societal_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    importance_value = entry['value']
                    if isinstance(importance_value, dict):
                        value = importance_value.get('value', '')
                        reference = importance_value.get('reference', '')
                        if value:
                            data['societal_importance'].append({
                                'value': value,
                                'reference': reference
                            })

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


# Database folders whose stored URL field does not follow the "{folder}_url"
# convention. WRiMS data is fetched from the WoRMS REST API, so its link is
# stored under 'worms_url' (the key used throughout the rest of the codebase),
# not 'wrims_url'.
_DB_URL_KEY_OVERRIDES = {
    'WRiMS': 'worms_url',
}


def get_available_databases(species_name: str, universal_id: Optional[str] = None) -> List[str]:
    """
    Get list of databases that have raw API data for this species.

    Dynamically discovers databases by scanning the raw_api_data folder structure.

    Args:
        species_name: Scientific name of the species
        universal_id: Optional universal species identifier

    Returns:
        List of database names (e.g., ['GBIF', 'WRiMS', 'IUCN', 'EASIN', 'AquaNIS'])
    """
    if not universal_id:
        return []

    # Use session-aware cache manager
    cache_manager = get_cache_manager()
    raw_data_dir = cache_manager.raw_api_data_dir() / universal_id

    if not raw_data_dir.exists():
        return []

    # Get all subdirectories (each represents a database)
    databases = []
    try:
        for item in raw_data_dir.iterdir():
            if item.is_dir():
                # Check if directory has any JSON files (actual data)
                json_files = list(item.glob('*.json'))
                if json_files:
                    databases.append(item.name)
    except Exception as e:
        print(f"Error scanning raw_api_data directory: {e}")
        return []

    return sorted(databases)


def get_database_url_from_raw_data(database_name: str, species_name: str, universal_id: Optional[str] = None) -> Optional[str]:
    """
    Extract database URL from raw API data JSON files.

    Looks for URL fields like 'easin_url', 'gbif_url', etc. in the raw data.

    Args:
        database_name: Name of the database (e.g., 'EASIN', 'GBIF')
        species_name: Scientific name of the species
        universal_id: Optional universal species identifier

    Returns:
        URL string or None if not found
    """
    if not universal_id:
        return None

    # Use session-aware cache manager
    cache_manager = get_cache_manager()
    raw_data_dir = cache_manager.raw_api_data_dir() / universal_id / database_name

    if not raw_data_dir.exists():
        return None

    # Look for JSON files in the database directory
    json_files = list(raw_data_dir.glob('*.json'))
    if not json_files:
        return None

    # Read the first JSON file (usually there's one per species name variant)
    try:
        with open(json_files[0], 'r', encoding='utf-8') as f:
            raw_data = json.load(f)

        # Try to find URL field (common patterns: easin_url, gbif_url, worms_url, etc.)
        url_key = _DB_URL_KEY_OVERRIDES.get(database_name, f"{database_name.lower()}_url")

        # Check in data section (incl. the metadata envelope WRiMS/WoRMS uses)
        if 'data' in raw_data and isinstance(raw_data['data'], dict):
            if url_key in raw_data['data']:
                return raw_data['data'][url_key]
            data_metadata = raw_data['data'].get('metadata')
            if isinstance(data_metadata, dict) and url_key in data_metadata:
                return data_metadata[url_key]

        # Check at root level
        if url_key in raw_data:
            return raw_data[url_key]

    except Exception as e:
        print(f"Error reading raw data for {database_name}: {e}")
        return None

    return None


def _build_wrims_introduced_url(envelope: Dict[str, Any], worms_url: str) -> Optional[str]:
    """Build the WRiMS introduced-register URL for a WoRMS record.

    Prefers the AphiaID stored in the data envelope's metadata; falls back to
    parsing it out of the WoRMS taxonomy URL (…/aphia.php?p=taxdetails&id=NNN).
    Returns None if no AphiaID can be determined.
    """
    aphia_id = None
    data_section = envelope.get('data')
    if isinstance(data_section, dict):
        meta = data_section.get('metadata')
        if isinstance(meta, dict):
            aphia_id = meta.get('aphia_id')

    if not aphia_id and worms_url and 'id=' in worms_url:
        aphia_id = worms_url.split('id=')[-1].split('&')[0]

    if not aphia_id:
        return None
    return f"https://www.marinespecies.org/introduced/aphia.php?p=taxdetails&id={aphia_id}"


def get_all_database_links_with_species(universal_id: str) -> List[Dict[str, str]]:
    """
    Get all database URLs with their associated species names (synonym variants).

    Scans the raw_api_data folder structure to find all database+species combinations.

    Args:
        universal_id: Universal species identifier (e.g., "2227300_procambarus_clarkii")

    Returns:
        List of dicts with 'database', 'species_name', and 'url' keys
    """
    if not universal_id:
        return []

    # Use session-aware cache manager
    cache_manager = get_cache_manager()
    raw_data_dir = cache_manager.raw_api_data_dir() / universal_id
    if not raw_data_dir.exists():
        return []

    links = []

    # Scan each database folder
    for db_folder in raw_data_dir.iterdir():
        if not db_folder.is_dir():
            continue

        database_name = db_folder.name

        # Scan each JSON file in the database folder
        for json_file in db_folder.glob('*.json'):
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Extract species name from metadata
                species_name = data.get('metadata', {}).get('species_name', 'Unknown')

                # Look for URL in multiple locations. The URL field usually
                # matches the folder name ("{db}_url"), but the WRiMS folder
                # stores its link under 'worms_url' (the data comes from the
                # WoRMS REST API) — the rest of the codebase uses that key too.
                url_key = _DB_URL_KEY_OVERRIDES.get(database_name, f"{database_name.lower()}_url")
                url = None

                # Priority 1: Check data.metadata section (most common location)
                if 'data' in data and isinstance(data['data'], dict):
                    if 'metadata' in data['data'] and isinstance(data['data']['metadata'], dict):
                        url = data['data']['metadata'].get(url_key)

                    # Priority 2: Check top level of data section (EASIN uses this)
                    if not url:
                        url = data['data'].get(url_key)

                # Add to links if URL exists and is valid
                if url and url not in ['Unknown', 'None', None, '']:
                    link = {
                        'database': database_name,
                        'species_name': species_name,
                        'url': url
                    }
                    # WRiMS: also expose the WRiMS introduced-register page
                    # (a different view from the general WoRMS taxonomy page),
                    # derived from the AphiaID.
                    if database_name == 'WRiMS':
                        introduced_url = _build_wrims_introduced_url(data, url)
                        if introduced_url:
                            link['introduced_url'] = introduced_url
                    links.append(link)

            except Exception as e:
                print(f"Error reading {json_file}: {e}")
                continue

    return links


def get_species_metadata(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get species metadata including database keys."""
    default_data = {
        "gbif_key": None,
        "aphia_id": None,
        "iucn_taxon_id": None,
        "match_type": "Unknown",
        "data_source": "Unknown"
    }

    data = default_data.copy()
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)

    if not categorized_data:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Get sources
    sources = categorized_data.get('sources', [])
    if sources:
        data['data_source'] = ', '.join(sources)

    # Extract metadata
    metadata_category = get_category_data(species_name, 'data_metadata', universal_id=universal_id)

    # The metadata is stored in a 'metadata' field as an array with nested dict values
    if 'metadata' in metadata_category:
        metadata_info = extract_multi_source_field(metadata_category['metadata'])
        metadata_dict = metadata_info['primary_value']

        if isinstance(metadata_dict, dict):
            if 'gbif_key' in metadata_dict:
                data['gbif_key'] = metadata_dict['gbif_key']
            if 'aphia_id' in metadata_dict:
                data['aphia_id'] = metadata_dict['aphia_id']
            if 'iucn_taxon_id' in metadata_dict:
                data['iucn_taxon_id'] = metadata_dict['iucn_taxon_id']
            if 'match_type' in metadata_dict:
                data['match_type'] = metadata_dict['match_type']

    # Fallback: Try direct field access (legacy format or alternate structure)
    if data['gbif_key'] is None and 'gbif_key' in metadata_category:
        field_info = extract_multi_source_field(metadata_category['gbif_key'])
        if field_info['primary_value']:
            data['gbif_key'] = field_info['primary_value']

    if data['aphia_id'] is None and 'aphia_id' in metadata_category:
        field_info = extract_multi_source_field(metadata_category['aphia_id'])
        if field_info['primary_value']:
            data['aphia_id'] = field_info['primary_value']

    if data['iucn_taxon_id'] is None and 'iucn_taxon_id' in metadata_category:
        field_info = extract_multi_source_field(metadata_category['iucn_taxon_id'])
        if field_info['primary_value']:
            data['iucn_taxon_id'] = field_info['primary_value']

    if data['match_type'] == 'Unknown' and 'match_type' in metadata_category:
        field_info = extract_multi_source_field(metadata_category['match_type'])
        if field_info['primary_value']:
            data['match_type'] = field_info['primary_value']

    return data


# New category data fetchers
def get_species_interactions_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get species interactions data from AI-categorized JSON."""
    default_data = {
        "interactions": [],
        "predators": [],
        "prey": [],
        "competitors": [],
        "parasites": [],
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    interactions = get_category_data(species_name, 'species_interactions', universal_id=universal_id)

    if not interactions:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract interactions data (to be implemented when data becomes available)
    # This will be populated as the AI categorizes relevant fields

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_impacts_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get ecological and economic impacts data from AI-categorized JSON."""
    default_data = {
        "impact_remarks": [],
        "ecological_impacts": [],
        "data_sources": []
    }

    data = default_data.copy()
    impacts = get_category_data(species_name, 'impacts', universal_id=universal_id)

    if not impacts:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract ALL impact remarks (general/mixed impact information)
    if 'impact_remarks' in impacts:
        remark_entries = impacts['impact_remarks']
        if isinstance(remark_entries, list):
            for entry in remark_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    remark_value = entry['value']
                    if isinstance(remark_value, dict):
                        description = remark_value.get('description', '')
                        source = remark_value.get('source', 'Unknown')
                        remark_type = remark_value.get('type', '')
                        note = entry.get('note', '')

                        if description:
                            data['impact_remarks'].append({
                                'description': description,
                                'source': source,
                                'type': remark_type,
                                'note': note
                            })

    # Extract ALL ecological impacts
    if 'ecological_impacts' in impacts:
        impact_entries = impacts['ecological_impacts']
        if isinstance(impact_entries, list):
            for entry in impact_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    impact_value = entry['value']
                    if isinstance(impact_value, dict):
                        description = impact_value.get('description', '')
                        source = impact_value.get('source', 'Unknown')
                        impact_type = impact_value.get('type', '')

                        if description:
                            data['ecological_impacts'].append({
                                'description': description,
                                'source': source,
                                'type': impact_type
                            })

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_management_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get management and biosecurity data from AI-categorized JSON."""
    default_data = {
        "prevention_measures": [],
        "control_methods": [],
        "eradication_attempts": [],
        "regulations": [],
        "legal_status": "Unknown",
        "is_eu_concern": None,       # EU IAS Regulation Union Concern list (bool or None)
        "is_ms_concern": None,       # Member State concern list (bool or None)
        "is_horizon_scanning": None, # EU horizon scanning list (bool or None)
        "pathways": [],
        "invasion_stage": "",
        "dispersal_vectors": [],
        "establishment_degree": "",
        "abundance": [],
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    management = get_category_data(species_name, 'management_biosecurity', universal_id=universal_id)

    if not management:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract EU regulatory status flags (direct boolean values from EASIN)
    for flag in ('is_eu_concern', 'is_ms_concern', 'is_horizon_scanning'):
        if flag in management:
            field_info = extract_multi_source_field(management[flag])
            if field_info['primary_value'] is not None:
                data[flag] = field_info['primary_value']

    # Extract ALL introduction pathways
    if 'pathways' in management:
        pathway_entries = management['pathways']
        if isinstance(pathway_entries, list):
            for entry in pathway_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    pathway_value = entry['value']
                    if isinstance(pathway_value, dict):
                        description = pathway_value.get('description', '')
                        source = pathway_value.get('source', 'Unknown')
                        if description:
                            data['pathways'].append({
                                'description': description,
                                'source': source
                            })

    # Extract invasion stage (primary value)
    if 'invasion_stage' in management:
        field_info = extract_multi_source_field(management['invasion_stage'])
        if field_info['primary_value'] and isinstance(field_info['primary_value'], dict):
            data['invasion_stage'] = field_info['primary_value'].get('description', '')

    # Extract ALL dispersal vectors
    if 'dispersal_vectors' in management:
        vector_entries = management['dispersal_vectors']
        if isinstance(vector_entries, list):
            for entry in vector_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    vector_value = entry['value']
                    if isinstance(vector_value, dict):
                        description = vector_value.get('description', '')
                        source = vector_value.get('source', 'Unknown')
                        if description:
                            data['dispersal_vectors'].append({
                                'description': description,
                                'source': source
                            })

    # Extract establishment degree (primary value)
    if 'establishment_degree' in management:
        field_info = extract_multi_source_field(management['establishment_degree'])
        if field_info['primary_value'] and isinstance(field_info['primary_value'], dict):
            data['establishment_degree'] = field_info['primary_value'].get('description', '')

    # Extract ALL abundance information
    if 'abundance' in management:
        abundance_entries = management['abundance']
        if isinstance(abundance_entries, list):
            for entry in abundance_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    abundance_value = entry['value']
                    if isinstance(abundance_value, dict):
                        description = abundance_value.get('description', '')
                        source = abundance_value.get('source', 'Unknown')
                        if description:
                            data['abundance'].append({
                                'description': description,
                                'source': source
                            })

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_economic_utilisation_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get economic utilisation data from AI-categorized JSON."""
    default_data = {
        "societal_importance": [],
        "commercial_uses": [],
        "fisheries": [],
        "aquaculture": [],
        "ornamental_trade": [],
        "market_value": "Unknown",
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    econ_util = get_category_data(species_name, 'economic_utilisation', universal_id=universal_id)

    if not econ_util:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract societal importance (FAO-ASFIS codes, commercial importance indicators)
    if 'societal_importance' in econ_util:
        importance_entries = econ_util['societal_importance']
        if isinstance(importance_entries, list):
            for entry in importance_entries:
                if isinstance(entry, dict) and 'value' in entry:
                    importance_value = entry['value']
                    if isinstance(importance_value, dict):
                        value = importance_value.get('value', '')
                        reference = importance_value.get('reference', '')
                        quality = importance_value.get('quality_status', 'unknown')
                        measurement_type = importance_value.get('measurement_type', '')
                        source = entry.get('source', 'Unknown')
                        if value:
                            data['societal_importance'].append({
                                'value': value,
                                'measurement_type': measurement_type,
                                'reference': reference,
                                'quality_status': quality,
                                'source': source
                            })

    # Extract commercial uses (to be implemented when data becomes available)
    # Extract fisheries data (to be implemented when data becomes available)
    # Extract aquaculture data (to be implemented when data becomes available)

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


def get_detection_monitoring_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get detection and monitoring data from AI-categorized JSON."""
    default_data = {
        "identification_methods": [],
        "survey_protocols": [],
        "edna_markers": [],
        "early_detection_indicators": [],
        "conflicts": {},
        "data_sources": []
    }

    data = default_data.copy()
    detection = get_category_data(species_name, 'detection_monitoring', universal_id=universal_id)

    if not detection:
        data["error"] = f"Species '{species_name}' not found in categorized cache"
        return data

    # Extract detection/monitoring data (to be implemented when data becomes available)
    # This will be populated as the AI categorizes relevant fields

    # Add data sources
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)
    if categorized_data:
        data['data_sources'] = categorized_data.get('sources', [])

    return data


# Legacy placeholder functions (kept for backwards compatibility)
def get_ecological_impact_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get ecological impact data - redirects to impacts_data."""
    return get_impacts_data(species_name, universal_id)


def get_risk_assessment_data(species_name: str, universal_id: Optional[str] = None) -> Dict[str, Any]:
    """Get risk assessment data - placeholder."""
    return {
        "placeholder": "No risk assessment data available from current APIs",
        "data_status": "placeholder_only",
        "data_sources": []
    }
