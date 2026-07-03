#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Aquatic Species Source Finding Pipeline
A Haystack Pipeline-based approach for sequential source discovery workflow.

APIs run per search term:
  - Semantic Scholar:  broad academic coverage with citation metrics
  - Europe PMC:        life sciences + USDA agricultural research
  - OpenAlex:          250M+ works, open-access focused, topic-filtered
  - DOAJ:              AIS-specialist journals (management-core topics only)
  - Google Scholar:    opt-in via include_google_scholar=True (2 calls/run cap)
  - Tavily:            grey literature, institutional reports, government sites
"""

import json
import logging
import warnings
from datetime import datetime
from typing import List, Dict, Any, Optional

# Haystack imports
from haystack import component, Pipeline

# Import all search functions
from functionalities.source_finding.api.tavily_search import (
    tavily_search_json,
    build_grey_lit_query,
    _GREY_LIT_DOMAINS,
    _DOMAIN_TO_INSTITUTION,
    _EXCLUDE_FROM_TAVILY,
)
from functionalities.source_finding.api.semantic_scholar_search import semantic_scholar_search_json, _extract_domain
from functionalities.source_finding.api.europe_pmc_search import europe_pmc_search_json
from functionalities.source_finding.api.openalex_search import openalex_search_json
from functionalities.source_finding.api.doaj_search import doaj_search_json
from functionalities.source_finding.api.google_scholar_search import google_scholar_search_json
from functionalities.source_finding.agents.relevance_filter import score_relevance
from core.registries.topic_registry import StandardTopicRegistry

# Import session-aware cache manager
from core.utils.cache_manager import get_search_results_dir

logger = logging.getLogger(__name__)


# ============================================================================
# COMPONENT: SEARCH EXECUTOR
# ============================================================================

@component
class SearchExecutorComponent:
    """
    Pipeline component that executes search terms across all configured APIs
    and caches results per API.

    APIs: Semantic Scholar, Europe PMC, OpenAlex, DOAJ (management-core only),
    Google Scholar (opt-in, 2-call cap), Tavily (grey literature, disabled by default).

    Results are deduplicated by DOI; papers found by multiple APIs have their
    source_api field merged into a list (e.g. ["semantic_scholar", "openalex"]).
    """

    def __init__(self, enable_caching: bool = True):
        """`enable_caching` toggles reuse of previously discovered sources across runs."""
        self.enable_caching = enable_caching

    # ------------------------------------------------------------------
    # Output type signature
    # ------------------------------------------------------------------
    @component.output_types(
        search_results=List[Dict[str, Any]],
        total_results=int,
        api_breakdown=Dict[str, Any],
    )
    def run(
        self,
        search_terms: List[str],
        species_name: str,
        research_topic: str = "",
        search_filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute search terms across all three APIs, deduplicate, and cache.

        Args:
            search_terms:    List of search terms to execute
            species_name:    Species name for context and query construction
            research_topic:  Research topic for metadata/caching
            search_filters:  Optional filter dict with keys:
                               year_min, year_max, min_citations,
                               open_access_only, include_grey_literature

        Returns:
            Dict with search_results, total_results, cache_filepath, api_breakdown
        """
        filters = search_filters or {}
        year_min = filters.get("year_min")
        year_max = filters.get("year_max")
        open_access_only = filters.get("open_access_only", False)
        include_grey = filters.get("include_grey_literature", True)

        ss_results: List[Dict[str, Any]] = []
        pmc_results: List[Dict[str, Any]] = []
        tv_results: List[Dict[str, Any]] = []
        oa_results: List[Dict[str, Any]] = []
        doaj_results: List[Dict[str, Any]] = []
        gs_results: List[Dict[str, Any]] = []

        # Resolve topic priority tier for DOAJ guard (management-core only)
        topic_def = StandardTopicRegistry.get_topic(research_topic)
        is_management_core = topic_def and getattr(topic_def, "priority_tier", "") == "management_core"

        # Google Scholar: always runs, capped at first 2 search terms per run
        # to protect the SerpAPI free quota (100 credits/month).
        gs_search_count = 0
        _GS_TERM_CAP = 2
        _GS_RESULT_CAP = 5

        for search_term in search_terms:
            full_query = f'"{species_name}" {search_term}'

            # -- Semantic Scholar --
            try:
                data = semantic_scholar_search_json(
                    query=full_query,
                    research_topic=research_topic,
                    year_min=year_min,
                    year_max=year_max,
                    include_grey=include_grey,
                    limit=10,
                )
                if "error" not in data:
                    for r in data.get("results", []):
                        r["search_term_used"] = search_term
                        r["full_query_used"] = full_query
                        r["species_context"] = species_name
                        ss_results.append(r)
            except Exception as e:
                logger.warning("Semantic Scholar failed for '%s': %s", search_term, e)

            # -- Europe PMC --
            try:
                data = europe_pmc_search_json(
                    query=full_query,
                    page_size=10,
                    year_min=year_min,
                    year_max=year_max,
                    open_access_only=open_access_only,
                    include_grey=include_grey,
                )
                if "error" not in data:
                    for r in data.get("results", []):
                        r["search_term_used"] = search_term
                        r["full_query_used"] = full_query
                        r["species_context"] = species_name
                        pmc_results.append(r)
            except Exception as e:
                logger.warning("Europe PMC failed for '%s': %s", search_term, e)

            # -- OpenAlex --
            try:
                data = openalex_search_json(
                    query=full_query,
                    research_topic=research_topic,
                    year_min=year_min,
                    year_max=year_max,
                    limit=10,
                )
                for r in data.get("results", []):
                    r["search_term_used"] = search_term
                    r["full_query_used"] = full_query
                    r["species_context"] = species_name
                    oa_results.append(r)
            except Exception as e:
                logger.warning("OpenAlex failed for '%s': %s", search_term, e)

            # -- DOAJ (management-core topics only) --
            if is_management_core:
                try:
                    data = doaj_search_json(
                        query=full_query,
                        research_topic=research_topic,
                        year_min=year_min,
                        year_max=year_max,
                        limit=10,
                    )
                    for r in data.get("results", []):
                        r["search_term_used"] = search_term
                        r["full_query_used"] = full_query
                        r["species_context"] = species_name
                        doaj_results.append(r)
                except Exception as e:
                    logger.warning("DOAJ failed for '%s': %s", search_term, e)

            # -- Google Scholar (always on, capped at first 2 search terms to protect quota) --
            if gs_search_count < _GS_TERM_CAP:
                try:
                    data = google_scholar_search_json(
                        query=full_query,
                        research_topic=research_topic,
                        year_min=year_min,
                        year_max=year_max,
                        limit=_GS_RESULT_CAP,
                    )
                    gs_search_count += 1
                    for r in data.get("results", []):
                        r["search_term_used"] = search_term
                        r["full_query_used"] = full_query
                        r["species_context"] = species_name
                        gs_results.append(r)
                    logger.info(
                        "Google Scholar: %d results (credit %d/%d used this run)",
                        len(data.get("results", [])), gs_search_count, _GS_TERM_CAP,
                    )
                except Exception as e:
                    logger.warning("Google Scholar failed for '%s': %s", search_term, e)


        # -- Tavily: one call per topic run (1 credit), never per search term --
        try:
            grey_query = build_grey_lit_query(species_name, research_topic)
            domains = _GREY_LIT_DOMAINS.get(research_topic, [])
            data = tavily_search_json(
                query=grey_query,
                max_results=5,
                search_depth="basic",
                include_answer=False,
                include_domains=domains if domains else None,
                exclude_domains=_EXCLUDE_FROM_TAVILY,
            )
            if "error" not in data:
                for r in data.get("results", []):
                    enhanced = self._normalise_tavily_result(r, grey_query, grey_query, species_name)
                    tv_results.append(enhanced)
            elif data.get("error") == "credits_exhausted":
                logger.warning("Tavily credits exhausted — grey literature skipped for this run")

            # Post-process: drop any results from excluded domains.
            # exclude_domains in the API call is best-effort only — Tavily does
            # not guarantee it, so we filter here as a reliable safety net.
            tv_results = [
                r for r in tv_results
                if r.get("domain") not in _EXCLUDE_FROM_TAVILY
            ]

            # Title-based dedup: the same paper can appear from multiple hosts
            # (e.g., publisher site + ResearchGate mirror). Tavily results have
            # doi=None so URL-based dedup misses these. Results arrive ordered
            # by score, so keeping the first occurrence keeps the best-scored one.
            seen_titles: set = set()
            deduped_tv: list = []
            for r in tv_results:
                norm_title = r.get("title", "").strip().lower().rstrip(".")
                if norm_title and norm_title in seen_titles:
                    continue
                seen_titles.add(norm_title)
                deduped_tv.append(r)
            tv_results = deduped_tv
        except Exception as e:
            logger.warning("Tavily failed: %s", e)

        # Initial-run caps per API:
        #   Free academic APIs (SS / PMC / OpenAlex / DOAJ): top-4 by citation count.
        #   Fetch stays at limit=10/page_size=10 per term so the citation sort has
        #   a wider pool to pick the best 4 from; capping here keeps the initial
        #   result set to ~22–24 total per topic.
        #   Credit-metered (GS / Tavily): capped at 5. They run once per topic and
        #   are never re-queried by "Show more sources".
        _FREE_API_CAP = 4
        _CREDIT_API_CAP = 5

        # -- Deduplicate SS, apply user filters, then score relevance --
        ss_results = _deduplicate(ss_results)
        ss_results = _apply_filters(ss_results, filters)
        ss_results.sort(key=lambda r: r.get("citation_count") or 0, reverse=True)
        ss_results = ss_results[:_FREE_API_CAP]
        ss_results = score_relevance(ss_results, species_name, research_topic)

        # -- Deduplicate PMC, apply user filters, then score relevance --
        pmc_results = _deduplicate(pmc_results)
        pmc_results = _apply_filters(pmc_results, filters)
        pmc_results.sort(key=lambda r: r.get("citation_count") or 0, reverse=True)
        pmc_results = pmc_results[:_FREE_API_CAP]
        pmc_results = score_relevance(pmc_results, species_name, research_topic)

        # -- Deduplicate OpenAlex, apply user filters, then score relevance --
        oa_results = _deduplicate(oa_results)
        oa_results = _apply_filters(oa_results, filters)
        oa_results.sort(key=lambda r: r.get("citation_count") or 0, reverse=True)
        oa_results = oa_results[:_FREE_API_CAP]
        oa_results = score_relevance(oa_results, species_name, research_topic)

        # -- Deduplicate DOAJ, apply user filters, then score relevance --
        doaj_results = _deduplicate(doaj_results)
        doaj_results = _apply_filters(doaj_results, filters)
        doaj_results = doaj_results[:_FREE_API_CAP]
        doaj_results = score_relevance(doaj_results, species_name, research_topic)

        # -- Deduplicate Google Scholar, apply user filters, then score relevance --
        gs_results = _deduplicate(gs_results)
        gs_results = _apply_filters(gs_results, filters)
        gs_results = gs_results[:_CREDIT_API_CAP]
        gs_results = score_relevance(gs_results, species_name, research_topic)

        # -- Score Tavily grey literature results --
        if tv_results:
            tv_results = score_relevance(tv_results, species_name, research_topic)

        # -- E6.3: Management relevance sort (management-core topics only) --
        # After relevance scoring, re-sort each API pool so management-applicable
        # papers bubble to the top. This ensures the highest-signal papers appear
        # first in the cached results and in the source-management UI.
        # Sort key: (is_low_confidence, not management_applicable) — False < True,
        # so confident management papers rank first; low-confidence/ecology-only last.
        if is_management_core:
            def _mgmt_sort_key(r: Dict[str, Any]) -> tuple:
                low_conf = r.get("is_low_confidence", False)
                not_mgmt = not r.get("management_applicable", True)
                return (low_conf, not_mgmt)
            for pool in [ss_results, pmc_results, oa_results, doaj_results, gs_results]:
                pool.sort(key=_mgmt_sort_key)

        # -- Deduplicate and merge all APIs --
        all_results = _deduplicate(ss_results + pmc_results + oa_results + doaj_results + gs_results + tv_results)

        # -- Caching (abstract already stripped by score_relevance) --
        api_cache_paths = self._cache_results(
            ss_results, pmc_results, tv_results, oa_results, doaj_results, gs_results,
            species_name, research_topic, search_terms,
        )

        api_breakdown = {
            "semantic_scholar": {
                "count": len(ss_results),
                "cache_filepath": api_cache_paths.get("semantic_scholar", ""),
            },
            "europe_pmc": {
                "count": len(pmc_results),
                "cache_filepath": api_cache_paths.get("europe_pmc", ""),
            },
            "openalex": {
                "count": len(oa_results),
                "cache_filepath": api_cache_paths.get("openalex", ""),
            },
            "doaj": {
                "count": len(doaj_results),
                "cache_filepath": api_cache_paths.get("doaj", ""),
            },
            "google_scholar": {
                "count": len(gs_results),
                "cache_filepath": api_cache_paths.get("google_scholar", ""),
            },
            "tavily": {
                "count": len(tv_results),
                "cache_filepath": api_cache_paths.get("tavily", ""),
            },
        }

        return {
            "search_results": all_results,
            "total_results": len(all_results),
            "api_breakdown": api_breakdown,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalise_tavily_result(
        self,
        r: Dict[str, Any],
        search_term: str,
        full_query: str,
        species_name: str,
    ) -> Dict[str, Any]:
        """Convert a raw Tavily result into the standardised schema."""
        domain = _extract_domain(r.get("url", ""))
        return {
            "title": r.get("title") or "",
            "url": r.get("url") or "",
            "domain": domain,
            "score": r.get("score") or 0.0,
            "source_api": "tavily",
            "doi": None,
            "has_pdf": False,
            "pdf_url": None,
            "publication_year": None,
            "journal_name": _DOMAIN_TO_INSTITUTION.get(domain),  # institution name
            "citation_count": None,
            "content_category": "web_search",
            "_abstract": r.get("content") or "",  # stripped after relevance scoring
            "search_term_used": search_term,
            "full_query_used": full_query,
            "species_context": species_name,
        }

    def _cache_results(
        self,
        ss_results: List[Dict[str, Any]],
        pmc_results: List[Dict[str, Any]],
        tv_results: List[Dict[str, Any]],
        oa_results: List[Dict[str, Any]],
        doaj_results: List[Dict[str, Any]],
        gs_results: List[Dict[str, Any]],
        species_name: str,
        research_topic: str,
        search_terms: List[str],
    ) -> Dict[str, str]:
        """Write per-API cache files into subdirectories and return {api: path}."""
        if not self.enable_caching:
            return {}

        api_cache_paths: Dict[str, str] = {}
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_species = species_name.replace(" ", "_").replace(".", "")

        try:
            base_dir = get_search_results_dir()

            api_data = {
                "semantic_scholar": ss_results,
                "europe_pmc": pmc_results,
                "openalex": oa_results,
                "doaj": doaj_results,
                "google_scholar": gs_results,
                "tavily": tv_results,
            }

            for api_name, results in api_data.items():
                if not results:
                    continue
                api_dir = base_dir / api_name
                api_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{api_name}_search_results_{safe_species}_{timestamp}.json"
                filepath = str(api_dir / filename)
                _write_cache_file(
                    filepath,
                    species=species_name,
                    research_topic=research_topic,
                    search_terms=search_terms,
                    api=api_name,
                    results=results,
                )
                api_cache_paths[api_name] = filepath

        except Exception as e:
            logger.warning("Caching failed: %s", e)

        return api_cache_paths


# ============================================================================
# FILTER HELPERS
# ============================================================================

def _apply_filters(results: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Post-fetch filter: discard results that don't meet user-specified criteria.

    Rules:
    - min_citations: papers with citation_count < threshold are dropped.
      Papers with no citation data (None) always pass — never penalise new work.
    - open_access_only: papers without a free PDF (has_pdf=False) are dropped.
      Intended for academic APIs only; Tavily results bypass this entirely.
    """
    min_cit = filters.get("min_citations", 0)
    open_only = filters.get("open_access_only", False)

    out = []
    for r in results:
        if min_cit > 0:
            cit = r.get("citation_count")
            if cit is not None and cit < min_cit:
                continue
        if open_only and not r.get("has_pdf", False):
            continue
        out.append(r)
    return out


# ============================================================================
# DEDUPLICATION
# ============================================================================

def _deduplicate(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate results by DOI, then by URL for no-DOI entries.

    - Same DOI across multiple APIs/search terms: merge into one entry, accumulate source_api.
    - No DOI: deduplicate by URL instead (handles SS papers returned by multiple search terms).
    - No DOI and no URL: always kept (rare edge case).
    """
    seen_doi: Dict[str, Dict[str, Any]] = {}
    seen_url: Dict[str, Dict[str, Any]] = {}

    def _merge_api(existing: Dict[str, Any], incoming: Dict[str, Any]) -> None:
        """Accumulate source_api from incoming into existing."""
        api = incoming.get("source_api")
        new_apis = [api] if isinstance(api, str) else (api or [])
        for a in new_apis:
            if a not in existing["source_api"]:
                existing["source_api"].append(a)

    def _to_list_entry(result: Dict[str, Any]) -> Dict[str, Any]:
        entry = result.copy()
        api = entry.get("source_api")
        entry["source_api"] = [api] if isinstance(api, str) else (api or [])
        return entry

    for result in results:
        doi = result.get("doi")
        url = result.get("url") or ""

        if doi:
            if doi not in seen_doi:
                seen_doi[doi] = _to_list_entry(result)
            else:
                _merge_api(seen_doi[doi], result)
        elif url:
            if url not in seen_url:
                seen_url[url] = _to_list_entry(result)
            else:
                _merge_api(seen_url[url], result)
        else:
            # No DOI, no URL — keep as-is (shouldn't normally occur)
            seen_url[id(result)] = _to_list_entry(result)

    return list(seen_doi.values()) + list(seen_url.values())


# ============================================================================
# CACHE HELPERS
# ============================================================================

def _write_cache_file(
    filepath: str,
    *,
    species: str,
    research_topic: str,
    search_terms: List[str],
    api: str,
    results: List[Dict[str, Any]],
) -> None:
    cache_data = {
        "species": species,
        "research_topic": research_topic,
        "search_terms": search_terms,
        "api": api,
        "timestamp": datetime.now().isoformat(),
        "total_results": len(results),
        "results": results,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)


# ============================================================================
# PIPELINE CONSTRUCTION
# ============================================================================

def create_source_finding_pipeline(enable_caching: bool = True) -> Pipeline:
    """
    Create and configure the source finding pipeline.

    Pipeline flow: Search Terms → [Semantic Scholar + Europe PMC + Tavily] → Deduplicated Results
    Search terms are provided externally (from registry or AI agent).

    Returns:
        Configured Pipeline object ready for execution
    """
    pipeline = Pipeline()
    pipeline.add_component(
        "search_executor", SearchExecutorComponent(enable_caching=enable_caching)
    )
    return pipeline


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def run_source_finding_pipeline(
    research_topic: str,
    species_name: str,
    search_terms: Optional[List[str]] = None,
    enable_caching: bool = True,
    search_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to run the source finding pipeline with predefined search terms.

    For anchor topics: Search terms should come from StandardTopicRegistry
    For custom topics:  Search terms should come from SearchTermGeneratorAgent (CTS)

    Args:
        research_topic:  Research focus area (for context and caching)
        species_name:    Scientific name of the species (required)
        search_terms:    List of search terms to execute (required)
        enable_caching:  Whether to enable result caching
        search_filters:  Optional filter dict with keys:
                           year_min, year_max, min_citations,
                           open_access_only, include_grey_literature

    Returns:
        Dictionary containing pipeline results with search_results, total_results,
        cache_filepath, and api_breakdown.
    """
    if not search_terms:
        raise ValueError(
            "search_terms must be provided. "
            "Use StandardTopicRegistry.get_search_terms() for anchor topics "
            "or SearchTermGeneratorAgent for custom topics."
        )

    pipeline = create_source_finding_pipeline(enable_caching=enable_caching)

    result = pipeline.run({
        "search_executor": {
            "search_terms": search_terms,
            "species_name": species_name,
            "research_topic": research_topic,
            "search_filters": search_filters or {},
        }
    })

    return result
