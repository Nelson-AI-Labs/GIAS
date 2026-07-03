#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
DOAJ (Directory of Open Access Journals) Search API Module
Highest-precision source in the stack: targets four AIS-specialist open-access
journals where every article is relevant to the domain.

Only called for management-core topics — no benefit for ecology-support topics
(habitat_ecology, biological_traits, species_interactions, taxonomic_identity)
since those journals don't publish that content.
"""

import html
import re
import requests
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse, urljoin

# ============================================================================
# API CONFIGURATION
# ============================================================================

_API_BASE = "https://doaj.org/api/search/articles/"

# AIS-specialist open-access journals indexed in DOAJ.
# These journals have management as core editorial content, so ISSN-filtered
# queries return near-zero noise — every result is domain-relevant.
_AIS_JOURNAL_ISSNS: List[str] = [
    "1989-8649",  # Management of Biological Invasions (tier 1 — management-first)
    "1314-2488",  # NeoBiota (tier 2 — management + ecology)
    "1798-6540",  # Aquatic Invasions (tier 3 — aquatic-specific)
    "2047-2382",  # Environmental Evidence (tier 1 — systematic reviews only)
]


# ============================================================================
# CORE FUNCTION
# ============================================================================

def doaj_search_json(
    query: str,
    research_topic: str = "",
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    limit: int = 10,
    page: int = 1,
) -> Dict[str, Any]:
    """
    Search DOAJ for AIS-specialist open-access journal articles.

    Restricts results to four high-priority AIS journals via ISSN filtering.
    This is the highest-precision source in the pipeline — results are always
    on-domain, so the relevance filter acts as a species/topic check, not a
    domain check.

    Only call this function for management-core topics
    (management_biosecurity, detection_monitoring, introduction_pathways, impacts).
    Calling for ecology-support topics wastes a request — those journals don't
    publish habitat ecology or taxonomic papers.

    Args:
        query:          Search query (e.g. '"Dreissena polymorpha" management effectiveness').
                        Passed to DOAJ Elasticsearch query, AND'd with ISSN filter.
        research_topic: Standard topic key (used for logging only; topic guard is
                        handled by the caller in pipeline.py).
        year_min:       Earliest publication year (inclusive). Applied via bibjson filter.
        year_max:       Latest publication year (inclusive).
        limit:          Maximum results per page (default: 10; DOAJ max: 100).
        page:           Page number for pagination (1-indexed).

    Returns:
        Dict with 'results' (standardised schema) and 'next_page' (int or None).
        Returns {'results': [], 'next_page': None} on failure (never raises).
    """
    # Build ISSN filter: any of the four target journals
    issn_filter = " OR ".join(
        f'bibjson.journal.issns:"{issn}"' for issn in _AIS_JOURNAL_ISSNS
    )
    full_query = f"({query}) AND ({issn_filter})"

    params: Dict[str, Any] = {
        "pageSize": limit,
        "page": page,
    }

    # DOAJ uses URL-path-based query: /api/search/articles/{query}
    search_url = f"{_API_BASE}{_url_encode_query(full_query)}"

    try:
        response = requests.get(search_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        import logging
        logging.getLogger(__name__).warning("DOAJ request failed: %s", e)
        return {"results": [], "next_page": None}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("DOAJ search failed: %s", e)
        return {"results": [], "next_page": None}

    raw_articles = data.get("results") or []
    total = data.get("total") or 0

    results: List[Dict[str, Any]] = []

    for article in raw_articles:
        bib = article.get("bibjson") or {}

        # -- Title --
        title = _clean_title(bib.get("title") or "")
        if not title:
            continue

        # -- DOI and URL --
        doi: Optional[str] = None
        url: Optional[str] = None
        for id_entry in (bib.get("identifier") or []):
            if id_entry.get("type") == "doi":
                doi = id_entry.get("id")
                if doi:
                    url = f"https://doi.org/{doi}"
                break

        if not url:
            # Fall back to article link
            links = bib.get("link") or []
            for link in links:
                if link.get("url"):
                    url = link["url"]
                    break

        if not url:
            continue  # no usable URL

        domain = _extract_domain(url)

        # -- PDF --
        pdf_url: Optional[str] = None
        has_pdf = False
        for link in (bib.get("link") or []):
            if link.get("type") == "fulltext" and link.get("url"):
                link_url = link["url"]
                if link_url.endswith(".pdf") or "pdf" in link_url.lower():
                    pdf_url = link_url
                    has_pdf = True
                    break
        # DOAJ articles are all open access — PDF is usually available
        if not has_pdf and (bib.get("link") or []):
            has_pdf = True  # open access but link type may not say "pdf"

        # -- Authors --
        authors: List[str] = []
        for a in (bib.get("author") or []):
            name = a.get("name") or ""
            if name:
                authors.append(name)

        # -- Journal name --
        journal = bib.get("journal") or {}
        journal_name: Optional[str] = journal.get("title") or None

        # -- Year --
        year: Optional[int] = None
        year_raw = bib.get("year")
        if year_raw:
            try:
                year = int(year_raw)
            except (ValueError, TypeError):
                pass

        # -- Year filter (DOAJ API doesn't support server-side year filtering) --
        if year_min and year and year < year_min:
            continue
        if year_max and year and year > year_max:
            continue

        # -- Abstract --
        abstract = bib.get("abstract") or ""

        results.append({
            "title": title,
            "url": url,
            "domain": domain,
            "source_api": "doaj",
            "doi": doi,
            "authors": authors,
            "has_pdf": has_pdf,
            "pdf_url": pdf_url,
            "publication_year": year,
            "journal_name": journal_name,
            "citation_count": None,  # DOAJ does not provide citation counts
            "influential_citation_count": None,
            "content_category": "academic",
            # search context filled in by pipeline
            "search_term_used": "",
            "full_query_used": query,
            "species_context": "",
            # temporary — used by relevance filter, stripped before caching
            "_abstract": abstract,
        })

    # Pagination: if there are more pages, return next page number
    fetched_so_far = (page - 1) * limit + len(raw_articles)
    next_page: Optional[int] = (page + 1) if fetched_so_far < total and raw_articles else None

    return {"results": results, "next_page": next_page}


# ============================================================================
# HAYSTACK TOOL WRAPPER
# ============================================================================

from haystack.tools import Tool  # noqa: E402

doaj_search_json_tool = Tool(
    name="doaj_search_json",
    description=(
        "Search DOAJ for open-access AIS-specialist journal articles "
        "(Management of Biological Invasions, NeoBiota, Aquatic Invasions, "
        "Environmental Evidence) and return structured JSON."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "Search query string",
        },
    },
    function=doaj_search_json,
)


# ============================================================================
# HELPERS
# ============================================================================

def _url_encode_query(query: str) -> str:
    """URL-encode a query string for use in the DOAJ path-based API."""
    from urllib.parse import quote
    return quote(query, safe="")


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
    print("DOAJ Search API Module")
