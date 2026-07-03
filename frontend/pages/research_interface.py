# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Research Interface Components
Handles the research mode UI for finding and reviewing additional sources.

This module is now a facade that re-exports from the modular research/ package.
All implementations have been moved to frontend/pages/research/ for better organization:
- research_state.py: State initialization and migration
- topic_selection.py: Topic selection UI components
- source_discovery.py: Static discovery list and find-more pagination
- source_extraction.py: Per-study analyze/extract/merge machinery
- extraction_process.py: Research execution and extraction
- merge_results.py: Merge interface and results display
"""

# Re-export main entry point for backward compatibility
from frontend.pages.research.research_interface import show_research_interface

# Re-export constants for backward compatibility
from frontend.pages.research.research_state import (
    TOPIC_DESCRIPTIONS,
    TOPIC_TO_DASHBOARD_CARD,
    ANCHOR_TOPICS,
    initialize_research_state_with_dcp_sources,
)

__all__ = [
    'show_research_interface',
    'TOPIC_DESCRIPTIONS',
    'TOPIC_TO_DASHBOARD_CARD',
    'ANCHOR_TOPICS',
    'initialize_research_state_with_dcp_sources',
]
