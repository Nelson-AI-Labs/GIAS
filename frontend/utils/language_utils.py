# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Language Utilities for GuardIAS Dashboard

Facade that re-exports the flag/language engine and the text parsers:
- flags.py: country/language flag generation + language-code resolution
- vernacular_utils.py: vernacular name processing
- distribution_utils.py: distribution/observation parsing
"""

# Re-export from flags (single source of truth for flags + language codes)
from frontend.utils.flags import (
    country_code_to_flag,
    get_country_flag,
    get_language_flag,
    normalize_language_name,
    is_supported_language,
)

# Re-export from vernacular_utils
from frontend.utils.vernacular_utils import (
    deduplicate_names,
    process_vernacular_names,
    format_vernacular_display,
    get_vernacular_summary,
)

# Re-export from distribution_utils
from frontend.utils.distribution_utils import (
    parse_country_distribution,
    parse_recent_observations,
)


__all__ = [
    # Flags + language codes
    'country_code_to_flag',
    'get_country_flag',
    'get_language_flag',
    'normalize_language_name',
    'is_supported_language',
    # Vernacular utilities
    'deduplicate_names',
    'process_vernacular_names',
    'format_vernacular_display',
    'get_vernacular_summary',
    # Distribution utilities
    'parse_country_distribution',
    'parse_recent_observations',
]
