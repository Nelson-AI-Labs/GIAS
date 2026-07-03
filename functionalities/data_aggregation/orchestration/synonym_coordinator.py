#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
SynonymCoordinator Component
Orchestrates synonym iteration with stateful management for Haystack pipeline loops.
"""

from haystack import component
from typing import Dict, List, Set, Any, Optional
from core.cache_layer.raw_data_store import RawDataStore


@component
class SynonymCoordinator:
    """
    Coordinates synonym-aware species data collection.

    Maintains state across pipeline iterations:
    - synonym_list: Fixed list of names to query (no growth)
    - already_queried: Set of names already processed (normalized)
    - universal_id: Species identifier for data grouping
    - raw_store: RawDataStore instance
    - current_index: Current position in synonym_list
    """

    def __init__(self):
        """Initialize the synonym coordinator with empty state."""
        # State variables (persist across runs)
        self.synonym_list: List[str] = []
        self.already_queried: Set[str] = set()
        self.universal_id: Optional[str] = None
        self.raw_store: Optional[RawDataStore] = None
        self.current_index: int = 0
        self.iteration_count: int = 0
        self.initialized: bool = False
        # Optional callback(current, total, current_name) — set externally before pipeline.run()
        self.progress_callback = None

    @component.output_types(
        next_synonym=str,
        universal_id=str,
        is_complete=bool,
        iteration_number=int
    )
    def run(self,
            initial_synonyms: Optional[List[str]] = None,
            universal_id: Optional[str] = None,
            loop_trigger: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Coordinate synonym iteration.

        First call (initialization):
            - Receives initial_synonyms and universal_id
            - Initializes state
            - Returns first synonym to query

        Subsequent calls (iteration):
            - Triggered by loop_trigger from LoopController
            - Returns next synonym OR signals completion

        Args:
            initial_synonyms: List of synonym names from Mistral (first call only)
            universal_id: Species identifier (first call only)
            loop_trigger: Signal to continue iteration (subsequent calls)

        Returns:
            Dict with next_synonym, universal_id, raw_store, is_complete, iteration_number
        """

        # INITIALIZATION (first run)
        if initial_synonyms is not None and universal_id is not None and not self.initialized:
            self.synonym_list = initial_synonyms.copy()
            self.universal_id = universal_id
            self.raw_store = RawDataStore(universal_id=universal_id)
            self.current_index = 0
            self.already_queried = set()
            self.iteration_count = 0
            self.initialized = True
            print(f"✓ SynonymCoordinator initialized with {len(initial_synonyms)} synonyms for {universal_id}")
            for i, syn in enumerate(initial_synonyms, 1):
                print(f"  {i}. {syn}")

        # ITERATION LOGIC: Find next unqueried synonym
        while self.current_index < len(self.synonym_list):
            candidate = self.synonym_list[self.current_index]
            candidate_normalized = candidate.lower().strip()

            if candidate_normalized not in self.already_queried:
                # Found next synonym to query
                self.already_queried.add(candidate_normalized)
                self.iteration_count += 1

                # Check if this is the last synonym
                is_last_synonym = (len(self.already_queried) >= len(self.synonym_list))

                print(f"\n{'='*70}")
                print(f"SynonymCoordinator: Iteration {self.iteration_count}/{len(self.synonym_list)}")
                print(f"Querying: '{candidate}'")
                print(f"{'='*70}")

                if self.progress_callback:
                    self.progress_callback(
                        current=self.iteration_count,
                        total=len(self.synonym_list),
                        current_name=candidate
                    )

                return {
                    "next_synonym": candidate,
                    "universal_id": self.universal_id,
                    "is_complete": is_last_synonym,
                    "iteration_number": self.iteration_count
                }

            # Already queried, skip to next
            self.current_index += 1

        # COMPLETION: All synonyms processed
        print(f"\n{'='*70}")
        print(f"✓ SynonymCoordinator COMPLETE")
        print(f"Processed {len(self.already_queried)} unique synonym names")
        print(f"{'='*70}\n")

        return {
            "next_synonym": "",  # Empty string signals completion
            "universal_id": self.universal_id,
            "is_complete": True,
            "iteration_number": self.iteration_count
        }
