#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Google Scholar Search API Module (via SerpAPI)
Provides access to Google Scholar's broad academic index, including grey-zone
sources and highly-cited papers that may not appear in Semantic Scholar or
Europe PMC.

QUOTA WARNING: SerpAPI free tier allows only 100 searches/month across all
Google products. This module must be enabled explicitly via
search_filters['include_google_scholar'] = True, and is capped at 2 searches
per pipeline run to protect the monthly quota.

Do not call this function for every search term — the pipeline enforces the cap.
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

_API_ENDPOINT = "https://serpapi.com/search"

SERPAPI_KEY: str = get_secret("SERPAPI_KEY") or ""


# ============================================================================
# CORE FUNCTION
# ============================================================================

def google_scholar_search_json(
    query: str,
    research_topic: str = "",
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Search Google Scholar via SerpAPI and return standardised result dicts.

    QUOTA: This function consumes 1 SerpAPI credit per call.
    Free tier: 100 credits/month. Never call this in a loop over all search terms.
    The pipeline enforces a 2-call cap per run via gs_search_count.

    Args:
        query:          Search query (e.g. '"Dreissena polymorpha" management effectiveness').
        research_topic: Standard topic key (used for logging only).
        year_min:       Earliest publication year (as_ylo param).
        year_max:       Latest publication year (as_yhi param).
        limit:          Number of results to request (1–20, default: 10).

    Returns:
        Dict with 'results' (standardised schema).
        Returns {'results': []} on failure (never raises).
    """
    if not SERPAPI_KEY:
        import logging
        logging.getLogger(__name__).warning(
            "Google Scholar search skipped: SERPAPI_KEY not configured in secrets.toml"
        )
        return {"results": []}

    params: Dict[str, Any] = {
        "engine": "google_scholar",
        "q": query,
        "num": min(limit, 20),  # SerpAPI caps at 20 per request
        "api_key": SERPAPI_KEY,
    }

    if year_min:
        params["as_ylo"] = year_min
    if year_max:
        params["as_yhi"] = year_max

    try:
        response = requests.get(_API_ENDPOINT, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        import logging
        logging.getLogger(__name__).warning("Google Scholar (SerpAPI) request failed: %s", e)
        return {"results": []}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Google Scholar search failed: %s", e)
        return {"results": []}

    # SerpAPI error response
    if "error" in data:
        import logging
        logging.getLogger(__name__).warning("SerpAPI error: %s", data["error"])
        return {"results": []}

    raw_results = data.get("organic_results") or []
    results: List[Dict[str, Any]] = []

    for item in raw_results:
        title = _clean_title(item.get("title") or "")
        if not title:
            continue

        url = item.get("link") or ""
        if not url:
            continue

        domain = _extract_domain(url)

        # -- Citation count --
        inline_links = item.get("inline_links") or {}
        cited_by = inline_links.get("cited_by") or {}
        citation_count: Optional[int] = cited_by.get("total") or None

        # -- PDF --
        pdf_url: Optional[str] = None
        has_pdf = False
        for resource in (item.get("resources") or []):
            if (resource.get("file_format") or "").upper() == "PDF":
                pdf_url = resource.get("link") or None
                has_pdf = pdf_url is not None
                break

        # -- Publication year and authors from publication_info.summary --
        pub_info = item.get("publication_info") or {}
        summary = pub_info.get("summary") or ""
        year = _parse_year_from_summary(summary)
        authors = _parse_authors_from_summary(summary)
        journal_name = _parse_journal_from_summary(summary)

        # -- Abstract from snippet --
        abstract = item.get("snippet") or ""

        results.append({
            "title": title,
            "url": url,
            "domain": domain,
            "source_api": "google_scholar",
            "doi": None,  # SerpAPI does not return DOI reliably
            "authors": authors,
            "has_pdf": has_pdf,
            "pdf_url": pdf_url,
            "publication_year": year,
            "journal_name": journal_name,
            "citation_count": citation_count,
            "influential_citation_count": None,
            "content_category": "academic",
            # search context filled in by pipeline
            "search_term_used": "",
            "full_query_used": query,
            "species_context": "",
            # temporary — used by relevance filter, stripped before caching
            "_abstract": abstract,
        })

    return {"results": results}


# ============================================================================
# HAYSTACK TOOL WRAPPER
# ============================================================================

from haystack.tools import Tool  # noqa: E402

google_scholar_search_json_tool = Tool(
    name="google_scholar_search_json",
    description=(
        "Search Google Scholar via SerpAPI and return structured JSON. "
        "QUOTA: consumes 1 SerpAPI credit per call (100/month free). "
        "Only use for high-priority searches."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "Search query string",
        },
    },
    function=google_scholar_search_json,
)


# ============================================================================
# HELPERS
# ============================================================================

def _parse_year_from_summary(summary: str) -> Optional[int]:
    """Extract a 4-digit year from a SerpAPI publication_info.summary string."""
    match = re.search(r"\b(19|20)\d{2}\b", summary)
    if match:
        try:
            return int(match.group())
        except ValueError:
            pass
    return None


def _parse_authors_from_summary(summary: str) -> List[str]:
    """
    Extract author names from a SerpAPI publication_info.summary string.

    Summary format is typically: "A Smith, B Jones - Journal Name, 2023"
    We take everything before the first " - " as the author segment.
    """
    if " - " in summary:
        author_segment = summary.split(" - ")[0].strip()
        return [a.strip() for a in author_segment.split(",") if a.strip()]
    return []


def _parse_journal_from_summary(summary: str) -> Optional[str]:
    """
    Extract journal name from a SerpAPI publication_info.summary string.

    Summary format: "A Smith - Journal Name, 2023 - Publisher"
    The journal name is typically the segment after the first " - ".
    """
    parts = summary.split(" - ")
    if len(parts) >= 2:
        # Second segment is "Journal Name, Year" — strip the year
        journal_segment = parts[1].strip()
        journal_name = re.sub(r",?\s*(19|20)\d{2}.*$", "", journal_segment).strip()
        return journal_name if journal_name else None
    return None


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
    print("Google Scholar Search API Module (SerpAPI)")
