#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Tavily Search API Module
AI-powered web search: targeted queries on institutional and government sources.
One call per topic per pipeline run (1 credit). Never called per search term.
"""

import logging
import requests
from typing import Dict, List, Any, Optional
from core.utils.config_loader import get_secret

logger = logging.getLogger(__name__)

# ============================================================================
# API CONFIGURATION
# ============================================================================
TAVILY_API_KEY = get_secret('TAVILY_API_KEY')

# ============================================================================
# DOMAIN REFERENCE DATA
# ============================================================================

# Maps exact Tavily result domains to human-readable institution names.
# Used by the pipeline normaliser to populate journal_name on grey-lit cards.
_DOMAIN_TO_INSTITUTION: Dict[str, str] = {
    "easin.jrc.ec.europa.eu": "EASIN (European Commission JRC)",
    "eea.europa.eu": "European Environment Agency",
    "eur-lex.europa.eu": "EUR-Lex (EU Legislation)",
    "ec.europa.eu": "European Commission",
    "iucn.org": "IUCN",
    "cbd.int": "Convention on Biological Diversity",
    "imo.org": "International Maritime Organization",
    "ramsar.org": "Ramsar Convention",
    "nas.er.usgs.gov": "USGS Nonindigenous Aquatic Species",
    "invasivespeciesinfo.gov": "NISIC",
    "glerl.noaa.gov": "NOAA GLANSIS",
    "fws.gov": "US Fish & Wildlife Service",
    "epa.gov": "US Environmental Protection Agency",
    "doi.gov": "US Dept of the Interior",
    "dcceew.gov.au": "Australian DCCEEW",
    "agriculture.gov.au": "Australian Dept of Agriculture",
    "dfo-mpo.gc.ca": "Fisheries and Oceans Canada",
    "inspection.canada.ca": "Canadian Food Inspection Agency",
    "invasivespeciescentre.ca": "Invasive Species Centre (Canada)",
}

# Domains already covered by dedicated DCP API connectors or unsuitable as
# scientific sources. Excluded from all Tavily results to prevent duplicates.
_EXCLUDE_FROM_TAVILY: List[str] = [
    "iucn.org",                 # connected via IUCN DCP API
    "easin.jrc.ec.europa.eu",   # connected via EASIN DCP API
    "gbif.org",                 # connected via GBIF DCP API
    "marinespecies.org",        # connected via WRiMS DCP API
    "corpi.ku.lt",              # connected via AquaNIS DCP API
    "wikipedia.org",            # not accepted as a scientific source
]

# include_domains is intentionally empty for all topics.
# Experiments showed domain restriction consistently produced lower scores and
# missed species-specific documents that open-web searches returned at 1.00.
# Steering is done via query signals; unwanted domains are blocked via
# _EXCLUDE_FROM_TAVILY + post-processing in pipeline.py.
_GREY_LIT_DOMAINS: Dict[str, List[str]] = {}

# Document-type query signals per topic.
# These are document-oriented phrases, not academic search terms.
# Targets the language used in government reports, management plans, and
# institutional web content — what Tavily can reach and academic APIs cannot.
_TOPIC_QUERY_SIGNALS: Dict[str, str] = {
    "management_biosecurity": "management plan OR action plan OR regulation OR eradication guidance",
    "detection_monitoring": "surveillance protocol OR monitoring programme OR detection methodology",
    "introduction_pathways": "pathway management OR ballast water regulation OR biosecurity guidance",
    "impacts": "impact assessment OR economic cost OR damage report invasive",
    "distribution_and_status": "species status report OR distribution assessment OR occurrence database",
    "biological_traits": "biology ecology growth reproduction physiology report",
    "habitat_ecology": "habitat assessment OR environmental tolerance OR ecology report invasive",
    "species_interactions": "predator prey interaction OR biological control OR food web report invasive",
    "taxonomic_identity": "species identification guide OR taxonomic key OR diagnostic field guide",
}

# ============================================================================
# QUERY BUILDER
# ============================================================================

def build_web_search_query(species_name: str, research_topic: str) -> str:
    """
    Build a document-oriented web search query for a given species and topic.

    Unlike academic search strings (designed for bibliographic indexes), this
    query targets the kind of language used in government reports, management
    plans, and institutional documents — the content that Tavily can reach and
    academic APIs cannot.

    Args:
        species_name: Species name (e.g. "Dreissena polymorpha")
        research_topic: Topic key (e.g. "management_biosecurity")

    Returns:
        Query string ready to pass to tavily_search_json()
    """
    signal = _TOPIC_QUERY_SIGNALS.get(
        research_topic, "invasive species report OR fact sheet"
    )
    return f'"{species_name}" {signal}'


# Keep legacy alias so any existing callers don't break
build_grey_lit_query = build_web_search_query

# ============================================================================
# CORE TAVILY FUNCTION
# ============================================================================

def tavily_search_json(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = False,
    include_domains: Optional[List[str]] = None,
    exclude_domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Search the web using Tavily API and return raw JSON response.

    One call per topic pipeline run (1 credit). Never call this per search
    term — use build_web_search_query() to build a single purpose-built query.

    Args:
        query: Search query string (use build_web_search_query() to construct)
        max_results: Number of results (default 5 = 1 credit at basic depth)
        search_depth: "basic" (1 credit) or "advanced" (2 credits). Always use basic.
        include_answer: Whether to include AI-generated answer. Not useful for pipeline.
        include_domains: List of exact domain strings to restrict results to.
                        Use _GREY_LIT_DOMAINS[research_topic] for topic-appropriate sources.
        exclude_domains: List of exact domain strings to block from results.
                        Pass _EXCLUDE_FROM_TAVILY to filter DCP-connected databases.

    Returns:
        Raw JSON response with source_api="tavily" tagged on each result, or
        {"error": "<reason>", "results": []} on any failure — never raises.

    Error values:
        "no_api_key"        — TAVILY_API_KEY not configured
        "credits_exhausted" — 429 with credit exhaustion message
        "rate_limited"      — 429 rate limit (retry later)
        "timeout"           — request timed out
        "<message>"         — any other exception
    """
    if not TAVILY_API_KEY:
        return {"error": "no_api_key", "results": []}

    url = "https://api.tavily.com/search"
    payload: Dict[str, Any] = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": search_depth,
        "include_answer": include_answer,
        "include_raw_content": False,
        "include_usage": True,
        "max_results": max_results,
    }
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains

    try:
        response = requests.post(url, json=payload, timeout=15)

        if response.status_code == 429:
            try:
                body = response.json()
            except Exception:
                body = {}
            body_str = str(body).lower()
            if "credit" in body_str or "quota" in body_str or "limit" in body_str:
                logger.warning("Tavily credits exhausted — grey literature skipped")
                return {"error": "credits_exhausted", "results": []}
            logger.warning("Tavily rate limited — grey literature skipped")
            return {"error": "rate_limited", "results": []}

        response.raise_for_status()
        data = response.json()

        for result in data.get("results", []):
            result["source_api"] = "tavily"

        usage = data.get("usage", {})
        if usage:
            logger.debug("Tavily call used %s credit(s)", usage.get("credits", "?"))

        return data

    except requests.exceptions.Timeout:
        logger.warning("Tavily request timed out")
        return {"error": "timeout", "results": []}
    except requests.exceptions.RequestException as e:
        logger.warning("Tavily request failed: %s", e)
        return {"error": str(e), "results": []}
    except Exception as e:
        logger.warning("Tavily search failed: %s", e)
        return {"error": str(e), "results": []}

# ============================================================================
# HAYSTACK TOOL WRAPPERS
# ============================================================================

from haystack.tools import Tool

tavily_search_json_tool = Tool(
    name="tavily_search_json",
    description="AI-powered web search on institutional sources using Tavily API. One call per topic — use build_web_search_query() to construct the query.",
    parameters={
        "query": {"type": "string", "description": "Search query string (from build_web_search_query)"},
        "max_results": {"type": "integer", "description": "Number of results (default 5, max 5 for 1 credit)"},
        "search_depth": {"type": "string", "description": "'basic' (1 credit) or 'advanced' (2 credits). Use basic."},
        "include_domains": {"type": "array", "items": {"type": "string"}, "description": "Exact domain strings to restrict results to"},
        "exclude_domains": {"type": "array", "items": {"type": "string"}, "description": "Exact domain strings to exclude from results"},
    },
    function=tavily_search_json,
)

if __name__ == "__main__":
    print("Tavily Search API Module")
    print("Run 'python test_tools.py' for comprehensive testing")
