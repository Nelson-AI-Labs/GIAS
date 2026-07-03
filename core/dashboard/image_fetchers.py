#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Image Fetchers
Functions for retrieving species images from various sources (Wikipedia, GBIF, cached data).
"""

import re
from typing import Optional

import requests

from core.dashboard.data_loaders import load_categorized_species_json
from core.utils.config_loader import get_contact_email


# ============================================================================
# IMAGE FETCHING FUNCTIONS
# ============================================================================

def get_species_image_url(species_name: str, universal_id: Optional[str] = None, gbif_key: Optional[int] = None) -> Optional[str]:
    """
    Get species image URL, prioritizing Wikipedia, then cached image_url, then GBIF media.

    Args:
        species_name: The species name
        universal_id: Optional universal identifier for cache lookup
        gbif_key: Optional GBIF taxon key (kept for backwards compatibility, not used)

    Returns:
        Image URL string or None
    """
    # Priority 1: Wikipedia API (curated editorial images)
    wikipedia_image = fetch_wikipedia_image(species_name)
    if wikipedia_image:
        return wikipedia_image

    # If Wikipedia fails, try cached data
    categorized_data = load_categorized_species_json(species_name, universal_id=universal_id)

    if categorized_data and 'categorized_fields' in categorized_data:
        data_metadata = categorized_data['categorized_fields'].get('data_metadata', {})

        # Priority 2: Cached image_url field (legacy)
        image_url_data = data_metadata.get('image_url', [])
        if isinstance(image_url_data, list) and image_url_data:
            for entry in image_url_data:
                if isinstance(entry, dict) and 'value' in entry:
                    cached_image_url = entry['value']
                    if cached_image_url:
                        return cached_image_url

        # Priority 3: GBIF media (from metadata.media field) - fallback for species without Wikipedia images
        media_data = data_metadata.get('media', [])
        if isinstance(media_data, list) and media_data:
            for entry in media_data:
                if isinstance(entry, dict) and 'value' in entry:
                    media_list = entry['value']
                    if isinstance(media_list, list) and len(media_list) > 0:
                        # Get the first media item
                        first_media = media_list[0]
                        if isinstance(first_media, dict):
                            image_url = first_media.get('identifier')
                            if image_url and isinstance(image_url, str):
                                return image_url

    # No image found
    return None


def fetch_wikipedia_image(species_name: str) -> Optional[str]:
    """
    Fetch main image from Wikipedia using scientific name.

    Uses the MediaWiki Action API to retrieve the primary image from a species' Wikipedia page.
    This provides curated, high-quality editorial images for species.
    Automatically follows redirects (e.g., scientific name → common name).

    Args:
        species_name: Scientific name of the species (e.g., "Procambarus clarkii")

    Returns:
        Image URL string from Wikimedia Commons or None if not found
    """
    if not species_name:
        return None

    try:
        # Replace spaces with underscores for Wikipedia page titles
        page_title = species_name.replace(' ', '_')

        api_url = "https://en.wikipedia.org/w/api.php"
        headers = {
            "User-Agent": f"GuardIAS/1.0 (contact: {get_contact_email()})",
            "Accept": "application/json"
        }

        # METHOD 1: Try pageimages API first (fastest, works for some pages)
        params = {
            'action': 'query',
            'titles': page_title,
            'prop': 'pageimages',
            'piprop': 'original',
            'format': 'json',
            'formatversion': 2,
            'redirects': 1  # Follow redirects automatically
        }

        response = requests.get(api_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        pages = data.get('query', {}).get('pages', [])

        if pages and 'original' in pages[0]:
            return pages[0]['original']['source']

        # METHOD 2: If pageimages didn't work, parse the page HTML for images
        params = {
            'action': 'parse',
            'page': page_title,
            'prop': 'text',
            'format': 'json',
            'formatversion': 2,
            'redirects': 1  # Follow redirects
        }

        response = requests.get(api_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if 'parse' in data and 'text' in data['parse']:
            html = data['parse']['text']

            # Find Wikimedia Commons images in the HTML
            # Pattern matches: upload.wikimedia.org/wikipedia/commons/.../*.jpg or *.png
            pattern = r'upload\.wikimedia\.org/wikipedia/commons/(?:thumb/)?([a-f0-9]/[a-f0-9]{2}/[^/"]+\.(?:jpg|jpeg|png))'
            matches = re.findall(pattern, html, re.IGNORECASE)

            if matches:
                # Reconstruct full URL from first match
                image_path = matches[0]
                return f"https://upload.wikimedia.org/wikipedia/commons/{image_path}"

        return None

    except requests.exceptions.RequestException as e:
        print(f"Error fetching Wikipedia image for {species_name}: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"Error parsing Wikipedia response for {species_name}: {e}")
        return None
