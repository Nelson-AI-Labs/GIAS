#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Paginated Source Fetcher
Fetches the next batch of sources for a topic using cursor-based pagination.
Called by the "Find more sources" UI button — distinct from the initial pipeline run.

Cursor state is stored in research_state['pagination'][topic] so successive
"Find more" clicks resume from where the last one stopped.
"""

import logging
from typing import Any, Dict, List, Optional

from functionalities.source_finding.api.semantic_scholar_search import semantic_scholar_search_json
from functionalities.source_finding.api.europe_pmc_search import europe_pmc_search_json
from functionalities.source_finding.api.openalex_search import openalex_search_json
from functionalities.source_finding.api.doaj_search import doaj_search_json
from functionalities.source_finding.agents.relevance_filter import score_relevance
from core.registries.topic_registry import StandardTopicRegistry

logger = logging.getLogger(__name__)

# ============================================================================
# CURSOR STATE HELPERS
# ============================================================================

def _init_cursor_state() -> Dict[str, Any]:
    """Return a fresh cursor state for a topic (first-ever fetch)."""
    return {
        "search_term_index": 0,
        "api_cursors": {
            "semantic_scholar": {"token": None, "exhausted": False},
            "europe_pmc": {"cursor_mark": "*", "exhausted": False},
            "openalex": {"cursor": "*", "exhausted": False},
            "doaj": {"page": 1, "exhausted": False},
            "tavily": {"exhausted": True},       # Tavily has no pagination
            "google_scholar": {"exhausted": True},  # single-shot, no pagination
        },
    }


def _all_apis_exhausted(cursor_state: Dict[str, Any]) -> bool:
    return all(
        v.get("exhausted", True)
        for v in cursor_state["api_cursors"].values()
    )


def _reset_api_cursors(cursor_state: Dict[str, Any]) -> None:
    """Reset API cursors to start position (called when advancing to next search term)."""
    cursor_state["api_cursors"]["semantic_scholar"] = {"token": None, "exhausted": False}
    cursor_state["api_cursors"]["europe_pmc"] = {"cursor_mark": "*", "exhausted": False}
    cursor_state["api_cursors"]["openalex"] = {"cursor": "*", "exhausted": False}
    cursor_state["api_cursors"]["doaj"] = {"page": 1, "exhausted": False}
    # Tavily and google_scholar stay exhausted — they never paginate


# ============================================================================
# MAIN FETCH FUNCTION
# ============================================================================

def fetch_next_batch(
    topic: str,
    species_name: str,
    search_filters: Optional[Dict[str, Any]] = None,
    existing_sources: Optional[Dict[str, Any]] = None,
    research_state: Optional[Dict[str, Any]] = None,
    batch_size: int = 5,
    per_api_limit: int = 2,
) -> Dict[str, Any]:
    """
    Fetch the next batch of sources for a topic using cursor-based API pagination.

    Reads and writes cursor state from research_state['pagination'][topic] so
    successive calls automatically resume from where the previous one stopped.

    Args:
        topic:            Topic key (anchor or custom).
        species_name:     Standardised species name.
        search_filters:   Filter dict (year_min, year_max, open_access_only, include_grey_literature).
        existing_sources: Dict of already-known sources keyed by URL (for deduplication).
        research_state:   The research_state dict from session state (cursor state lives here).
        batch_size:       Target total number of new sources to return per call.
        per_api_limit:    How many results to request from each individual paginating API
                          per loop iteration (SS / EPMC / OpenAlex / DOAJ). GS and Tavily
                          are single-shot (exhausted after initial run) and are never re-queried.

    Returns:
        {
            'new_sources': [list of normalised source dicts],
            'all_exhausted': bool  — True when no more sources can be found for any search term
        }
    """
    filters = search_filters or {}
    existing = existing_sources or {}

    # Resolve pagination state store
    if research_state is None:
        research_state = {}
    if "pagination" not in research_state:
        research_state["pagination"] = {}

    # Load or initialise cursor state for this topic
    if topic not in research_state["pagination"]:
        research_state["pagination"][topic] = _init_cursor_state()
    cursor_state = research_state["pagination"][topic]

    # Get all search terms for this topic
    normalized_key = StandardTopicRegistry.normalize_topic_name(topic)
    search_terms = StandardTopicRegistry.get_search_terms(normalized_key) or []

    if not search_terms:
        logger.warning("No search terms found for topic '%s' — cannot fetch more.", topic)
        return {"new_sources": [], "all_exhausted": True}

    new_sources: List[Dict[str, Any]] = []
    attempts = 0
    max_term_advances = len(search_terms)  # prevent infinite loop across search terms

    # Resolve DOAJ eligibility once — DOAJ only applies to management-core topics.
    # For ecology-support topics we must mark DOAJ exhausted up-front so that
    # _all_apis_exhausted() can return True and the loop can advance search terms.
    topic_def = StandardTopicRegistry.get_topic(topic)
    is_management_core = bool(topic_def and getattr(topic_def, "priority_tier", "") == "management_core")
    if not is_management_core:
        cursor_state["api_cursors"]["doaj"]["exhausted"] = True

    while len(new_sources) < batch_size and attempts <= max_term_advances:
        term_index = cursor_state["search_term_index"]
        if term_index >= len(search_terms):
            # All search terms exhausted
            break

        search_term = search_terms[term_index]
        full_query = f'"{species_name}" {search_term}'

        if _all_apis_exhausted(cursor_state):
            # Advance to next search term and reset cursors
            cursor_state["search_term_index"] += 1
            _reset_api_cursors(cursor_state)
            attempts += 1
            continue

        ss_batch: List[Dict[str, Any]] = []
        pmc_batch: List[Dict[str, Any]] = []
        oa_batch: List[Dict[str, Any]] = []
        doaj_batch: List[Dict[str, Any]] = []

        # -- Semantic Scholar --
        ss_cursors = cursor_state["api_cursors"]["semantic_scholar"]
        if not ss_cursors.get("exhausted"):
            try:
                data = semantic_scholar_search_json(
                    query=full_query,
                    research_topic=topic,
                    year_min=filters.get("year_min"),
                    year_max=filters.get("year_max"),
                    include_grey=filters.get("include_grey_literature", True),
                    limit=per_api_limit,
                    continuation_token=ss_cursors.get("token"),
                )
                if "error" not in data:
                    for r in data.get("results", []):
                        r["search_term_used"] = search_term
                        r["full_query_used"] = full_query
                        r["species_context"] = species_name
                        ss_batch.append(r)
                    # Update cursor
                    next_token = data.get("continuation_token")
                    ss_cursors["token"] = next_token
                    if not next_token:
                        ss_cursors["exhausted"] = True
            except Exception as e:
                logger.warning("SS paginated fetch failed for '%s': %s", search_term, e)
                ss_cursors["exhausted"] = True

        # -- Europe PMC --
        epmc_cursors = cursor_state["api_cursors"]["europe_pmc"]
        if not epmc_cursors.get("exhausted"):
            try:
                data = europe_pmc_search_json(
                    query=full_query,
                    page_size=per_api_limit,
                    year_min=filters.get("year_min"),
                    year_max=filters.get("year_max"),
                    open_access_only=filters.get("open_access_only", False),
                    include_grey=filters.get("include_grey_literature", True),
                    cursor_mark=epmc_cursors.get("cursor_mark", "*"),
                )
                if "error" not in data:
                    for r in data.get("results", []):
                        r["search_term_used"] = search_term
                        r["full_query_used"] = full_query
                        r["species_context"] = species_name
                        pmc_batch.append(r)
                    # Update cursor
                    next_cursor = data.get("next_cursor_mark")
                    if not next_cursor or next_cursor == epmc_cursors.get("cursor_mark"):
                        epmc_cursors["exhausted"] = True
                    else:
                        epmc_cursors["cursor_mark"] = next_cursor
            except Exception as e:
                logger.warning("EPMC paginated fetch failed for '%s': %s", search_term, e)
                epmc_cursors["exhausted"] = True

        # -- OpenAlex --
        oa_cursors = cursor_state["api_cursors"]["openalex"]
        if not oa_cursors.get("exhausted"):
            try:
                data = openalex_search_json(
                    query=full_query,
                    research_topic=topic,
                    year_min=filters.get("year_min"),
                    year_max=filters.get("year_max"),
                    limit=per_api_limit,
                    cursor=oa_cursors.get("cursor", "*"),
                )
                for r in data.get("results", []):
                    r["search_term_used"] = search_term
                    r["full_query_used"] = full_query
                    r["species_context"] = species_name
                    oa_batch.append(r)
                # Update cursor
                next_oa_cursor = data.get("next_cursor")
                oa_cursors["cursor"] = next_oa_cursor or "*"
                if not next_oa_cursor:
                    oa_cursors["exhausted"] = True
            except Exception as e:
                logger.warning("OpenAlex paginated fetch failed for '%s': %s", search_term, e)
                oa_cursors["exhausted"] = True

        # -- DOAJ (management-core topics only) --
        # Re-apply the exhausted flag after any _reset_api_cursors() call
        # to keep DOAJ correctly disabled for ecology-support topics.
        doaj_cursors = cursor_state["api_cursors"]["doaj"]
        if not is_management_core:
            doaj_cursors["exhausted"] = True
        if is_management_core and not doaj_cursors.get("exhausted"):
            try:
                data = doaj_search_json(
                    query=full_query,
                    research_topic=topic,
                    year_min=filters.get("year_min"),
                    year_max=filters.get("year_max"),
                    limit=per_api_limit,
                    page=doaj_cursors.get("page", 1),
                )
                for r in data.get("results", []):
                    r["search_term_used"] = search_term
                    r["full_query_used"] = full_query
                    r["species_context"] = species_name
                    doaj_batch.append(r)
                # Update page cursor
                next_page = data.get("next_page")
                if next_page:
                    doaj_cursors["page"] = next_page
                else:
                    doaj_cursors["exhausted"] = True
            except Exception as e:
                logger.warning("DOAJ paginated fetch failed for '%s': %s", search_term, e)
                doaj_cursors["exhausted"] = True

        # -- Apply relevance filter to all batches before adding to accumulator --
        # This mirrors pipeline.py and ensures "Find more" results are filtered
        # consistently with the initial pipeline run.
        ss_batch = score_relevance(ss_batch, species_name, topic)
        pmc_batch = score_relevance(pmc_batch, species_name, topic)
        oa_batch = score_relevance(oa_batch, species_name, topic)
        doaj_batch = score_relevance(doaj_batch, species_name, topic)

        for r in ss_batch + pmc_batch + oa_batch + doaj_batch:
            _maybe_add(r, existing, new_sources)

        attempts += 1

    all_exhausted = (
        cursor_state["search_term_index"] >= len(search_terms)
        and _all_apis_exhausted(cursor_state)
    )

    return {"new_sources": new_sources, "all_exhausted": all_exhausted}


# ============================================================================
# DEDUPLICATION HELPERS
# ============================================================================

def find_existing_source(
    url: str,
    doi: Optional[str],
    all_sources: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Return the stored source dict that matches url or doi, else None.

    Used by both the initial run (extraction_process.py) and paginated fetch
    so deduplication logic stays in one place.
    """
    if url and url in all_sources:
        return all_sources[url]
    if doi:
        for s in all_sources.values():
            if s.get("doi") == doi:
                return s
    return None


def _maybe_add(
    source: Dict[str, Any],
    existing: Dict[str, Any],
    accumulator: List[Dict[str, Any]],
) -> None:
    """Add source to accumulator only if not already in existing_sources or accumulator."""
    url = source.get("url", "")
    doi = source.get("doi")

    # Check against already-known sources (URL or DOI match)
    if find_existing_source(url, doi, existing):
        return

    # Check against sources already accumulated in this batch
    for s in accumulator:
        if url and s.get("url") == url:
            return
        if doi and s.get("doi") == doi:
            return

    accumulator.append(source)
