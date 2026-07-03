# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Distribution Utilities
Parsing functions for distribution and observation data.
"""

from typing import List
from frontend.utils.flags import get_country_flag


def parse_country_distribution(distribution_text: str) -> List[tuple[str, str, int]]:
    """
    Parse GBIF distribution text to extract country data with counts.

    Args:
        distribution_text: Text like "Total occurrences: 1,234 records across 5 countries\n  - Norway: 890 records\n  - Sweden: 344 records"

    Returns:
        List of tuples: (flag, country_name, count)
    """
    if not distribution_text or distribution_text == "Unknown":
        return []

    countries_data = []
    lines = distribution_text.split('\n')

    for line in lines:
        line = line.strip()
        # Look for pattern: "  - Country: X records"
        if line.startswith('- ') and ':' in line and 'records' in line:
            try:
                # Extract country and count
                parts = line[2:].split(':')  # Remove "- " prefix
                country = parts[0].strip()
                count_text = parts[1].strip()

                # Extract number from "X,XXX records"
                count_str = count_text.replace('records', '').replace(',', '').strip()
                count = int(count_str)

                # Get flag
                flag = get_country_flag(country)

                countries_data.append((flag, country, count))
            except (ValueError, IndexError):
                continue

    # Sort by count descending
    return sorted(countries_data, key=lambda x: x[2], reverse=True)


def parse_recent_observations(observations_text: str) -> List[tuple[str, str, str, str]]:
    """
    Parse recent observations text to extract location data with flags.

    Args:
        observations_text: Text like "  - Location: (59.1234, 10.5678) in Norway on 2023-05-15"

    Returns:
        List of tuples: (flag, country, coordinates, date)
    """
    if not observations_text or observations_text == "Unknown":
        return []

    observations_data = []
    lines = observations_text.split('\n')

    for line in lines:
        line = line.strip()
        # Look for pattern: "  - Location: (lat, lon) in Country on date"
        if line.startswith('- Location:') and ' in ' in line and ' on ' in line:
            try:
                # Extract components
                # "- Location: (59.1234, 10.5678) in Norway on 2023-05-15"
                parts = line.split(' in ')
                coords_part = parts[0].replace('- Location:', '').strip()

                location_date = parts[1].split(' on ')
                country = location_date[0].strip()
                date = location_date[1].strip()

                # Get flag
                flag = get_country_flag(country)

                observations_data.append((flag, country, coords_part, date))
            except (IndexError, ValueError):
                continue

    return observations_data
