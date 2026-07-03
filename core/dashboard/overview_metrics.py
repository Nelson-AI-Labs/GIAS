# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Search Overview Metrics
=======================

Computes lightweight coverage metrics from already-loaded categorized data.
Used to render a quick-glance overview panel above the dashboard.
"""

from typing import Any, Dict, List

from core.registries.topic_registry import StandardTopicRegistry

ALL_DATABASES = ["GBIF", "WRiMS", "IUCN", "EASIN", "AquaNIS", "CABI"]


def compute_overview_metrics(
    categorized_fields: Dict[str, Any],
    synonyms_searched: List[str],
    sources_with_data: List[str],
) -> Dict[str, Any]:
    """
    Compute overview metrics from categorized species data.

    Args:
        categorized_fields: The 'categorized_fields' dict from load_categorized_data_by_id.
                            Structure: {topic_key: {field_name: [entries, ...]}}
        synonyms_searched:  List of synonym strings that were queried (from session state).
        sources_with_data:  List of database names that returned data (from manifest 'sources').

    Returns:
        Dict with keys:
            synonyms_searched   int   — number of name variants queried
            synonym_list        list  — the actual synonym strings
            sources_with_data   list  — databases that returned data
            sources_no_data     list  — databases that were queried but returned no data
            total_fields        int   — total non-empty fields across all standard topics
            topics              dict  — per-topic breakdown:
                {topic_key: {display_name, field_count, has_data}}
    """
    topic_metrics: Dict[str, Any] = {}
    total_fields = 0

    for topic_key in StandardTopicRegistry.get_all_topic_keys():
        topic_data = categorized_fields.get(topic_key, {})
        field_count = sum(1 for v in topic_data.values() if v)
        total_fields += field_count

        topic_def = StandardTopicRegistry.get_topic(topic_key)
        topic_metrics[topic_key] = {
            "display_name": topic_def.display_name,
            "field_count": field_count,
            "has_data": field_count > 0,
        }

    active = [s for s in ALL_DATABASES if s in sources_with_data]
    inactive = [s for s in ALL_DATABASES if s not in sources_with_data]

    return {
        "synonyms_searched": len(synonyms_searched),
        "synonym_list": synonyms_searched,
        "sources_with_data": active,
        "sources_no_data": inactive,
        "total_fields": total_fields,
        "topics": topic_metrics,
    }
