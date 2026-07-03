#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Europe PMC Search API Module
Life sciences specialist with strong coverage of government publications
(MEDLINE) and agricultural research (Agricola/USDA).

Supports optional year range and open-access filtering via query parameters.
"""

import html
import re
import requests
from typing import Dict, Any, Optional
from urllib.parse import urlparse


def _clean_title(raw: str) -> str:
    """Strip HTML tags and decode entities from API-returned titles."""
    return html.unescape(re.sub(r"<[^>]+>", "", raw or "")).strip()

_API_ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

# ============================================================================
# CORE FUNCTION
# ============================================================================

# Europe PMC SRC codes for peer-reviewed academic literature.
# MED = PubMed/MEDLINE, PMC = PubMed Central full-text.
# PPR (preprints), ETH (theses), PAT (patents), AGR (Agricola), etc.
# are included only when grey literature is enabled.
_ACADEMIC_SRC_CODES = {"MED", "PMC"}


def europe_pmc_search_json(
    query: str,
    page_size: int = 5,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    include_grey: bool = True,
    cursor_mark: str = "*",
) -> Dict[str, Any]:
    """
    Search Europe PMC and return standardised result dicts.

    Args:
        query:            Base query string (e.g. '"Carcinus maenas" invasion ecology').
        page_size:        Maximum number of results to return (default: 5)
        year_min:         Earliest publication year to include (inclusive).
        year_max:         Latest publication year to include (inclusive).
        open_access_only: When True, appends OPEN_ACCESS:Y to restrict to open-access only.
        include_grey:     When False, restricts to SRC:MED and SRC:PMC (peer-reviewed
                          journals + PMC full-text). When True, all sources are searched
                          including preprints (PPR), theses (ETH), patents (PAT), etc.
        cursor_mark:      Cursor for paginated fetching. Use '*' for the first page;
                          pass the 'next_cursor_mark' from a previous response to continue.

    Returns:
        Dict with 'results' list (standardised schema) or 'error' key on failure.
        Also includes 'next_cursor_mark' (str or None) for fetching the next page.
        Each result includes content_category ('academic' or 'grey').
    """
    # Europe PMC uses structured query syntax where space-separated words
    # are implicitly AND'd. For multi-word search terms like "behavior
    # activity patterns nocturnal diurnal", requiring ALL words kills
    # recall for niche species. We extract the species-quoted portion and
    # OR the remaining keywords so any single keyword match suffices.
    full_query = _build_epmc_query(
        query,
        year_min=year_min,
        year_max=year_max,
        open_access_only=open_access_only,
        include_grey=include_grey,
    )

    params: Dict[str, Any] = {
        "query": full_query,
        "format": "json",
        "pageSize": page_size,
        "resultType": "core",
        "synonym": "false",  # disable MeSH expansion — unreliable for IAS taxa
        "cursorMark": cursor_mark,
    }

    try:
        response = requests.get(_API_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        return {"error": f"Europe PMC request failed: {e}"}
    except Exception as e:
        return {"error": f"Europe PMC search failed: {e}"}

    # Capture cursor for next page (None when results are exhausted)
    next_cursor_mark: Optional[str] = data.get("nextCursorMark") or None

    raw_articles = (
        data.get("resultList", {}).get("result") or []
    )
    results = []

    for article in raw_articles:
        doi: Optional[str] = article.get("doi") or None
        pmid: Optional[str] = article.get("pmid") or None

        # -- Resolve best available URL (free PDF > HTML > DOI > PMID abstract) --
        url, has_pdf, pdf_url = _resolve_url(article, doi)
        if not url:
            continue  # no URL at all — skip (very rare)

        domain = _extract_domain(url)

        citation_count: Optional[int] = article.get("citedByCount")

        # -- Authors --
        # Europe PMC returns authorList.author as a list of dicts with fullName or
        # lastName + firstName fields. Prefer fullName when available.
        raw_authors = (article.get("authorList") or {}).get("author") or []
        authors = []
        for a in raw_authors:
            if a.get("fullName"):
                authors.append(a["fullName"])
            elif a.get("lastName"):
                first = a.get("firstName", "")
                authors.append(f"{a['lastName']}, {first}".strip(", "))

        # All Europe PMC results are "academic" — preprints, theses, and other
        # non-journal types still come from an academic database.
        epmc_src: Optional[str] = article.get("source") or None
        content_category = "academic"

        results.append({
            "title": _clean_title(article.get("title") or ""),
            "url": url,
            "domain": domain,
            "source_api": "europe_pmc",
            "doi": doi,
            "authors": authors,
            "has_pdf": has_pdf,
            "pdf_url": pdf_url,
            "publication_year": _parse_year(article.get("pubYear")),
            "journal_name": article.get("journalTitle") or None,
            "citation_count": citation_count,
            "epmc_source": epmc_src,
            "content_category": content_category,
            "influential_citation_count": None,  # not available in Europe PMC
            "pmid": pmid,
            # internal: used by relevance filter, stripped before caching
            "_abstract": article.get("abstractText") or "",
            # search context filled in by pipeline
            "search_term_used": "",
            "full_query_used": query,
            "species_context": "",
        })

    return {"results": results, "next_cursor_mark": next_cursor_mark}


# ============================================================================
# HAYSTACK TOOL WRAPPER
# ============================================================================

from haystack.tools import Tool  # noqa: E402

europe_pmc_search_json_tool = Tool(
    name="europe_pmc_search_json",
    description=(
        "Search Europe PMC for open-access life-science and agricultural papers "
        "(MEDLINE + Agricola) and return structured JSON."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "Search query string",
        },
        "page_size": {
            "type": "integer",
            "description": "Maximum number of results to return (default: 5)",
        },
    },
    function=europe_pmc_search_json,
)

# ============================================================================
# HELPERS
# ============================================================================

def _build_epmc_query(
    raw_query: str,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    open_access_only: bool = False,
    include_grey: bool = True,
) -> str:
    """
    Transform a raw query like '"Species name" "required phrase" keyword1 keyword2'
    into a Europe PMC query where:
    - The species must appear in the title or abstract (field-scoped)
    - Additional quoted phrases must appear anywhere in the full text (AND'd)
    - Bare words are OR-grouped for recall (any one sufficient)

    Result: (TITLE:"Species name" OR ABSTRACT:"Species name")
              AND "required phrase"
              AND (keyword1 OR keyword2 OR ...)
              [AND FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD]]
              [AND OPEN_ACCESS:Y]

    Why field-scope only the species?
    Without TITLE/ABSTRACT scoping, the species name only needs to appear
    anywhere in the full text — a paper about bears mentioning salmon as prey
    will match. Scoping to title/abstract ensures the paper is *about* the species.
    Topic phrases and keywords don't need field-scoping — full-text presence is
    sufficient signal and avoids killing recall for niche species.

    Literal "OR" tokens in the raw query are stripped (artefacts from old-style
    synonym notation like '"phrase1" OR "phrase2"').
    """
    import re
    # Extract all quoted phrases and remaining bare words
    quoted_parts = re.findall(r'"[^"]*"', raw_query)
    remaining = re.sub(r'"[^"]*"', '', raw_query).strip()
    # Strip literal "OR" artefacts left over from old-style synonym notation
    keywords = [k for k in remaining.split() if k.upper() != 'OR']

    parts = []
    if quoted_parts:
        species = quoted_parts[0]  # e.g. "Oncorhynchus gorbuscha"
        parts.append(f'(TITLE:{species} OR ABSTRACT:{species})')
        # Additional quoted phrases → required in full text (AND'd, not field-scoped)
        for qp in quoted_parts[1:]:
            parts.append(qp)

    if keywords:
        keyword_clause = "(" + " OR ".join(keywords) + ")" if len(keywords) > 1 else keywords[0]
        parts.append(keyword_clause)

    # Source type filter: restrict to peer-reviewed journals when grey literature is off
    if not include_grey:
        parts.append("(SRC:MED OR SRC:PMC)")

    # Date range filter using Europe PMC's FIRST_PDATE field
    if year_min or year_max:
        lo = f"{year_min}-01-01" if year_min else "1900-01-01"
        hi = f"{year_max}-12-31" if year_max else "*"
        parts.append(f"FIRST_PDATE:[{lo} TO {hi}]")

    # Open access filter — applied at query time for server-side filtering
    if open_access_only:
        parts.append("OPEN_ACCESS:Y")

    return " AND ".join(parts)


def _resolve_url(
    article: Dict[str, Any], doi: Optional[str]
) -> tuple[Optional[str], bool, Optional[str]]:
    """
    Return (canonical_url, has_pdf, pdf_url) for an article.

    Preference order:
    1. PDF URL from fullTextUrlList (not subscription-required)
    2. HTML full-text URL from fullTextUrlList
    3. DOI landing page
    4. Europe PMC abstract page (via PMID)
    """
    pdf_url: Optional[str] = None
    html_url: Optional[str] = None

    url_list = (
        (article.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    )
    for entry in url_list:
        availability = (entry.get("availability") or "").lower()
        is_subscription = "subscription" in availability
        style = (entry.get("documentStyle") or "").lower()
        link = entry.get("url") or ""
        if not link:
            continue
        # Prefer free/open PDFs; skip subscription PDFs (DOI fallback is better)
        if style == "pdf" and pdf_url is None and not is_subscription:
            pdf_url = link
        elif style in ("html", "doi") and html_url is None and not is_subscription:
            html_url = link

    if pdf_url:
        return pdf_url, True, pdf_url
    if html_url:
        return html_url, False, None
    if doi:
        return f"https://doi.org/{doi}", False, None

    pmid = article.get("pmid")
    if pmid:
        return f"https://europepmc.org/article/MED/{pmid}", False, None

    return None, False, None


def _extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.replace("www.", "") if netloc else ""
    except Exception:
        return ""


def _parse_year(value: Any) -> Optional[int]:
    try:
        return int(value) if value else None
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    print("Europe PMC Search API Module")
