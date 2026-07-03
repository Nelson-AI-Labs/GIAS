#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Resolver Service

Resolves a user's species input into a validated scientific name and a complete,
authoritative synonym list sourced from GBIF and WoRMS taxonomic databases.

Runs once per research session (keyed by universal_id) and caches the result.
All subsequent calls within the same session load from cache — no API or LLM calls made.

The resolved data is the single source of truth for species identity across all pipelines:
- data_aggregation: uses synonym_list as query targets for all database APIs
- extraction: uses synonym_list to identify all valid name variants in documents
- report_generation: uses synonym_list for source traceability (which name found what)

Cache location:
    cache/{session_id}/species_context/{universal_id}_species_resolution.json

Usage:
    from core.services.species_resolver import resolve_species

    resolution = resolve_species("Red Swamp Crayfish", universal_id="abc123", session_id="xyz")
    # {
    #   "corrected_name": "Procambarus clarkii",
    #   "synonym_list": ["Procambarus clarkii", "Cambarus clarkii", "Astacus clarkii"],
    #   "gbif_key": 2227868,
    #   "confidence": "high",
    #   "original_input": "Red Swamp Crayfish",
    #   "synonym_sources_failed": []
    # }
"""

import json
from typing import Dict, List, Any, Optional
from core.utils.cache_manager import get_cache_manager


def resolve_species(
    user_input: str,
    universal_id: str,
    session_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolve a species input to a validated name and authoritative synonym list.

    Loads from session cache if already resolved for this universal_id.
    Otherwise runs the full resolution pipeline and caches the result.

    Args:
        user_input: Raw user input (common name, misspelled name, or scientific name)
        universal_id: Universal species ID used for cache file naming
        session_id: Explicit session ID for cache path (pass from main thread in Streamlit)

    Returns:
        Dict with:
            - corrected_name: Accepted scientific name in Latin binomial format
            - synonym_list: [corrected_name] + all synonyms from GBIF and WoRMS (deduplicated)
            - gbif_key: GBIF usageKey integer
            - confidence: "high", "medium", or "low"
            - original_input: The raw user input
            - synonym_sources_failed: list of sources whose synonym fetch errored
              (empty = synonym_list is complete; non-empty = it may be incomplete)
    """
    cache_manager = get_cache_manager(session_id=session_id)
    cache_dir = cache_manager.species_context_dir()
    cache_file = cache_dir / f"{universal_id}_species_resolution.json"

    if cache_file.exists():
        print(f"  [species_resolver] Loading from cache: {cache_file.name}")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    print(f"  [species_resolver] Resolving '{user_input}'...")
    result = _build_resolution(user_input)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    return result


def _build_resolution(user_input: str) -> Dict[str, Any]:
    """
    Run the full species resolution pipeline:
    1. Validate/correct name with Mistral AI
    2. Get GBIF usageKey
    3. Fetch synonyms from GBIF and WoRMS
    4. Clean synonyms (strip author annotations, discard non-binomial strings)
    5. Build deduplicated synonym list with corrected_name first

    Args:
        user_input: Raw user input string

    Returns:
        Resolved species dict (same shape as resolve_species return value)
    """
    # Step 1: Validate and correct the species name
    from functionalities.data_aggregation.agents.species_name_validator_agent import SpeciesNameValidatorAgent
    validator = SpeciesNameValidatorAgent()
    validation = validator.run(user_input=user_input)
    corrected_name = validation["corrected_name"]
    confidence = validation.get("confidence", "low")
    print(f"  Corrected name: '{corrected_name}' (confidence: {confidence})")

    # Step 2: Get GBIF usageKey — required for GBIF synonym lookup
    from functionalities.data_aggregation.api.gbif import _get_gbif_species_match, get_species_synonyms as get_gbif_synonyms
    gbif_match = _get_gbif_species_match(corrected_name)
    if not gbif_match or not gbif_match.get("usageKey"):
        raise ValueError(f"Could not find '{corrected_name}' in GBIF database")
    gbif_key = gbif_match["usageKey"]
    print(f"  GBIF key: {gbif_key}")

    # Step 3: Fetch synonyms from GBIF and WoRMS
    raw_synonyms, sources_failed = _fetch_db_synonyms(corrected_name, gbif_key, get_gbif_synonyms)

    # Step 4: Clean synonyms — strip author strings and discard non-latin-binomial entries
    if raw_synonyms:
        from functionalities.data_aggregation.agents.synonym_cleaner_agent import SynonymCleanerAgent
        print(f"  Cleaning {len(raw_synonyms)} raw synonyms...")
        cleaned_synonyms = SynonymCleanerAgent().run(raw_synonyms=raw_synonyms)["cleaned_synonyms"]
    else:
        cleaned_synonyms = []

    # Step 5: Build deduplicated list — corrected name is always first
    synonym_list = [corrected_name]
    seen = {corrected_name.lower().strip()}
    for syn in cleaned_synonyms:
        key = syn.lower().strip()
        if key not in seen:
            seen.add(key)
            synonym_list.append(syn)

    print(f"  Final synonym list ({len(synonym_list)} names): {synonym_list}")
    if sources_failed:
        print(f"  ⚠ Synonym list may be incomplete — fetch failed for: {sources_failed}")

    return {
        "corrected_name": corrected_name,
        "synonym_list": synonym_list,
        "gbif_key": gbif_key,
        "confidence": confidence,
        "original_input": user_input,
        # Sources whose synonym fetch raised an error (network/API failure). Empty list
        # means every source was reached — so an empty synonym_list is then a genuine
        # "this species has no synonyms", not a silent outage. Non-empty means the
        # synonym_list may be incomplete.
        "synonym_sources_failed": sources_failed
    }


def _fetch_db_synonyms(corrected_name: str, gbif_key: int, get_gbif_synonyms) -> tuple:
    """
    Fetch raw synonyms from GBIF and WoRMS. Failures are non-fatal but reported.

    A source is only recorded as failed when its fetch raises an error (network/API
    failure). A source legitimately returning no synonyms — or WoRMS having no record
    for a non-marine species — is normal, not a failure.

    Args:
        corrected_name: Validated scientific name for WoRMS lookup
        gbif_key: GBIF usageKey for GBIF synonym lookup
        get_gbif_synonyms: The GBIF synonym function (passed to avoid re-import)

    Returns:
        Tuple of:
        - raw_synonyms: combined raw synonym strings from both sources (may contain authors)
        - sources_failed: list of "<Source>: <error>" strings for sources whose fetch
          raised. Empty when every source was reached successfully.
    """
    from functionalities.data_aggregation.api.wrims import get_aphia_id, get_species_synonyms as get_worms_synonyms

    raw_synonyms = []
    sources_failed = []

    # GBIF synonyms
    try:
        gbif_synonyms = get_gbif_synonyms(gbif_key)
        if gbif_synonyms:
            print(f"  GBIF: {len(gbif_synonyms)} synonyms")
            raw_synonyms.extend(gbif_synonyms)
        else:
            print("  GBIF: no synonyms returned")
    except Exception as e:
        print(f"  ⚠ GBIF synonym fetch failed: {e}")
        sources_failed.append(f"GBIF: {e}")

    # WoRMS synonyms
    try:
        aphia_id = get_aphia_id(corrected_name)
        if aphia_id:
            print(f"  WoRMS AphiaID: {aphia_id}")
            worms_result = get_worms_synonyms(aphia_id)
            worms_synonyms = [
                entry["scientificname"]
                for entry in worms_result.get("synonyms", [])
                if entry.get("scientificname")
            ]
            if worms_synonyms:
                print(f"  WoRMS: {len(worms_synonyms)} synonyms")
                raw_synonyms.extend(worms_synonyms)
            else:
                print("  WoRMS: no synonyms returned")
        else:
            # Non-marine species have no WoRMS record — expected, not a failure.
            print(f"  WoRMS: no AphiaID for '{corrected_name}' (non-marine species)")
    except Exception as e:
        print(f"  ⚠ WoRMS synonym fetch failed: {e}")
        sources_failed.append(f"WoRMS: {e}")

    return raw_synonyms, sources_failed
