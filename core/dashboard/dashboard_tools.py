#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Dashboard Tools
JSON-based functions that return structured data for dashboard cards.
Reads from AI-categorized data in cache/categorized_data/

This module is the main entry point for dashboard data functions.
For better organization, core functions have been split into submodules:
- data_loaders.py: JSON loading and cache utilities
- image_fetchers.py: Image retrieval functions
- conflict_detection.py: Data conflict detection utilities
- species_data.py: Species data retrieval functions (actual implementations)

All functions are re-exported here for backward compatibility.
"""

from typing import Dict, List, Any, Optional

# Import from submodules - these are re-exported for backward compatibility
from core.dashboard.data_loaders import (
    load_categorized_species_json,
    list_cached_species,
    get_category_data,
    extract_multi_source_field,
)

from core.dashboard.image_fetchers import (
    get_species_image_url,
    fetch_wikipedia_image,
)

from core.dashboard.conflict_detection import (
    detect_conflicts,
    check_data_categories,
    aggregate_distribution_by_status,
    prepare_conflict_display_data,
)

# Species data accessors
from core.dashboard.species_data import (
    get_taxonomic_data,
    get_distribution_data,
    get_environmental_data,
    get_morphological_data,
    get_physiological_data,
    get_biological_data,
    get_conservation_data,
    get_available_databases,
    get_database_url_from_raw_data,
    get_all_database_links_with_species,
    get_species_metadata,
    get_species_interactions_data,
    get_impacts_data,
    get_management_data,
    get_economic_utilisation_data,
    get_detection_monitoring_data,
    get_ecological_impact_data,
    get_risk_assessment_data,
)

__all__ = [
    # Data loaders
    'load_categorized_species_json',
    'list_cached_species',
    'get_category_data',
    'extract_multi_source_field',
    # Image fetchers
    'get_species_image_url',
    'fetch_wikipedia_image',
    # Conflict detection
    'detect_conflicts',
    'check_data_categories',
    'aggregate_distribution_by_status',
    'prepare_conflict_display_data',
    # Species data functions
    'get_taxonomic_data',
    'get_distribution_data',
    'get_environmental_data',
    'get_morphological_data',
    'get_physiological_data',
    'get_biological_data',
    'get_conservation_data',
    'get_available_databases',
    'get_database_url_from_raw_data',
    'get_all_database_links_with_species',
    'get_species_metadata',
    'get_species_interactions_data',
    'get_impacts_data',
    'get_management_data',
    'get_economic_utilisation_data',
    'get_detection_monitoring_data',
    'get_ecological_impact_data',
    'get_risk_assessment_data',
]
