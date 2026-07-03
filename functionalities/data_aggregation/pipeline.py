#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Database Integration Pipeline
A Haystack Pipeline for extracting species information from multiple databases.
"""

import os
import json
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

# Haystack imports
from haystack import component, Pipeline
from haystack.components.routers import ConditionalRouter
from haystack.dataclasses import ChatMessage

# Import API components and agents
from functionalities.data_aggregation.api.gbif import GBIFComponent, _get_gbif_species_match
from functionalities.data_aggregation.api.wrims import WRiMSComponent
from functionalities.data_aggregation.api.IUCN import IUCNComponent
from functionalities.data_aggregation.api.easin import EASINComponent
from functionalities.data_aggregation.api.aquanis import AquaNISComponent
from functionalities.data_aggregation.api.cabi_sparql import CABIComponent
from functionalities.data_aggregation.agents.species_analysis_agent import SpeciesAnalysisAgent
from functionalities.data_aggregation.orchestration.synonym_coordinator import SynonymCoordinator
from core.services.categorize_to_json import CategorizationComponent
from core.services.species_resolver import resolve_species
from core.utils.universal_identifier import generate_cache_id
from core.utils.species_name_utils import standardize_species_name
from core.cache_layer.raw_data_store import RawDataStore
from core.utils.config_loader import get_api_key

# Import Streamlit for caching (if available)
try:
    import streamlit as st
except ImportError:
    st = None


# Each database is a self-contained Haystack component that owns the full path for its
# source: API extraction, flattening/standardization through the universal SQL layer, and
# caching in SQLite. GBIFComponent and WRiMSComponent are the reference implementations;
# the remaining API components (IUCN, EASIN, AquaNIS, CABI) follow the same contract.

# ============================================================================
# REPORT GENERATOR
# ============================================================================

@component
class ReportGeneratorComponent:
    """
    Pipeline component that generates a human-readable report file.
    """
    
    def __init__(self, output_dir: str = None):
        """Initialize the report generator component.
        
        Args:
            output_dir: Directory to save reports (defaults to cache folder)
        """
        if output_dir is None:
            from core.utils.config_loader import get_project_root
            self.output_dir = str(get_project_root() / 'cache')
        else:
            self.output_dir = output_dir
    
    @component.output_types(report_path=str, success=bool)
    def run(self, summary: str, sources: List[str], species_name: str,
            query_metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Generate human-readable report file with SQL cache information.
        
        Args:
            summary: Species summary text
            sources: List of data sources
            species_name: Scientific name of the species
            query_metadata: Metadata about the SQL query
            
        Returns:
            Dict with report file path and success status
        """
        try:
            # Create filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_species = species_name.replace(' ', '_').replace('.', '')
            filename = f"{safe_species}_sql_database_report_{timestamp}.txt"
            report_path = os.path.join(self.output_dir, filename)
            
            # Create cache information section
            cache_info = ""
            if query_metadata:
                cache_info = f"""
CACHE INFORMATION:
- Query Timestamp: {query_metadata.get('query_timestamp', 'Unknown')}
- Total Sources: {query_metadata.get('total_sources', 0)}
- Successful Sources: {query_metadata.get('successful_sources', 0)}
- Cache Status: {query_metadata.get('cache_status', 'Unknown')}

DATA FRESHNESS:
{chr(10).join(f'- {source}: {timestamp}' for source, timestamp in query_metadata.get('data_freshness', {}).items())}

RECORD COUNTS:
{chr(10).join(f'- {source}: {count} records' for source, count in query_metadata.get('record_counts', {}).items())}
"""
            
            # Create report content
            report_content = f"""SPECIES DATABASE REPORT (SQL-CACHED)
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

SPECIES: {species_name}

DATA SOURCES CONSULTED:
{', '.join(f'- {source}' for source in sources)}
{cache_info}
{'='*80}
SPECIES SUMMARY
{'='*80}

{summary}

{'='*80}
REPORT METADATA
{'='*80}

Generation Time: {datetime.now().isoformat()}
Pipeline Version: 2.0 (SQL-based)
Sources Count: {len(sources)}
Cache Implementation: SQLite with structured data storage

---
Generated by GuardIAS Species Database Integration Pipeline (SQL Edition)
"""
            
            # Write report file
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(report_content)

            return {
                "report_path": report_path,
                "success": True
            }

        except Exception as e:
            return {
                "report_path": "",
                "success": False
            }

# ============================================================================
# PIPELINE SYNCHRONIZATION COMPONENT
# ============================================================================

@component
class APIJoiner:
    """
    Joiner component that waits for all API components to finish.
    Ensures categorization only runs after all raw data is fetched.
    """

    @component.output_types(species_name=str, ready=bool)
    def run(self, species_name: str,
            gbif_status: str,
            wrims_status: str,
            iucn_status: str,
            easin_status: str,
            aquanis_status: str,
            cabi_status: str) -> Dict[str, Any]:
        """
        Wait for all API components, then trigger categorization.

        Args:
            species_name: Scientific name of the species
            gbif_status: Status from GBIF component
            wrims_status: Status from WRiMS component
            iucn_status: Status from IUCN component
            easin_status: Status from EASIN component
            aquanis_status: Status from AquaNIS component
            cabi_status: Status from CABI component

        Returns:
            Dict with species_name and ready flag
        """
        print(f"✓ All API components finished for {species_name}")
        print(f"  GBIF: {gbif_status}, WRiMS: {wrims_status}, IUCN: {iucn_status}, EASIN: {easin_status}, AquaNIS: {aquanis_status}, CABI: {cabi_status}")
        return {"species_name": species_name, "ready": True}


# ============================================================================
# PARALLEL API EXECUTION COMPONENT
# ============================================================================

# Map each component's cache_status vocabulary to a frontend bar state.
# All 6 API components return exactly these three values.
_DB_STATUS_MAP = {
    "raw_saved": "found",
    "no_data": "no_data",
    "error": "fail",
}


@component
class ParallelAPIComponent:
    """
    Queries all 6 databases concurrently for one synonym.

    Replaces the 6 individually-wired API components + APIJoiner in the
    synonym-aware pipeline. Each child component's run() is reused unchanged
    and executed in its own thread (ThreadPoolExecutor). The fan-in / as_completed
    loop runs on the calling (pipeline) thread, so db_progress_callback fires there
    too — safe to update Streamlit widgets from it.

    Thread safety: each child writes to its own RawDataStore source subdirectory
    (one isolated file per species×source), so concurrent save_raw_data calls never
    collide. No lock required.
    """

    def __init__(self):
        """Instantiate one API component per source database, reusing their fetch/store logic."""
        # Reuse the existing component bodies — no fetch/store reimplementation.
        self._sources = [
            ("GBIF", GBIFComponent()),
            ("WRiMS", WRiMSComponent()),
            ("IUCN", IUCNComponent()),
            ("EASIN", EASINComponent()),
            ("AquaNIS", AquaNISComponent()),
            ("CABI", CABIComponent()),
        ]
        # Set externally before pipeline.run() (mirrors the legacy per-component pattern)
        self.raw_store = None
        # Optional callback(db_name, status, done, total) — fired as each DB returns
        self.db_progress_callback = None

    def _run_one(self, name: str, comp, species_name: str) -> str:
        """Run a single DB component, return its mapped bar status."""
        try:
            result = comp.run(species_name=species_name, raw_store=self.raw_store)
            cache_status = result.get("cache_status", "error")
        except Exception as e:
            print(f"Error in {name} parallel run: {str(e)}")
            cache_status = "error"
        return _DB_STATUS_MAP.get(cache_status, "fail")

    @component.output_types(species_name=str, ready=bool)
    def run(self, species_name: str) -> Dict[str, Any]:
        """
        Query all 6 databases concurrently for one synonym.

        Returns the APIJoiner contract (species_name + ready) so the downstream
        ConditionalRouter wiring is unchanged.
        """
        total = len(self._sources)
        done = 0
        statuses: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=total) as executor:
            future_to_name = {
                executor.submit(self._run_one, name, comp, species_name): name
                for name, comp in self._sources
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                status = future.result()
                statuses[name] = status
                done += 1
                if self.db_progress_callback:
                    self.db_progress_callback(name, status, done, total)

        print(f"✓ Parallel API query complete for '{species_name}': {statuses}")
        return {"species_name": species_name, "ready": True}


# ============================================================================
# PIPELINE CONSTRUCTION
# ============================================================================

def create_species_database_pipeline() -> Pipeline:
    """
    Create and configure the species database pipeline with AI categorization.

    Pipeline flow: Species → GBIF/WRiMS/IUCN Components (raw data) → AI Categorization → Categorized JSON

    Returns:
        Configured Pipeline object ready for execution
    """

    # Create pipeline
    pipeline = Pipeline()

    # Add API components - fetch and save raw data
    pipeline.add_component("gbif_component", GBIFComponent())
    pipeline.add_component("wrims_component", WRiMSComponent())
    pipeline.add_component("iucn_component", IUCNComponent())

    # Add joiner to synchronize API completion
    pipeline.add_component("api_joiner", APIJoiner())

    # Add AI categorization component
    pipeline.add_component("categorization", CategorizationComponent())

    # Connect pipeline for sequential execution:
    # API components (parallel) → Joiner (waits for all) → Categorization (sequential)
    pipeline.connect("gbif_component.cache_status", "api_joiner.gbif_status")
    pipeline.connect("wrims_component.cache_status", "api_joiner.wrims_status")
    pipeline.connect("iucn_component.cache_status", "api_joiner.iucn_status")
    pipeline.connect("api_joiner.species_name", "categorization.species_name")

    return pipeline

# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def run_species_database_pipeline(species_name: str) -> Dict[str, Any]:
    """
    Convenience function to run the species database pipeline with AI categorization.

    Args:
        species_name: Scientific name of the species

    Returns:
        Dictionary containing categorized data path and processing results
    """

    # Standardize species name and overwrite parameter - everything downstream uses standardized version
    raw_species_name = species_name
    species_name = standardize_species_name(species_name)

    print(f"Raw input: '{raw_species_name}' -> Standardized: '{species_name}'")

    # Cache the standardized name in Streamlit session state if available
    if st and hasattr(st, 'session_state'):
        st.session_state.standardized_species_name = species_name
        st.session_state.raw_species_input = raw_species_name
        print(f"Cached standardized species name: {species_name}")

    print(f"Starting species data pipeline for: {species_name}")

    # Create and run pipeline with standardized name
    pipeline = create_species_database_pipeline()

    result = pipeline.run({
        "gbif_component": {"species_name": species_name},
        "wrims_component": {"species_name": species_name},
        "iucn_component": {"species_name": species_name},
        "api_joiner": {"species_name": species_name}
    })

    # Extract categorization results
    categorized_path = None
    categorization_status = "error"

    if "categorization" in result:
        categorized_path = result["categorization"].get("categorized_path")
        categorization_status = result["categorization"].get("categorization_status", "error")

    # Add convenience information to result
    result["categorized_data_path"] = categorized_path
    result["categorization_status"] = categorization_status
    result["database_ready"] = categorization_status == "success"  # Legacy compatibility

    return result


# ============================================================================
# SYNONYM-AWARE PIPELINE (WITH HAYSTACK LOOP ARCHITECTURE)
# ============================================================================

def create_synonym_aware_pipeline() -> Pipeline:
    """
    Create synonym-aware species database pipeline with Haystack loop architecture.

    Pipeline supports:
    - Iterative querying of all synonym name variants
    - Genuinely parallel API execution: all 6 databases (GBIF, WRiMS, IUCN,
      EASIN, AquaNIS, CABI) queried concurrently per synonym via ParallelAPIComponent
    - Loop-based architecture using Haystack native features
    - Universal ID grouping for all variant data

    Returns:
        Configured Pipeline with loop connections
    """

    pipeline = Pipeline(max_runs_per_component=20)  # Safety limit for synonym iteration

    # Add orchestration components
    pipeline.add_component("synonym_coordinator", SynonymCoordinator())

    # Add the parallel API component (queries all 6 databases concurrently)
    pipeline.add_component("parallel_api", ParallelAPIComponent())

    # Add categorization
    pipeline.add_component("categorization", CategorizationComponent())

    # ========================================================================
    # FORWARD CONNECTIONS: SynonymCoordinator → ParallelAPIComponent
    # ========================================================================

    # Pass next_synonym to the parallel API component.
    # NOTE: raw_store is set directly on the component (see run function below) —
    # Haystack connections can't pass complex Python objects like RawDataStore.
    pipeline.connect("synonym_coordinator.next_synonym", "parallel_api.species_name")

    # ========================================================================
    # CONDITIONAL ROUTING: ConditionalRouter (loop back OR categorize)
    # ========================================================================

    # Add ConditionalRouter to decide: continue loop OR run categorization
    conditional_router = ConditionalRouter(
        routes=[
            {
                # Continue looping when not complete (and APIs are ready)
                "condition": "{{is_complete == False and ready == True}}",
                "output": "{{is_complete}}",
                "output_name": "continue_loop",
                "output_type": bool
            },
            {
                # Proceed to categorization when complete (and APIs are ready)
                "condition": "{{is_complete == True and ready == True}}",
                "output": "{{universal_id}}",
                "output_name": "categorize",
                "output_type": str
            }
        ]
    )
    pipeline.add_component("conditional_router", conditional_router)

    # SynonymCoordinator → ConditionalRouter
    pipeline.connect("synonym_coordinator.is_complete", "conditional_router.is_complete")
    pipeline.connect("synonym_coordinator.universal_id", "conditional_router.universal_id")

    # ParallelAPIComponent triggers the router after all 6 DBs complete
    # Router waits for ready=True before evaluating conditions
    pipeline.connect("parallel_api.ready", "conditional_router.ready")

    # ConditionalRouter → Loop back to SynonymCoordinator (only when is_complete=False)
    pipeline.connect("conditional_router.continue_loop", "synonym_coordinator.loop_trigger")

    # ConditionalRouter → Categorization (only when is_complete=True)
    pipeline.connect("conditional_router.categorize", "categorization.universal_id")

    return pipeline


def run_species_database_pipeline_with_synonyms(user_input: str, progress_callback=None, db_progress_callback=None, resolution_callback=None) -> Dict[str, Any]:
    """
    Run the synonym-aware species data collection pipeline.

    This is the main entry point for synonym-aware processing. It:
    1. Validates the species name with Mistral AI
    2. Gets synonyms from the validation
    3. Creates a universal ID for grouping all variant data
    4. Runs the Haystack loop pipeline to query all synonyms
    5. Categorizes all collected data into a single JSON

    Args:
        user_input: User's species name query (can be common name, misspelled, etc.)

    Returns:
        Dict containing:
            - universal_id: Species identifier
            - gbif_key: GBIF usage key
            - original_query: User's input
            - corrected_name: Validated scientific name
            - validation_result: Full Mistral validation response
            - categorized_path: Path to categorized JSON
            - categorization_status: "success" or "partial" or "error"
            - status: Overall pipeline status
    """

    print(f"\n{'='*70}")
    print(f"SYNONYM-AWARE PIPELINE (Haystack Architecture)")
    print(f"{'='*70}")
    print(f"User Input: '{user_input}'\n")

    try:
        # Step 1: Resolve species name and synonyms from taxonomic databases
        print("Step 1: Resolving species name and synonyms...")
        cache_id = generate_cache_id(user_input)
        resolution = resolve_species(user_input, universal_id=cache_id)
        corrected_name = resolution["corrected_name"]
        gbif_key = resolution["gbif_key"]
        synonym_list = resolution["synonym_list"]
        synonym_sources_failed = resolution.get("synonym_sources_failed", [])

        print(f"✓ Corrected name: '{corrected_name}' (confidence: {resolution['confidence']})")
        print(f"✓ GBIF Key: {gbif_key}")
        print(f"✓ Cache ID: {cache_id}")
        print(f"✓ Synonyms to query ({len(synonym_list)}):")
        for i, name in enumerate(synonym_list, 1):
            print(f"    {i}. {name}")

        # Report resolution result to the frontend (corrected name + variants)
        # before the synonym loop begins (None = no-op, safe for CLI usage).
        if resolution_callback:
            resolution_callback(corrected_name=corrected_name, synonym_list=synonym_list)

        # Step 2: Create and run synonym-aware pipeline
        print("\nStep 2: Running Haystack loop pipeline...")
        pipeline = create_synonym_aware_pipeline()

        # Create RawDataStore for this species
        raw_store = RawDataStore(universal_id=cache_id)

        # Set raw_store directly on the parallel API component
        # (Can't pass complex objects through Haystack pipeline connections)
        parallel_api = pipeline.get_component("parallel_api")
        parallel_api.raw_store = raw_store

        # Wire progress callbacks (None = no-op, safe for CLI usage):
        #   progress_callback     → per-synonym (coordinator)
        #   db_progress_callback  → per-database (parallel API component)
        pipeline.get_component("synonym_coordinator").progress_callback = progress_callback
        parallel_api.db_progress_callback = db_progress_callback

        # Initialize pipeline with synonym list and cache_id
        result = pipeline.run({
            "synonym_coordinator": {
                "initial_synonyms": synonym_list,
                "universal_id": cache_id  # Still using 'universal_id' key for backward compatibility
            }
        })

        # Extract results
        categorized_path = result.get("categorization", {}).get("categorized_path")
        categorization_status = result.get("categorization", {}).get("categorization_status")

        print(f"\n{'='*70}")
        print(f"PIPELINE COMPLETE")
        print(f"{'='*70}")
        print(f"Cache ID: {cache_id}")
        print(f"Categorized Data: {categorized_path}")
        print(f"Status: {categorization_status}")
        print(f"{'='*70}\n")

        return {
            "universal_id": cache_id,
            "gbif_key": gbif_key,
            "original_query": user_input,
            "corrected_name": corrected_name,
            "categorized_path": categorized_path,
            "categorization_status": categorization_status,
            "all_synonyms_searched": synonym_list,
            "synonym_sources_failed": synonym_sources_failed,
            "status": "success" if categorization_status == "success" else "partial"
        }

    except Exception as e:
        print(f"\n❌ Pipeline failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "universal_id": "",
            "gbif_key": 0,
            "original_query": user_input,
            "corrected_name": "",
            "categorized_path": "",
            "categorization_status": "error",
            "status": "error",
            "error_message": str(e)
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python database_connecting_pipeline.py <species_name>")
        sys.exit(1)

    species_name = sys.argv[1]
    print(f"Running species data pipeline for: {species_name}")

    try:
        result = run_species_database_pipeline(species_name)

        print("\n" + "="*60)
        print("PIPELINE EXECUTION COMPLETE")
        print("="*60)

        if result.get("categorization_status") == "success":
            print(f"✓ Categorized data ready at: {result.get('categorized_data_path')}")
        elif result.get("categorization_status") == "partial":
            print(f"⚠ Partial categorization at: {result.get('categorized_data_path')}")
        else:
            print("✗ Categorization failed")
            
        # Print component results
        if "gbif_component" in result:
            print(f"+ GBIF component executed")
        if "wrims_component" in result:
            print(f"+ WRiMS component executed")
            
    except Exception as e:
        print(f"Pipeline failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

