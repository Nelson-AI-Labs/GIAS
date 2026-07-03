# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
CABI Thesaurus (PoolParty) SPARQL client.

Compendium datasheet links are resolved via skos:prefLabel + cabi:compendiumDatasheetAt.

Endpoint: https://id.cabi.org/PoolParty/sparql/cabt
"""

from typing import Any, Dict

import requests

from core.utils.config_loader import get_contact_email

CABI_SPARQL_URL = "https://id.cabi.org/PoolParty/sparql/cabt"

HEADERS = {
    "User-Agent": f"GuardIAS/1.0 (contact: {get_contact_email()})",
    "Accept": "application/sparql-results+json",
}

DEFAULT_TIMEOUT = 60.0


def _sparql_escape_double_quoted_string(value: str) -> str:
    """Escape backslashes, quotes, and newlines so a value is safe inside a
    SPARQL double-quoted string literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
    )


def build_compendium_datasheet_query(scientific_name: str) -> str:
    """Build a SELECT that binds the English prefLabel to the given scientific name."""
    safe = _sparql_escape_double_quoted_string(scientific_name.strip())
    return f"""PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX cabi: <https://id.cabi.org/cabiontology/>

SELECT ?speciesName ?datasheet
WHERE {{
   VALUES ?speciesName {{ "{safe}"@en }}
   ?concept skos:prefLabel ?speciesName ;
            cabi:compendiumDatasheetAt ?datasheet .
}}
"""


def _post_sparql_json(query: str, timeout: float) -> dict[str, Any]:
    """POST a SPARQL query to the CABI endpoint and return the parsed JSON results,
    raising if the response is not the expected SPARQL-results JSON content type."""
    resp = requests.post(
        CABI_SPARQL_URL,
        data={
            "query": query,
            "format": "application/sparql-results+json",
        },
        headers=HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    ct = resp.headers.get("Content-Type", "")
    if "application/sparql-results+json" not in ct:
        raise RuntimeError(
            f"Expected application/sparql-results+json, got Content-Type: {ct!r}."
        )
    return resp.json()


def extract_datasheet_uris(payload: dict[str, Any]) -> list[str]:
    """Collect unique datasheet URIs from SPARQL JSON results, preserving order."""
    bindings = payload.get("results", {}).get("bindings", [])
    if not isinstance(bindings, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for row in bindings:
        if not isinstance(row, dict):
            continue
        cell = row.get("datasheet")
        if not isinstance(cell, dict):
            continue
        if cell.get("type") != "uri":
            continue
        uri = cell.get("value")
        if not uri or not isinstance(uri, str):
            continue
        if uri not in seen:
            seen.add(uri)
            out.append(uri)
    return out


def fetch_cabi_compendium_datasheet_urls(
    scientific_name: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[str]:
    """
    Return CABI Compendium datasheet URLs for a scientific name (English prefLabel).

    Raises requests.HTTPError / requests.RequestException / RuntimeError on failure.
    Returns an empty list when the endpoint responds but there are no bindings.
    """
    name = (scientific_name or "").strip()
    if not name:
        return []
    payload = _post_sparql_json(build_compendium_datasheet_query(name), timeout=timeout)
    return extract_datasheet_uris(payload)


# ============================================================================
# HAYSTACK PIPELINE COMPONENT
# ============================================================================

try:
    from haystack import component

    @component
    class CABIComponent:
        """
        Haystack pipeline component for CABI Thesaurus SPARQL lookups.

        Fetches Compendium datasheet URLs for a species name and persists them
        to the shared RawDataStore so the categorisation step can reference them.
        """

        def __init__(self) -> None:
            self.raw_store = None

        @component.output_types(
            cached_data=Dict[str, Any],
            cabi_data=Dict[str, Any],
            cache_status=str,
        )
        def run(self, species_name: str, raw_store=None) -> Dict[str, Any]:
            """Fetch CABI datasheet URLs for the species, persist them to raw_store,
            and report a cache_status of raw_saved, no_data, or error."""
            if raw_store is not None:
                self.raw_store = raw_store

            try:
                urls = fetch_cabi_compendium_datasheet_urls(species_name)
            except Exception as e:
                print(f"  [CABI] Error fetching datasheets for '{species_name}': {e}")
                return {"cached_data": {}, "cabi_data": {}, "cache_status": "error"}

            if not urls:
                return {"cached_data": {}, "cabi_data": {}, "cache_status": "no_data"}

            cabi_data: Dict[str, Any] = {
                "species_name": species_name,
                "datasheet_urls": urls,
                # First URL exposed as cabi_url so get_all_database_links_with_species
                # picks it up automatically (scans for {source_lower}_url pattern).
                "cabi_url": urls[0],
                "source": "CABI",
            }

            if self.raw_store is not None:
                self.raw_store.save_raw_data(species_name, "CABI", cabi_data)

            return {
                "cached_data": cabi_data,
                "cabi_data": cabi_data,
                "cache_status": "raw_saved",
            }

except ImportError:
    # Haystack not installed — component unavailable, plain fetch function still works.
    pass
