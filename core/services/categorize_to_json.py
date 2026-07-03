#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Categorize to JSON Service
Reads raw JSON, uses AI to categorize fields, outputs categorized JSON file.
Simple. No SQL.
"""

import os
import json
from typing import Dict, List, Any
from datetime import datetime
from functionalities.data_aggregation.agents.data_categorization_agent import DataCategorizationAgent
from core.cache_layer.raw_data_store import RawDataStore
from core.cache_layer.categorized_data_helpers import save_categorized_data_by_id
from core.utils.cache_manager import get_cache_manager
from core.registries.topic_registry import StandardTopicRegistry


def _build_categorized_fields() -> Dict[str, Any]:
    """Build the categorized_fields skeleton from the registry (single source of truth)."""
    fields = {key: {} for key in StandardTopicRegistry.get_all_topic_keys()}
    fields["data_metadata"] = {}
    fields["unknown"] = {}
    return fields


class JSONCategorizationService:
    """
    Simple service: Raw JSON → AI Categorization → Categorized JSON
    Session-aware for multi-user cache isolation.
    """

    def __init__(self, session_id: str = None):
        """
        Initialize the JSON categorization service.

        Args:
            session_id: Session ID for cache isolation. If None, uses current session.
        """
        # Use cache_manager for all path resolution
        self.cache_manager = get_cache_manager(session_id)
        self.session_id = session_id

        # Initialize components
        self.agent = DataCategorizationAgent()
        # Defer RawDataStore creation so importing/instantiating this service never
        # creates directories: categorize_species() creates one when needed, and
        # categorize_by_universal_id() creates its own properly-configured instance.
        self.raw_store = None

        print(f"✓ Initialized JSON Categorization Service (Session: {self.cache_manager.session_id})")
        print(f"  Input: {self.cache_manager.raw_api_data_dir()}")
        print(f"  Output: {self.cache_manager.categorized_data_dir()}")

    def categorize_species(self, species_name: str) -> str:
        """
        Categorize all data for a species using Mistral AI and save to JSON file.

        Args:
            species_name: Species to categorize

        Returns:
            Path to output JSON file
        """
        print(f"\n📋 Categorizing: {species_name}")

        # Collect data from all sources
        categorized_data = {
            "species_name": species_name,
            "timestamp": datetime.now().isoformat(),
            "sources": [],
            "categorized_fields": _build_categorized_fields()
        }

        # Process each source - ALL fields go through Mistral AI
        for source in ['GBIF', 'WRiMS', 'IUCN', 'EASIN']:
            result = self._process_source(species_name, source)
            if result:
                categorized_data["sources"].append(source)

                # Merge AI-categorized fields - preserve all sources as arrays
                for category, fields in result.get('categorized', {}).items():
                    for field_name, field_data in fields.items():
                        # Initialize field as list if it doesn't exist
                        if field_name not in categorized_data["categorized_fields"][category]:
                            categorized_data["categorized_fields"][category][field_name] = []

                        # Append this source's data to the array
                        categorized_data["categorized_fields"][category][field_name].append(field_data)

        # Save to JSON file
        output_path = self._save_categorized_json(species_name, categorized_data)

        print(f"\n✓ Saved categorized data to: {output_path}")
        return output_path

    def categorize_by_universal_id(self, universal_id: str) -> str:
        """
        Categorize all raw data files for a universal species ID.

        This method is used by the synonym-aware pipeline to categorize
        data from all name variants (synonyms) collected for a species.
        All variant data is merged into a single categorized output file.

        Args:
            universal_id: Universal species identifier (format: {gbif_key}_{name})

        Returns:
            Path to output JSON file

        Examples:
            >>> service = JSONCategorizationService()
            >>> path = service.categorize_by_universal_id("2227300_procambarus_clarkii")
            >>> # Processes all files in cache/raw_api_data/2227300_procambarus_clarkii/
            >>> # Outputs to cache/categorized_data/2227300_procambarus_clarkii_categorized.json
        """
        print(f"\n📋 Categorizing all data for universal ID: {universal_id}")

        # Create RawDataStore configured for universal ID
        raw_store_with_id = RawDataStore(universal_id=universal_id)

        # Get all raw data files grouped by source
        files_by_source = raw_store_with_id.get_files_by_source_for_id(universal_id)

        print(f"  Found files:")
        for source, files in files_by_source.items():
            print(f"    {source}: {len(files)} files")

        # Initialize categorized data structure
        categorized_data = {
            "universal_id": universal_id,
            "timestamp": datetime.now().isoformat(),
            "sources": [],
            "categorized_fields": _build_categorized_fields()
        }

        # Dynamically discover sources
        available_sources = raw_store_with_id.get_available_sources_for_id(universal_id)

        if not available_sources:
            print(f"⚠️  No data sources found for {universal_id}")
            # Still create empty output file for consistency
            empty_output = {
                "universal_id": universal_id,
                "sources": [],
                "categorized_data": {},
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "status": "no_data"
                }
            }
            categorized_dir = self.cache_manager.categorized_data_dir()
            output_path = os.path.join(categorized_dir, f"{universal_id}_categorized.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(empty_output, f, indent=2, ensure_ascii=False)
            return {"categorized_path": output_path, "categorization_status": "no_data"}

        # Process each source
        for source in available_sources:
            files = files_by_source.get(source, [])

            if not files:
                print(f"  {source}... no data")
                continue

            print(f"  {source}... processing {len(files)} file(s)...", end=" ")

            try:
                # Load and combine all data from this source
                combined_source_data = {}
                query_names_used = []  # Track which synonym names were queried for this source

                for filepath in files:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        envelope = json.load(f)
                        file_data = envelope.get('data', {})

                        # Capture the query name from the envelope metadata
                        query_name = envelope.get('metadata', {}).get('species_name')
                        if query_name and query_name not in query_names_used:
                            query_names_used.append(query_name)

                        # Merge data (this is a simple merge, more sophisticated merging could be added)
                        for key, value in file_data.items():
                            if key not in combined_source_data:
                                combined_source_data[key] = value
                            else:
                                # If key already exists, handle merging
                                # For lists, extend; for others, keep first
                                if isinstance(combined_source_data[key], list) and isinstance(value, list):
                                    combined_source_data[key].extend(value)
                                # For other types, keep the first value (could be enhanced)

                # Send combined data to AI for categorization
                ai_results = self.agent.categorize_fields_by_source(combined_source_data, source)

                # Organize results by category
                for result in ai_results:
                    category = result.get('ai_suggested_category', 'unknown')
                    field_name = result.get('field_name', 'unnamed_field')

                    if category not in categorized_data["categorized_fields"]:
                        category = 'unknown'

                    # Initialize field as list if it doesn't exist
                    if field_name not in categorized_data["categorized_fields"][category]:
                        categorized_data["categorized_fields"][category][field_name] = []

                    # Build field entry preserving all metadata from categorization agent
                    field_entry = {
                        'value': result.get('field_value'),
                        'data_type': result.get('data_type', 'unknown'),
                        'source': source,
                        'query_names': query_names_used  # Which synonym names were queried for this source
                    }

                    # Add categorization_method if present
                    if 'categorization_method' in result:
                        field_entry['categorization_method'] = result['categorization_method']

                    # Only add ai_reasoning if it was actually provided (AI was used)
                    if 'ai_reasoning' in result:
                        field_entry['ai_reasoning'] = result['ai_reasoning']

                    # Add original_field tracking if present (for typed arrays)
                    if 'original_field' in result:
                        field_entry['original_field'] = result['original_field']

                    # Add discriminator_type if present (for typed arrays)
                    if 'discriminator_type' in result:
                        field_entry['discriminator_type'] = result['discriminator_type']

                    # Add note if present (for special handling)
                    if 'note' in result:
                        field_entry['note'] = result['note']

                    # Append this source's data
                    categorized_data["categorized_fields"][category][field_name].append(field_entry)

                # Post-processing: Aggregate taxonomy fields
                temp_categorized = {category: {} for category in categorized_data["categorized_fields"].keys()}
                for category, fields in categorized_data["categorized_fields"].items():
                    for field_name, field_list in fields.items():
                        if field_list and field_list[-1]['source'] == source:
                            temp_categorized[category][field_name] = field_list[-1]

                self._aggregate_taxonomy_fields(temp_categorized, source)

                categorized_data["sources"].append(source)
                print("done")

            except Exception as e:
                print(f"error: {str(e)}")
                # Continue with other sources even if one fails

        # Save to folder structure using new helper function
        from pathlib import Path
        categorized_dir = self.cache_manager.categorized_data_dir()
        success = save_categorized_data_by_id(universal_id, categorized_data, categorized_dir)

        if success:
            # Run geo-normalization on free-text distribution fields
            from core.services.geo_normalizer import GeoNormalizationService
            GeoNormalizationService().normalize_distribution(universal_id)

            # Return path to species folder for consistency
            species_folder = categorized_dir / universal_id.replace('/', '_')
            print(f"\n✓ Saved categorized data to: {species_folder}")
            return str(species_folder)
        else:
            print(f"\n❌ Failed to save categorized data")
            return ""

    def _process_source(self, species_name: str, source: str) -> Dict[str, Any]:
        """Process one data source - send ALL fields through Mistral AI."""
        print(f"  {source}...", end=" ")

        # Initialize raw_store if needed (for legacy categorize_species method)
        if self.raw_store is None:
            self.raw_store = RawDataStore()

        # Load raw data
        raw_data = self.raw_store.load_raw_data(species_name, source)
        if not raw_data:
            print("no data")
            return None

        # Organize results by AI-suggested category
        categorized = _build_categorized_fields()

        try:
            # Send ALL fields to Mistral for categorization
            print(f"categorizing {len(raw_data)} fields with AI...", end=" ")
            ai_results = self.agent.categorize_fields_by_source(raw_data, source)

            for result in ai_results:
                category = result.get('ai_suggested_category', 'unknown')
                field_name = result.get('field_name', 'unnamed_field')

                # If category is not recognized, put in unknown
                if category not in categorized:
                    category = 'unknown'

                # Store field with AI metadata
                categorized[category][field_name] = {
                    'value': result.get('field_value'),
                    'data_type': result.get('data_type', 'unknown'),
                    'ai_reasoning': result.get('ai_reasoning', 'AI categorization failed'),
                    'source': source
                }

            # Post-processing: Aggregate individual taxonomic rank fields into a taxonomy object
            self._aggregate_taxonomy_fields(categorized, source)

            print(f"done")

        except Exception as e:
            # AI categorization failed - put all fields in "unknown" category
            print(f"AI failed, saving as unknown...", end=" ")

            for field_name, field_value in raw_data.items():
                categorized['unknown'][field_name] = {
                    'value': field_value,
                    'data_type': type(field_value).__name__,
                    'ai_reasoning': f'AI categorization failed: {str(e)}',
                    'source': source
                }

            print(f"done (with errors)")

        return {
            'categorized': categorized,
            'uncategorized': {}  # Everything went through AI or to unknown
        }

    def _aggregate_taxonomy_fields(self, categorized: Dict[str, Any], source: str) -> None:
        """
        Aggregate individual taxonomic rank fields into a 'taxonomy' object.

        This handles sources like WRiMS that provide kingdom, phylum, class, order,
        family, genus as separate fields instead of a nested taxonomy object.

        Args:
            categorized: The categorized data dictionary to modify in-place
            source: The data source name
        """
        # Check if we have individual taxonomic rank fields in taxonomic_identity
        taxonomy_ranks = ['kingdom', 'phylum', 'class', 'order', 'family', 'genus']
        taxonomic_identity = categorized.get('taxonomic_identity', {})

        # Collect individual taxonomy fields
        individual_fields = {}
        fields_to_remove = []

        for rank in taxonomy_ranks:
            if rank in taxonomic_identity:
                # Store the value for this rank
                individual_fields[rank] = taxonomic_identity[rank]['value']
                fields_to_remove.append(rank)

        # If we found individual fields, create a taxonomy object
        if individual_fields:
            # Only create if we don't already have a taxonomy object from this source
            # (to avoid duplicating data that was already properly structured)
            has_taxonomy_object = 'taxonomy' in taxonomic_identity

            if not has_taxonomy_object:
                # Create aggregated taxonomy object
                categorized['taxonomic_identity']['taxonomy'] = {
                    'value': individual_fields,
                    'data_type': 'dict',
                    'ai_reasoning': f'Aggregated from individual taxonomic rank fields ({", ".join(individual_fields.keys())})',
                    'source': source
                }

                # Remove the individual fields since they're now in the taxonomy object
                for field in fields_to_remove:
                    del categorized['taxonomic_identity'][field]

                print(f"aggregated {len(individual_fields)} taxonomy fields...", end=" ")

    def _map_field_to_category(self, field_name: str) -> str:
        """Simple mapping of known fields to categories."""
        taxonomy_fields = {'species_name', 'taxonomy', 'kingdom', 'phylum', 'class',
                          'order', 'family', 'genus', 'authority', 'taxonomic_rank',
                          'taxonomic_status', 'synonyms', 'vernacular_names', 'children_taxa'}

        distribution_fields = {'distribution_records', 'occurrence_sample', 'establishment_info'}

        environment_fields = {'habitat', 'habitats_list', 'ecological_zone',
                             'salinity_tolerance', 'temperature_range', 'depth_range',
                             'environmental_tolerances', 'life_history_traits'}

        conservation_fields = {'iucn_status', 'population_trend', 'assessment_date',
                              'threats', 'conservation_measures', 'conservation_status',
                              'conservation_records'}

        metadata_fields = {'metadata', 'gbif_key', 'aphia_id', 'iucn_taxon_id',
                          'worms_url', 'gbif_url', 'iucn_url', 'data_source',
                          'found_in_worms', 'match_type', 'data_metadata'}

        if field_name in taxonomy_fields:
            return 'taxonomic_identity'
        elif field_name in distribution_fields:
            return 'distribution'
        elif field_name in environment_fields:
            return 'environmental_tolerances'
        elif field_name in conservation_fields:
            return 'conservation'
        elif field_name in metadata_fields:
            return 'data_metadata'
        else:
            return 'data_metadata'  # default

    def _save_categorized_json(self, species_name: str, data: Dict[str, Any]) -> str:
        """Save categorized data to JSON file."""
        # Sanitize species name for filename
        safe_name = species_name.replace(' ', '_').replace('.', '')
        filename = f"{safe_name}_categorized.json"
        categorized_dir = self.cache_manager.categorized_data_dir()
        filepath = os.path.join(categorized_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return filepath


# ============================================================================
# HAYSTACK PIPELINE COMPONENT
# ============================================================================

from haystack import component

@component
class CategorizationComponent:
    """
    Pipeline component that runs AI categorization on raw API data.
    Integrates with the DCP pipeline to automatically categorize species data.
    Session-aware for multi-user cache isolation.
    """

    def __init__(self, session_id: str = None):
        """
        Initialize categorization component.

        Args:
            session_id: Session ID for cache isolation. If None, uses current session.
        """
        self.service = JSONCategorizationService(session_id)

    @component.output_types(
        categorized_path=str,
        categorization_status=str,
        species_name=str
    )
    def run(self, species_name: str = None, universal_id: str = None) -> Dict[str, Any]:
        """
        Categorize all raw API data for a species using Mistral AI.

        Args:
            species_name: Scientific name of the species (for backward compatibility)
            universal_id: Universal species ID for synonym-aware categorization (preferred)

        Returns:
            Dict with path to categorized JSON and status
        """
        try:
            # Prefer universal_id if provided (synonym-aware pipeline)
            if universal_id:
                print(f"\n🤖 Starting AI categorization for universal_id: {universal_id}")
                output_path = self.service.categorize_by_universal_id(universal_id)
                identifier = universal_id
            elif species_name:
                print(f"\n🤖 Starting AI categorization for: {species_name}")
                output_path = self.service.categorize_species(species_name)
                identifier = species_name
            else:
                raise ValueError("Either species_name or universal_id must be provided")

            if output_path and os.path.exists(output_path):
                print(f"✓ Categorization complete: {output_path}")
                return {
                    "categorized_path": output_path,
                    "categorization_status": "success",
                    "species_name": identifier
                }
            else:
                print(f"⚠️ Categorization completed with warnings")
                return {
                    "categorized_path": output_path if output_path else "",
                    "categorization_status": "partial",
                    "species_name": identifier
                }

        except Exception as e:
            print(f"❌ Categorization failed: {str(e)}")
            return {
                "categorized_path": "",
                "categorization_status": "error",
                "species_name": identifier if 'identifier' in locals() else ""
            }


def main():
    """
    Main entry point - always categorize everything in raw_api_data.

    ⚠️  DEPRECATED: This script uses the legacy directory structure ⚠️

    This main() function is designed for the old flat cache structure:
        cache/{session_id}/raw_api_data/GBIF/{species}.json
        cache/{session_id}/raw_api_data/WRiMS/{species}.json

    NEW APPROACH:
    Use the database_connecting_pipeline.py with synonym-aware capabilities:
        cache/{session_id}/raw_api_data/{universal_id}/GBIF/{species}.json
        cache/{session_id}/raw_api_data/{universal_id}/WRiMS/{species}.json

    This function is kept for backwards compatibility with old cache data.
    """
    print("\n" + "="*70)
    print("⚠️  WARNING: Using legacy categorization script")
    print("="*70)
    print("This script uses the OLD directory structure.")
    print("For new data, use: pipelines/database_connecting_pipeline.py (run_species_database_pipeline_with_synonyms)")
    print("="*70 + "\n")

    service = JSONCategorizationService()

    # Find all species in raw_api_data
    raw_data_dir = service.cache_manager.raw_api_data_dir()
    species_set = set()

    for source in ['GBIF', 'WRiMS', 'IUCN']:
        source_dir = os.path.join(raw_data_dir, source)
        if os.path.exists(source_dir):
            for filename in os.listdir(source_dir):
                if filename.endswith('.json'):
                    species_name = filename.replace('.json', '').replace('_', ' ')
                    species_set.add(species_name)

    if not species_set:
        print("❌ No species found in raw_api_data/")
        print("   Fetch species data first through the app")
        return

    # Categorize all found species
    for species in species_set:
        output_path = service.categorize_species(species)
        print(f"📄 Output: {output_path}")

    print(f"\n✓ Done! Categorized {len(species_set)} species")
    print(f"📂 View results in: {service.cache_manager.categorized_data_dir()}")


if __name__ == "__main__":
    main()
