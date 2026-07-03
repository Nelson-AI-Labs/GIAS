#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Semantic Scholar Search API Module
Primary academic source finder with citation-based quality signals across all disciplines.
"""

import html
import re
import time
import requests
from typing import Dict, Any, Optional
from urllib.parse import urlparse


def _clean_title(raw: str) -> str:
    """Strip HTML tags and decode entities from API-returned titles."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw or "")).strip()

from core.utils.config_loader import get_secret

# ============================================================================
# API CONFIGURATION
# ============================================================================

SEMANTIC_SCHOLAR_API_KEY = get_secret('SEMANTIC_SCHOLAR')
_API_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"

# Fields we request from the API
# abstract is fetched for relevance scoring and stripped before caching
# publicationTypes is fetched so we can categorise results as academic vs. grey literature
_FIELDS = "title,abstract,citationCount,influentialCitationCount,publicationVenue,openAccessPdf,externalIds,year,publicationTypes,authors"

# Publication types considered peer-reviewed academic literature.
# Everything outside this set (Book, Dataset, Patent, Thesis, etc.) is grey literature.
_ACADEMIC_PUBLICATION_TYPES = {"JournalArticle", "Review", "MetaAnalysis", "ConferencePaper"}

# publicationTypes filter applied when grey literature is excluded.
_ACADEMIC_TYPES_PARAM = "JournalArticle,Review,MetaAnalysis,ConferencePaper"

# Semantic Scholar fieldsOfStudy filter per standard research topic.
# Narrows results to relevant academic disciplines at the API level.
# Custom topics (not in this dict) omit the filter entirely — no restriction.
_FIELDS_OF_STUDY: Dict[str, str] = {
    "taxonomic_identity":      "Biology",
    "biological_traits":       "Biology",
    "distribution_and_status": "Biology,Environmental Science,Geography",
    "habitat_ecology":         "Biology,Environmental Science",
    "species_interactions":    "Biology,Environmental Science",
    "impacts":                 "Biology,Environmental Science,Agricultural and Food Sciences,Medicine",
    "introduction_pathways":   "Biology,Environmental Science",
    "management_biosecurity":  "Biology,Environmental Science,Agricultural and Food Sciences,Law",
    "detection_monitoring":    "Biology,Environmental Science",
}

# ============================================================================
# CORE FUNCTION
# ============================================================================

def semantic_scholar_search_json(
    query: str,
    research_topic: str = "",
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    include_grey: bool = True,
    limit: int = 20,
    continuation_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Search Semantic Scholar and return standardised result dicts.

    Args:
        query:               Search query (e.g. '"Carcinus maenas" invasion ecology')
        research_topic:      Standard topic key (e.g. 'habitat_ecology'). When provided
                             and recognised, adds a fieldsOfStudy filter to narrow results
                             to relevant academic disciplines. Custom or unknown topics
                             omit the filter entirely.
        year_min:            Earliest publication year to include (inclusive). Defaults to 2015.
        year_max:            Latest publication year to include (inclusive). Defaults to open-ended.
        include_grey:        When False, restricts to JournalArticle/Review/MetaAnalysis/
                             ConferencePaper only. When True, all publication types are returned.
        limit:               Maximum number of results to return (default: 20).
        continuation_token:  Cursor token from a previous response for paginated fetching.
                             When provided, the API resumes from the next page of results.

    Returns:
        Dict with 'results' list (standardised schema) or 'error' key on failure.
        Also includes 'continuation_token' (str or None) for fetching the next page.
        Each result contains: title, url, domain, source_api, doi,
        has_pdf, pdf_url, publication_year, journal_name, citation_count,
        content_category ('academic' or 'grey').
    """
    # Build year filter: "YYYY-" (open end) or "YYYY-YYYY" (range)
    if year_min and year_max:
        year_param = f"{year_min}-{year_max}"
    elif year_min:
        year_param = f"{year_min}-"
    else:
        year_param = "2015-"  # existing default when no filter supplied

    params: Dict[str, Any] = {
        "query": _build_ss_query(query),
        "fields": _FIELDS,
        "year": year_param,
        "limit": limit,
    }

    # Cursor-based pagination: pass token to resume from a previous result set
    if continuation_token:
        params["token"] = continuation_token

    # Restrict to academic publication types when grey literature is excluded
    if not include_grey:
        params["publicationTypes"] = _ACADEMIC_TYPES_PARAM

    fields_of_study = _FIELDS_OF_STUDY.get(research_topic)
    if fields_of_study:
        params["fieldsOfStudy"] = fields_of_study

    headers: Dict[str, str] = {}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY

    # Retry with backoff on 429 (rate limit). Sleep only after a 429 response,
    # honouring the Retry-After header when present. Authenticated requests rarely
    # hit rate limits, but the public tier shares a global pool with other users.
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(
                _API_ENDPOINT, params=params, headers=headers, timeout=15
            )
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = int(response.headers.get("Retry-After", 5 + attempt * 5))
                    time.sleep(retry_after)
                    continue
                return {"error": "Semantic Scholar rate limited after retries"}
            response.raise_for_status()
            data = response.json()
            break
        except requests.exceptions.RequestException as e:
            return {"error": f"Semantic Scholar request failed: {e}"}
        except Exception as e:
            return {"error": f"Semantic Scholar search failed: {e}"}
    else:
        return {"error": "Semantic Scholar: max retries exceeded"}

    # Capture cursor for next page (None when results are exhausted)
    next_token: Optional[str] = data.get("token") or None

    raw_papers = data.get("data", [])
    results = []

    for paper in raw_papers:
        # -- PDF url --
        oa = paper.get("openAccessPdf") or {}
        pdf_url: Optional[str] = oa.get("url") or None

        # -- Canonical URL (DOI → PDF → Semantic Scholar paper page) --
        external_ids = paper.get("externalIds") or {}
        doi: Optional[str] = external_ids.get("DOI") or None
        paper_id: Optional[str] = paper.get("paperId") or None
        if doi:
            url = f"https://doi.org/{doi}"
        elif pdf_url:
            url = pdf_url
        elif paper_id:
            url = f"https://www.semanticscholar.org/paper/{paper_id}"
        else:
            continue

        domain = _extract_domain(url)

        citation_count: Optional[int] = paper.get("citationCount")

        # -- Venue --
        venue = paper.get("publicationVenue") or {}
        journal_name: Optional[str] = venue.get("name") or None

        # -- Authors --
        # SS returns a list of {"authorId": ..., "name": ...} dicts; extract names only
        raw_authors = paper.get("authors") or []
        authors = [a["name"] for a in raw_authors if a.get("name")]

        # All Semantic Scholar results are "academic" — preprints and other
        # non-journal types still come from an academic database.
        pub_types = paper.get("publicationTypes") or []
        is_academic = bool(set(pub_types) & _ACADEMIC_PUBLICATION_TYPES)
        content_category = "academic"

        results.append({
            "title": _clean_title(paper.get("title") or ""),
            "url": url,
            "domain": domain,
            "source_api": "semantic_scholar",
            "doi": doi,
            "authors": authors,
            "has_pdf": pdf_url is not None,
            "pdf_url": pdf_url,
            "publication_year": paper.get("year"),
            "journal_name": journal_name,
            "citation_count": citation_count,
            "influential_citation_count": paper.get("influentialCitationCount"),
            "publication_types": pub_types,
            "content_category": content_category,
            # search context filled in by pipeline
            "search_term_used": "",
            "full_query_used": query,
            "species_context": "",
            # temporary — used by relevance filter, stripped before caching
            "_abstract": paper.get("abstract") or "",
        })

    return {"results": results, "continuation_token": next_token}


# ============================================================================
# HAYSTACK TOOL WRAPPER
# ============================================================================

from haystack.tools import Tool  # noqa: E402  (placed after main logic intentionally)

semantic_scholar_search_json_tool = Tool(
    name="semantic_scholar_search_json",
    description=(
        "Search Semantic Scholar for peer-reviewed academic papers and return "
        "structured JSON with citation metrics and PDF links."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "Search query string",
        },
    },
    function=semantic_scholar_search_json,
)

# ============================================================================
# HELPERS
# ============================================================================

def _build_ss_query(raw_query: str) -> str:
    """
    Transform '"Species name" "required phrase" keyword1 keyword2'
    into '+"Species name" +"required phrase" (keyword1 | keyword2)'.

    The bulk search endpoint uses Lucene syntax:
    - Every quoted phrase → mandatory via + prefix. The first is the species
      name; additional quoted phrases are required topic anchors (e.g.
      +"invasive" or +"management effectiveness").
    - Bare words → OR'd with | inside parentheses — any single keyword
      matching is sufficient.

    CRITICAL: In Lucene syntax, when any + operator is present, bare unadorned
    terms beside it are implicitly AND-required (not optional). This means
    +"species" morphology physical makes BOTH morphology AND physical required.
    Explicit | grouping is the only way to make topic keywords genuinely optional:
    +"species" (morphology | physical | characteristics).

    The word OR is NOT a valid operator on this endpoint — only | works.
    Literal "OR" tokens in the raw query are stripped before processing.
    """
    quoted_parts = re.findall(r'"[^"]*"', raw_query)
    remaining = re.sub(r'"[^"]*"', '', raw_query).strip()
    # Strip literal "OR" artefacts left over from old-style synonym notation
    keywords = [k for k in remaining.split() if k.upper() != 'OR']

    parts = []
    for qp in quoted_parts:          # ALL quoted phrases → mandatory
        parts.append(f'+{qp}')
    if len(keywords) > 1:
        parts.append(f"({' | '.join(keywords)})")  # OR-grouped bare keywords
    elif keywords:
        parts.append(keywords[0])    # single keyword, no grouping needed

    return " ".join(parts)


def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.replace("www.", "") if netloc else ""
    except Exception:
        return ""


if __name__ == "__main__":
    print("Semantic Scholar Search API Module")
    print("Run with a query to test: e.g. python -m functionalities.source_finding.api.semantic_scholar_search")
