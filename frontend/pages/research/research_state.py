# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Research State Management
State initialization and migration for the research interface.
"""

import uuid
import streamlit as st
from core.dashboard.dashboard_tools import (
    get_taxonomic_data,
    get_morphological_data,
    get_physiological_data,
    get_distribution_data,
    get_environmental_data,
    get_conservation_data,
    get_species_interactions_data,
    get_impacts_data,
    get_management_data,
    get_economic_utilisation_data,
    get_detection_monitoring_data,
    get_all_database_links_with_species,
    get_available_databases,
)
from core.registries.topic_registry import StandardTopicRegistry

# Topic descriptions for tooltips - loaded from centralized registry
TOPIC_DESCRIPTIONS = StandardTopicRegistry.get_short_descriptions()

# Topic to dashboard card mapping - loaded from registry
TOPIC_TO_DASHBOARD_CARD = StandardTopicRegistry.get_dashboard_card_mapping()

# Mapping of data fetch functions to dashboard cards
# Keys match the dashboard_card values from the topic registry
FETCHER_MAP = {
    'taxonomic': get_taxonomic_data,
    'morphological': get_morphological_data,
    'physiological': get_physiological_data,
    'distribution': get_distribution_data,
    'environmental': get_environmental_data,
    'conservation': get_conservation_data,
    'species_interactions': get_species_interactions_data,
    'impacts': get_impacts_data,
    'management_biosecurity': get_management_data,
    'economic_utilisation': get_economic_utilisation_data,
    'detection_monitoring': get_detection_monitoring_data
}

# Comprehensive database info mapping (covers all possible databases)
DATABASE_INFO_MAP = {
    'GBIF': {
        'full_name': 'Global Biodiversity Information Facility',
        'description': 'Species data from the Global Biodiversity Information Facility'
    },
    'WRiMS': {
        'full_name': 'World Register of Marine Species',
        'description': 'Marine species data from the World Register of Marine Species'
    },
    'IUCN': {
        'full_name': 'IUCN Red List',
        'description': 'Conservation status data from the IUCN Red List of Threatened Species'
    },
    'EASIN': {
        'full_name': 'European Alien Species Information Network',
        'description': 'Invasive species data from the European Alien Species Information Network'
    },
    'AquaNIS': {
        'full_name': 'AquaNIS - Information System on Aquatic Non-Indigenous Species',
        'description': 'Aquatic invasive species data from AquaNIS'
    }
}

# Anchor topics - loaded from centralized registry (underscore format internally)
# Taxonomic Identity is excluded: it's populated from databases (DCP), not PDF extraction
ANCHOR_TOPICS = [t for t in StandardTopicRegistry.get_all_topic_keys() if t != 'taxonomic_identity']


def initialize_research_state_with_dcp_sources(species_name, universal_id):
    """Initialize research state with DCP sources from dashboard data"""

    topic_sources = {}

    # Initialize each anchor topic with DCP sources
    for topic in ANCHOR_TOPICS:
        card_key = TOPIC_TO_DASHBOARD_CARD.get(topic)
        dcp_sources = []

        if card_key and card_key in FETCHER_MAP:
            try:
                # Fetch data for this card
                data = FETCHER_MAP[card_key](species_name, universal_id=universal_id)
                dcp_sources = data.get('data_sources', [])
            except Exception as e:
                print(f"Error fetching DCP sources for {topic}: {e}")
                dcp_sources = []

        topic_sources[topic] = {
            'dcp_sources': dcp_sources,
            'research_source_urls': [],
            'dcp_count': len(dcp_sources),
            'research_count': 0,
            'total_count': len(dcp_sources),
            'dashboard_card': card_key
        }

    # Build reverse mapping: which topics does each DCP source have data for?
    source_to_topics = {}
    for topic, topic_data in topic_sources.items():
        dcp_sources_for_topic = topic_data['dcp_sources']
        for source_name in dcp_sources_for_topic:
            if source_name not in source_to_topics:
                source_to_topics[source_name] = []
            source_to_topics[source_name].append(topic)

    # Fetch database links using new modular method
    database_links = get_all_database_links_with_species(universal_id)

    # Get dynamically available databases from raw_api_data folder
    available_databases = get_available_databases(species_name, universal_id=universal_id)

    # Create URL mapping from modular links (first URL for each database)
    db_url_map = {}
    for link in database_links:
        db_name = link['database']
        db_url_map.setdefault(db_name, link['url'])

    all_sources = {}

    # Add DCP database sources to all_sources (only those that are available)
    for db_name in available_databases:
        db_info = DATABASE_INFO_MAP.get(db_name)
        if not db_info:
            # Unknown database - create generic info
            db_info = {
                'full_name': db_name,
                'description': f'Species data from {db_name}'
            }

        # Get URL from modular database links
        db_url = db_url_map.get(db_name)

        # Fallback: Use placeholder if no URL found
        if not db_url:
            db_url = f"https://database.placeholder/{db_name.lower()}"

        source_id = f"dcp_{db_name.lower()}"
        all_sources[source_id] = {
            'id': str(uuid.uuid4()),
            'url': db_url,
            'title': f"{db_name} Database",
            'domain': db_name,
            'score': 1.0,  # DCP sources are pre-approved with max score
            'topics': source_to_topics.get(db_name, []),  # Only topics with actual data
            'search_terms_used': st.session_state.get('synonyms_searched', [species_name]),
            'approved': True,
            'is_dcp_source': True,
            'uploaded_pdf': None,
            'pdf_filename': None
        }

    return {
        'anchor_topics': ANCHOR_TOPICS.copy(),
        'custom_topics': [],
        'topic_sources': topic_sources,
        'all_sources': all_sources,  # includes DCP (data-collection pipeline) sources
        'selected_for_next_run': [],
        'custom_topic_interpretations': {},  # Maps custom topic -> interpretation data
        'pagination': {},           # Cursor state for paginated "Find more" API calls
        'researched_topics': [],    # Topics that have been run through "Run Research"
                                    # — their checkboxes are greyed out; use Reset to retry
    }


