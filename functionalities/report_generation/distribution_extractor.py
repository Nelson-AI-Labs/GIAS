#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Distribution Table Extractor Component
========================================

Haystack component that sits between DataCleanerComponent and the narrative
generator. When distribution_and_status is in the cleaned data, it:

1. Extracts the distribution_records field
2. Deduplicates records by (locality, establishment_status, establishment_means)
3. Emits structured rows {locality, status, means, sources}
4. Returns the remaining cleaned data (distribution_records removed so the
   narrative generator doesn't render it a second time)

The structured rows feed the report's occurrence-records appendix table.
"""

from typing import Dict, Any, List, Set
from haystack import component

# E3.4: Continent and supra-national region names that add no value at the
# country-level distribution table. "Formosa" is the pre-1945 name for Taiwan;
# "GE" is Georgia (not Germany) — these are ISO/GBIF artefacts.
_INTERNAL_SOURCES: Set[str] = {'AI-normalization', 'Unknown', 'Research Source'}

def _add_provenance(provenance: Dict[str, list], rec: Dict[str, Any]) -> None:
    """Accumulate where a datapoint came from as {database: [contributing datasets]}.

    GBIF is an aggregator: its records carry ``database='GBIF'`` plus a ``source``
    naming the contributing checklist that asserted the record (e.g. "Catalogue of
    Life"). Direct connectors (WRiMS, EASIN, CABI) have no separate dataset — the
    ``source`` *is* the database, so it nests under itself with no sub-dataset.
    """
    src = (rec.get("source") or "").strip()
    database = (rec.get("database") or "").strip() or src
    if not database or database in _INTERNAL_SOURCES:
        return
    datasets = provenance.setdefault(database, [])
    if src and src != database and src not in _INTERNAL_SOURCES and src not in datasets:
        datasets.append(src)


def _format_provenance(provenance: Dict[str, list]) -> List[Dict[str, str]]:
    """Render provenance as structured source chips: [{key, detail}].

    ``key`` is the database name (so the template can link it to its bibliography
    entry via src_chip); ``detail`` is the contributing dataset label, kept
    separate so a verbose (often non-English) title reads as a dataset citation,
    not stray data. Databases with no sub-dataset carry an empty detail.
    """
    out: List[Dict[str, str]] = []
    for database, datasets in provenance.items():
        if not datasets:
            detail = ""
        elif len(datasets) == 1:
            detail = f"dataset: {datasets[0]}"
        else:
            detail = f"datasets: {'; '.join(datasets)}"
        out.append({"key": database, "detail": detail})
    return out


_CONTINENT_BLOCKLIST: Set[str] = {
    "Africa", "Oceania", "North America", "Middle America", "Caribbean",
    "South America", "Central America", "Asia", "Europe", "Antarctica",
    "Europe & Northern Asia (excluding China)",
    "Formosa",  # outdated name for Taiwan
    # Biogeographic realms — too coarse for a country-level table, same as
    # continents. GBIF checklists (e.g. "Freshwater Animal Diversity Assessment")
    # list species under these. Exact-string, render-time match like the rest.
    "Neotropical", "Palearctic", "Nearctic", "Afrotropical",
    "Indomalayan", "Australasian", "Oceanian", "Antarctic",
}


@component
class DistributionTableExtractor:
    """
    Extracts distribution_records from cleaned data and renders a markdown table.

    Inputs:
        cleaned_data: Output of DataCleanerComponent — {category: {field: [{fact, sources, agreement}]}}

    Outputs:
        remaining_data: cleaned_data with distribution_records removed from distribution_and_status
        distribution_records: list of {locality, status, means, sources} rows, or [] if none
    """

    def __init__(self):
        pass

    @component.output_types(
        remaining_data=Dict[str, Any],
        distribution_records=List[Dict[str, Any]]
    )
    def run(self, cleaned_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract distribution_records as structured rows for the report appendix.

        After DataCleaner, distribution_records entries look like:
            [{fact: [{locality: ..., establishment_status: ..., ...}, ...], sources: [...]}]
        The fact value is a list of record dicts. We flatten across all fact-lists,
        dedup by (locality, status, means), then shape into display rows.
        """
        import copy
        remaining_data = copy.deepcopy(cleaned_data)

        dist_category = remaining_data.get("distribution_and_status", {})
        raw_records = dist_category.pop("distribution_records", None)

        # If the category is now empty, drop it entirely
        if dist_category is not None and not dist_category:
            remaining_data.pop("distribution_and_status", None)

        if not raw_records:
            return {"remaining_data": remaining_data, "distribution_records": []}

        # Flatten all record dicts from all fact-list entries
        flat_records = []
        for entry in raw_records:
            fact = entry.get("fact")
            if isinstance(fact, list):
                for rec in fact:
                    if isinstance(rec, dict):
                        flat_records.append(rec)

        if not flat_records:
            return {"remaining_data": remaining_data, "distribution_records": []}

        # Dedup by (locality, establishment_status, establishment_means),
        # collecting provenance as {database: [contributing dataset titles]}.
        seen: Dict[tuple, Dict] = {}
        for rec in flat_records:
            locality = (rec.get("locality") or "").strip()
            status = rec.get("establishment_status") or ""
            means = rec.get("establishment_means") or ""
            key = (locality.lower(), status.lower(), means.lower())

            if key not in seen:
                seen[key] = {
                    "locality": locality,
                    "establishment_status": status,
                    "establishment_means": means,
                    "provenance": {},
                }
            _add_provenance(seen[key]["provenance"], rec)

        deduped = list(seen.values())

        # E3.4: Drop continent/supra-national entries — they add no value at
        # country granularity and inflate the table without useful information.
        deduped = [r for r in deduped if r["locality"] not in _CONTINENT_BLOCKLIST]

        # Sort: INTRODUCED first, then by locality alphabetically
        def _sort_key(r):
            means_order = 0 if r["establishment_means"].upper() == "INTRODUCED" else 1
            return (means_order, r["locality"].lower())

        deduped.sort(key=_sort_key)

        records = self._build_records(deduped)
        return {"remaining_data": remaining_data, "distribution_records": records}

    def _build_records(self, records) -> List[Dict[str, Any]]:
        """Shape deduplicated distribution records into the report appendix rows
        {locality, status, means, sources}, humanising the status/means codes."""
        out: List[Dict[str, Any]] = []
        for rec in records:
            locality = rec["locality"] or "—"
            status = rec["establishment_status"] or "—"
            means = rec["establishment_means"] or "—"
            sources = _format_provenance(rec["provenance"])

            if status.upper() == "PRESENT":
                status = "Present"
            elif status.upper() == "NOT_SPECIFIED":
                status = "Not specified"

            if means.upper() == "INTRODUCED":
                means = "Introduced"
            elif means.upper() == "NATIVE":
                means = "Native"
            elif means.upper() == "NOT_SPECIFIED":
                means = "Not specified"

            out.append({
                "locality": locality.replace("|", ""),  # GBIF artefact, never meaningful
                "status": status,
                "means": means,
                "sources": sources,
            })

        return out
