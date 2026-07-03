#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Raw Data Store Module
Handles saving and loading raw structured API responses as JSON files.
Preserves original API data structure before flattening and SQL processing.
"""

import json
import os
import glob
from datetime import datetime
from typing import Dict, Any, Optional, List


class RawDataStore:
    """
    Manages storage of raw API responses as JSON files.
    Saves structured dictionaries with metadata envelope.
    """

    def __init__(self, cache_dir: Optional[str] = None, universal_id: Optional[str] = None, session_id: Optional[str] = None):
        """
        Initialize the raw data store.

        Args:
            cache_dir: Base cache directory. Defaults to session-aware cache/{session_id}/raw_api_data/
            universal_id: Optional universal species identifier (format: {gbif_key}_{name}).
                         If provided, files will be organized in universal_id subdirectories.
            session_id: Optional session ID for multi-user cache isolation.
                       If None, uses current session from Streamlit context.
        """
        if cache_dir is None:
            # Use session-aware cache directory
            from core.utils.cache_manager import get_raw_api_data_dir
            cache_dir = str(get_raw_api_data_dir())

        self.cache_dir = os.path.abspath(cache_dir)
        self.universal_id = universal_id
        self.session_id = session_id

        # Create base cache directory if it doesn't exist
        os.makedirs(self.cache_dir, exist_ok=True)

    def _sanitize_species_name(self, species_name: str) -> str:
        """
        Sanitize species name for use in filenames.

        Args:
            species_name: Original species name

        Returns:
            Sanitized species name with spaces replaced by underscores
        """
        # Replace spaces with underscores
        sanitized = species_name.replace(' ', '_')

        # Remove or replace other problematic characters for filenames
        # Keep alphanumeric, underscores, hyphens, and periods
        sanitized = ''.join(c for c in sanitized if c.isalnum() or c in ('_', '-', '.'))

        return sanitized

    def _get_file_path(self, species_name: str, source: str) -> str:
        """
        Build full file path for a species and source.

        Supports two directory structures:
        - With universal_id: cache/raw_api_data/{universal_id}/{source}/{species_name}.json
        - Without universal_id: {cache_dir}/{source}/{species_name}.json (fallback when universal_id is not provided)

        Args:
            species_name: Species name (will be sanitized)
            source: Data source (e.g., 'GBIF', 'WRiMS', 'IUCN')

        Returns:
            Full path to JSON file
        """
        sanitized_name = self._sanitize_species_name(species_name)

        if self.universal_id:
            # New structure: cache/raw_api_data/{universal_id}/{source}/{species_name}.json
            species_dir = os.path.join(self.cache_dir, self.universal_id)
            os.makedirs(species_dir, exist_ok=True)
            source_dir = os.path.join(species_dir, source)
        else:
            # Fallback: when universal_id is not provided, files are grouped by source only
            source_dir = os.path.join(self.cache_dir, source)

        os.makedirs(source_dir, exist_ok=True)
        file_path = os.path.join(source_dir, f"{sanitized_name}.json")
        return file_path

    def save_raw_data(self, species_name: str, source: str, data: Dict[str, Any]) -> None:
        """
        Save structured API data to JSON file with metadata envelope.

        Args:
            species_name: Scientific name of the species
            source: Data source name (e.g., 'GBIF', 'WRiMS', 'IUCN')
            data: Structured data dictionary to save

        Raises:
            Exception: On any error (JSON serialization, file write, permissions)
        """
        try:
            # Build file path (directory creation handled by _get_file_path)
            file_path = self._get_file_path(species_name, source)

            # Create metadata envelope
            envelope = {
                "metadata": {
                    "timestamp": datetime.now().isoformat(),
                    "source": source,
                    "species_name": species_name,
                    "universal_id": self.universal_id  # Can be None when universal_id was not provided at init time
                },
                "data": data
            }

            # Write to file (overwrite if exists)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(envelope, f, indent=2, ensure_ascii=False)


        except Exception as e:
            # Re-raise exception with context
            raise Exception(f"Failed to save raw data for '{species_name}' from {source}: {str(e)}") from e

    def load_raw_data(self, species_name: str, source: str) -> Optional[Dict[str, Any]]:
        """
        Load structured API data from JSON file.

        Args:
            species_name: Scientific name of the species
            source: Data source name (e.g., 'GBIF', 'WRiMS', 'IUCN')

        Returns:
            Data portion (unwrapped from metadata envelope), or None if file doesn't exist

        Raises:
            Exception: On JSON parsing errors or read errors
        """
        try:
            file_path = self._get_file_path(species_name, source)

            # Return None if file doesn't exist
            if not os.path.exists(file_path):
                return None

            # Read and parse JSON
            with open(file_path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)

            # Extract and return data portion only
            data = envelope.get('data')
            return data

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse JSON for '{species_name}' from {source}: {str(e)}") from e
        except Exception as e:
            raise Exception(f"Failed to load raw data for '{species_name}' from {source}: {str(e)}") from e

    def delete_raw_data(self, species_name: str, source: str) -> None:
        """
        Delete cached raw data file.

        Args:
            species_name: Scientific name of the species
            source: Data source name (e.g., 'GBIF', 'WRiMS', 'IUCN')

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: On deletion errors
        """
        try:
            file_path = self._get_file_path(species_name, source)

            # Raise exception if file doesn't exist
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"No cached data found for '{species_name}' from {source}")

            # Delete file
            os.remove(file_path)

        except FileNotFoundError:
            raise
        except Exception as e:
            raise Exception(f"Failed to delete raw data for '{species_name}' from {source}: {str(e)}") from e

    def get_available_sources_for_id(self, universal_id: str) -> List[str]:
        """
        Dynamically discover all available data sources for a universal ID.

        Scans the subdirectories in cache/raw_api_data/{universal_id}/ and returns
        all folder names as available sources. This enables automatic discovery of
        new data sources without requiring code changes.

        Args:
            universal_id: Universal species identifier (format: {gbif_key}_{name})

        Returns:
            List of source names (e.g., ['AquaNIS', 'EASIN', 'GBIF', 'IUCN', 'WRiMS'])
            Returns empty list if universal_id directory doesn't exist.

        Examples:
            >>> store = RawDataStore()
            >>> sources = store.get_available_sources_for_id("2227300_procambarus_clarkii")
            >>> # Returns: ['AquaNIS', 'EASIN', 'GBIF', 'IUCN', 'WRiMS']
        """
        species_dir = os.path.join(self.cache_dir, universal_id)

        if not os.path.exists(species_dir):
            return []

        available_sources = []
        try:
            for item in os.listdir(species_dir):
                item_path = os.path.join(species_dir, item)
                if os.path.isdir(item_path):
                    available_sources.append(item)
        except OSError as e:
            return []

        available_sources.sort()  # Alphabetical order for consistency
        return available_sources

    def get_all_files_for_id(self, universal_id: str) -> List[str]:
        """
        Get all raw data files for a universal species ID.

        This retrieves all JSON files across all sources (GBIF, WRiMS, IUCN)
        for a given universal species identifier. Useful for categorization
        where all synonym variant data needs to be processed together.

        Args:
            universal_id: Universal species identifier (format: {gbif_key}_{name})

        Returns:
            List of absolute file paths to all JSON files for this species.
            Returns empty list if directory doesn't exist.

        Examples:
            >>> store = RawDataStore()
            >>> files = store.get_all_files_for_id("2227300_procambarus_clarkii")
            >>> # Returns: [
            >>>   ".../2227300_procambarus_clarkii/GBIF/Procambarus_clarkii.json",
            >>>   ".../2227300_procambarus_clarkii/GBIF/Cambarus_clarkii.json",
            >>>   ".../2227300_procambarus_clarkii/WRiMS/Procambarus_clarkii.json",
            >>>   ...
            >>> ]
        """
        species_dir = os.path.join(self.cache_dir, universal_id)

        if not os.path.exists(species_dir):
            return []

        files = []
        # Dynamically discover all available sources
        available_sources = self.get_available_sources_for_id(universal_id)

        for source in available_sources:
            source_dir = os.path.join(species_dir, source)
            if os.path.exists(source_dir):
                # Get all JSON files in this source directory
                source_files = glob.glob(os.path.join(source_dir, "*.json"))
                files.extend(source_files)

        return files

    def get_files_by_source_for_id(self, universal_id: str) -> Dict[str, List[str]]:
        """
        Get all raw data files for a universal ID, grouped by source.

        Args:
            universal_id: Universal species identifier

        Returns:
            Dictionary mapping source names to lists of file paths.
            Example: {"GBIF": ["file1.json", "file2.json"], "WRiMS": ["file3.json"]}
        """
        species_dir = os.path.join(self.cache_dir, universal_id)

        if not os.path.exists(species_dir):
            return {}  # Return empty dict instead of hardcoded keys

        # Dynamically discover all available sources
        available_sources = self.get_available_sources_for_id(universal_id)
        files_by_source = {}

        for source in available_sources:
            source_dir = os.path.join(species_dir, source)
            if os.path.exists(source_dir):
                source_files = glob.glob(os.path.join(source_dir, "*.json"))
                if source_files:  # Only add if files exist
                    files_by_source[source] = source_files

        return files_by_source


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    """Test the RawDataStore functionality."""

    print("=== Testing RawDataStore ===\n")

    # Initialize store
    store = RawDataStore()

    # Test data
    test_species = "Procambarus clarkii"
    test_source = "TEST"
    test_data = {
        "species_name": "Procambarus clarkii",
        "taxonomy": {
            "kingdom": "Animalia",
            "phylum": "Arthropoda",
            "class": "Malacostraca"
        },
        "habitat": "Freshwater",
        "test_field": "This is a test"
    }

    # Test 1: Save data
    print("Test 1: Saving data...")
    try:
        store.save_raw_data(test_species, test_source, test_data)
        print("✓ Save successful\n")
    except Exception as e:
        print(f"✗ Save failed: {e}\n")

    # Test 2: Load data
    print("Test 2: Loading data...")
    try:
        loaded_data = store.load_raw_data(test_species, test_source)
        if loaded_data == test_data:
            print("✓ Load successful, data matches\n")
        else:
            print("✗ Load successful but data doesn't match\n")
    except Exception as e:
        print(f"✗ Load failed: {e}\n")

    # Test 3: Load non-existent data
    print("Test 3: Loading non-existent data...")
    try:
        result = store.load_raw_data("Nonexistent species", test_source)
        if result is None:
            print("✓ Correctly returned None for non-existent data\n")
        else:
            print("✗ Should have returned None\n")
    except Exception as e:
        print(f"✗ Unexpected exception: {e}\n")

    # Test 4: Delete data
    print("Test 4: Deleting data...")
    try:
        store.delete_raw_data(test_species, test_source)
        print("✓ Delete successful\n")
    except Exception as e:
        print(f"✗ Delete failed: {e}\n")

    # Test 5: Delete non-existent data
    print("Test 5: Deleting non-existent data...")
    try:
        store.delete_raw_data(test_species, test_source)
        print("✗ Should have raised FileNotFoundError\n")
    except FileNotFoundError:
        print("✓ Correctly raised FileNotFoundError\n")
    except Exception as e:
        print(f"✗ Unexpected exception: {e}\n")

    print("=== Tests Complete ===")
