# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Shared standardization utilities for data normalization.

This module provides functions to standardize field values across different
database sources (WRiMS, GBIF, AquaNIS, EASIN, etc.) to ensure consistent
data representation throughout the application.
"""

from typing import Optional


def standardize_establishment_means(means: Optional[str]) -> str:
    """
    Standardize establishment means values across databases.

    Normalizes various terms for how a species became established in an area
    (alien, introduced, exotic, native, etc.) to a standard set of values.

    Args:
        means: Raw establishment means value from database

    Returns:
        Standardized value: 'alien', 'native', 'uncertain', or 'not_specified'
    """
    if not means:
        return 'not_specified'

    means_lower = means.lower().strip()

    # Mapping of common variants to standard values
    aliases = {
        'alien': ['alien', 'introduced', 'exotic', 'non-native', 'non_native', 'nonnative'],
        'native': ['native', 'indigenous', 'endemic', 'autochthonous'],
        'uncertain': ['uncertain', 'unknown', 'unclear', 'cryptogenic']
    }

    for standard, variants in aliases.items():
        if means_lower in variants:
            return standard

    return 'not_specified'


def standardize_invasiveness(invasiveness: Optional[str]) -> str:
    """
    Standardize invasiveness status values.

    Normalizes various terms describing a species' invasive status
    to a consistent set of values.

    Args:
        invasiveness: Raw invasiveness value from database

    Returns:
        Standardized value: 'invasive', 'not_invasive', 'of_concern',
                          'uncertain', or 'not_specified'
    """
    if not invasiveness:
        return 'not_specified'

    invasiveness_lower = invasiveness.lower().strip()

    if invasiveness_lower == 'invasive':
        return 'invasive'
    elif invasiveness_lower in ['not invasive', 'not_invasive', 'noninvasive', 'non-invasive']:
        return 'not_invasive'
    elif invasiveness_lower in ['of concern', 'of_concern', 'potentially invasive', 'potentially_invasive']:
        return 'of_concern'
    elif invasiveness_lower in ['uncertain', 'not specified', 'not_specified', 'unknown']:
        return 'uncertain'

    return 'not_specified'


def standardize_establishment_status(occurrence: Optional[str]) -> str:
    """
    Standardize establishment status (from WRiMS occurrence field).

    Normalizes terms describing whether a species is established,
    reported, or has uncertain status in a location.

    Args:
        occurrence: Raw occurrence/establishment status from database

    Returns:
        Standardized value: 'established', 'reported', 'sometimes_present',
                          'uncertain', or 'not_specified'
    """
    if not occurrence:
        return 'not_specified'

    occurrence_lower = occurrence.lower().strip()

    if occurrence_lower == 'established':
        return 'established'
    elif occurrence_lower == 'reported':
        return 'reported'
    elif occurrence_lower in ['sometimes present', 'sometimes_present', 'occasional']:
        return 'sometimes_present'
    elif occurrence_lower in ['uncertain', 'unknown']:
        return 'uncertain'

    return 'not_specified'


def standardize_iucn_category(category: Optional[str]) -> str:
    """
    Standardize IUCN Red List category codes.

    Ensures consistent representation of IUCN conservation status categories.

    Args:
        category: Raw IUCN category value

    Returns:
        Standardized IUCN category code or 'NE' (Not Evaluated) if not recognized
    """
    if not category:
        return 'NE'

    category_upper = category.upper().strip()

    # Standard IUCN categories
    valid_categories = {
        'EX': 'EX',   # Extinct
        'EW': 'EW',   # Extinct in the Wild
        'CR': 'CR',   # Critically Endangered
        'EN': 'EN',   # Endangered
        'VU': 'VU',   # Vulnerable
        'NT': 'NT',   # Near Threatened
        'LC': 'LC',   # Least Concern
        'DD': 'DD',   # Data Deficient
        'NE': 'NE',   # Not Evaluated
        # Handle full names
        'EXTINCT': 'EX',
        'EXTINCT IN THE WILD': 'EW',
        'CRITICALLY ENDANGERED': 'CR',
        'ENDANGERED': 'EN',
        'VULNERABLE': 'VU',
        'NEAR THREATENED': 'NT',
        'LEAST CONCERN': 'LC',
        'DATA DEFICIENT': 'DD',
        'NOT EVALUATED': 'NE'
    }

    return valid_categories.get(category_upper, 'NE')


def standardize_population_trend(trend: Optional[str]) -> str:
    """
    Standardize population trend values.

    Normalizes various terms describing population trends to a consistent set.

    Args:
        trend: Raw population trend value

    Returns:
        Standardized value: 'increasing', 'stable', 'decreasing', or 'unknown'
    """
    if not trend:
        return 'unknown'

    trend_lower = trend.lower().strip()

    if trend_lower in ['increasing', 'increase', 'growing']:
        return 'increasing'
    elif trend_lower in ['stable', 'constant', 'steady']:
        return 'stable'
    elif trend_lower in ['decreasing', 'decrease', 'declining', 'decline']:
        return 'decreasing'

    return 'unknown'
