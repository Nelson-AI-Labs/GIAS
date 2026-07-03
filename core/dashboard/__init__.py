# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Dashboard Package
Provides tools for data loading, species information retrieval, and dashboard utilities.

This package is organized into focused modules:
- data_loaders: JSON loading and cache utilities
- species_data: Core data retrieval functions for species information (implementations)
- image_fetchers: Image retrieval from Wikipedia, GBIF, etc.
- conflict_detection: Data conflict detection and display utilities
- dashboard_tools: Main facade (imports from above modules for backward compatibility)
"""

# Re-export commonly used functions for convenience
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

# Re-export species data functions for convenience
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
)
