#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
OpenAlex Search API Module
Broad academic source finder with 250M+ works indexed, including many open-access
AIS papers not covered by Semantic Scholar. Topic-level filtering narrows results
before the relevance filter runs.
"""

import html
import re
import requests
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from core.utils.config_loader import get_secret

# ============================================================================
# API CONFIGURATION
# ============================================================================

_API_ENDPOINT = "https://api.openalex.org/works"

# Email for the OpenAlex polite pool (higher rate limits, no API key required).
# Users should set OPENALEX_EMAIL in .streamlit/secrets.toml.
OPENALEX_EMAIL: str = get_secret("OPENALEX_EMAIL") or ""

# OpenAlex topic IDs that best match each standard research topic.
# Filter uses topics.id with pipe-separated IDs for OR logic.
# IDs discovered via https://api.openalex.org/topics?search=<term>
#   T12213 = Marine Ecology and Invasive Species
#   T12701 = Biological Control of Invasive Species
#   T10005 = Ecology and Vegetation Dynamics Studies
#   T12640 = Environmental DNA in Biodiversity Studies
#   T10895 = Species Distribution and Climate Change
#   T12097 = Aquatic Invertebrate Ecology and Behavior
_TOPIC_FILTER: Dict[str, str] = {
    "management_biosecurity":  "T12213|T12701",
    "detection_monitoring":    "T12213|T12640",
    "introduction_pathways":   "T12213|T12701",
    "impacts":                 "T12213|T10005",
    "distribution_and_status": "T10895|T12213",
    "habitat_ecology":         "T10005|T12097",
    "species_interactions":    "T10005|T12097",
    "biological_traits":       "T10005|T12097",
    "taxonomic_identity":      "T10005",
}

# Fields we request from the API (comma-separated, no spaces).
# abstract_inverted_index is OpenAlex's abstract format — must be reconstructed.
_SELECT_FIELDS = (
    "id,title,doi,publication_year,primary_location,"
    "cited_by_count,abstract_inverted_index,open_access"
)


# ============================================================================
# CORE FUNCTION
# ============================================================================

def openalex_search_json(
    query: str,
    research_topic: str = "",
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 10,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search OpenAlex and return standardised result dicts.

    Args:
        query:          Search query (e.g. '"Carcinus maenas" invasion ecology').
                        Passed directly to OpenAlex full-text search.
        research_topic: Standard topic key (e.g. 'habitat_ecology'). When recognised,
                        adds a topics.display_name filter to narrow to relevant discipline.
        year_min:       Earliest publication year (inclusive).
        year_max:       Latest publication year (inclusive).
        limit:          Maximum number of results to return (default: 10).
        cursor:         Cursor for paginated fetching. Use None or '*' for the first page;
                        pass the 'next_cursor' from a previous response to continue.

    Returns:
        Dict with 'results' (standardised schema) and 'next_cursor' (str or None).
        Returns {'results': [], 'next_cursor': None} on failure (logs warning, never raises).
    """
    params: Dict[str, Any] = {
        "search": query,
        "select": _SELECT_FIELDS,
        "per-page": limit,
        "cursor": cursor or "*",
    }

    # Add polite-pool email if configured
    if OPENALEX_EMAIL:
        params["mailto"] = OPENALEX_EMAIL

    # Topic filter: narrows to discipline cluster at the API level.
    # Uses topics.id with pipe-separated IDs (OR logic).
    topic_filter = _TOPIC_FILTER.get(research_topic)
    if topic_filter:
        params["filter"] = f"topics.id:{topic_filter}"

    # Year range filter via publication_year filter
    if year_min and year_max:
        year_filter = f"publication_year:{year_min}-{year_max}"
    elif year_min:
        year_filter = f"publication_year:>{year_min - 1}"
    elif year_max:
        year_filter = f"publication_year:<{year_max + 1}"
    else:
        year_filter = None

    if year_filter:
        existing_filter = params.get("filter", "")
        params["filter"] = f"{existing_filter},{year_filter}" if existing_filter else year_filter

    try:
        response = requests.get(_API_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        import logging
        logging.getLogger(__name__).warning("OpenAlex request failed: %s", e)
        return {"results": [], "next_cursor": None}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("OpenAlex search failed: %s", e)
        return {"results": [], "next_cursor": None}

    meta = data.get("meta") or {}
    next_cursor: Optional[str] = meta.get("next_cursor") or None

    raw_works = data.get("results") or []
    results: List[Dict[str, Any]] = []

    for work in raw_works:
        # -- Abstract --
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

        # -- DOI and canonical URL --
        doi: Optional[str] = work.get("doi")
        if doi:
            # OpenAlex returns full DOI URLs like "https://doi.org/10...."
            doi_clean = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
            url = f"https://doi.org/{doi_clean}"
            doi = doi_clean
        else:
            # Fall back to OpenAlex landing page
            oa_id = work.get("id") or ""
            url = oa_id if oa_id.startswith("http") else ""
            if not url:
                continue  # skip works with no usable URL

        domain = _extract_domain(url)

        # -- Open access / PDF --
        open_access = work.get("open_access") or {}
        is_oa: bool = open_access.get("is_oa", False)
        pdf_url: Optional[str] = open_access.get("oa_url") or None

        # -- Journal name from primary_location --
        primary_location = work.get("primary_location") or {}
        source = primary_location.get("source") or {}
        journal_name: Optional[str] = source.get("display_name") or None

        results.append({
            "title": _clean_title(work.get("title") or ""),
            "url": url,
            "domain": domain,
            "source_api": "openalex",
            "doi": doi,
            "authors": [],  # not included in select to minimise response size
            "has_pdf": pdf_url is not None or is_oa,
            "pdf_url": pdf_url,
            "publication_year": work.get("publication_year"),
            "journal_name": journal_name,
            "citation_count": work.get("cited_by_count"),
            "influential_citation_count": None,
            "content_category": "academic",
            # search context filled in by pipeline
            "search_term_used": "",
            "full_query_used": query,
            "species_context": "",
            # temporary — used by relevance filter, stripped before caching
            "_abstract": abstract,
        })

    return {"results": results, "next_cursor": next_cursor}


# ============================================================================
# HAYSTACK TOOL WRAPPER
# ============================================================================

from haystack.tools import Tool  # noqa: E402

openalex_search_json_tool = Tool(
    name="openalex_search_json",
    description=(
        "Search OpenAlex for peer-reviewed academic papers (250M+ works indexed) "
        "and return structured JSON with open-access links."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "Search query string",
        },
    },
    function=openalex_search_json,
)


# ============================================================================
# HELPERS
# ============================================================================

def _reconstruct_abstract(inv_index: Optional[Dict[str, List[int]]]) -> str:
    """
    Reconstruct a plain-text abstract from OpenAlex's inverted index format.

    OpenAlex stores abstracts as {word: [position, ...]} dicts to save space.
    We reverse this into a word list ordered by position.
    """
    if not inv_index:
        return ""
    try:
        max_pos = max(pos for positions in inv_index.values() for pos in positions)
        words = [""] * (max_pos + 1)
        for word, positions in inv_index.items():
            for pos in positions:
                words[pos] = word
        return " ".join(words)
    except (ValueError, TypeError):
        return ""


def _clean_title(raw: str) -> str:
    """Strip HTML tags and decode entities from API-returned titles."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw or "")).strip()


def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.replace("www.", "") if netloc else ""
    except Exception:
        return ""


if __name__ == "__main__":
    print("OpenAlex Search API Module")
