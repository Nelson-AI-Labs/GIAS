# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Research Interface Module
Modular components for the research mode UI.

This package provides the research interface for finding and reviewing additional sources.

Modules:
- research_state: State initialization and migration
- topic_selection: Topic selection UI components
- source_discovery: Static discovery list and find-more pagination
- source_extraction: Per-study analyze/extract/merge machinery
- extraction_process: Research execution and extraction
- research_interface: Main entry point
"""

from frontend.pages.research.research_interface import show_research_interface
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
