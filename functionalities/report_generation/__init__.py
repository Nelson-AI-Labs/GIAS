# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Report Generation Pipeline (RGP) Components
===========================================

Haystack components for generating markdown reports from categorized species data.

Components:
- JSONLoaderComponent: Loads categorized JSON data
- CategoryFilterComponent: Filters to selected categories
- DataCleanerComponent: Strips metadata, deduplicates, detects contradictions
- NarrativeGeneratorComponent: Converts cleaned JSON to per-category narrative HTML
"""

from functionalities.report_generation.json_loader import JSONLoaderComponent
from functionalities.report_generation.category_filter import CategoryFilterComponent
from functionalities.report_generation.data_cleaner import DataCleanerComponent
from functionalities.report_generation.narrative_generator import NarrativeGeneratorComponent

__all__ = [
    'JSONLoaderComponent',
    'CategoryFilterComponent',
    'DataCleanerComponent',
    'NarrativeGeneratorComponent',
]
