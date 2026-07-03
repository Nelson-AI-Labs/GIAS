# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Distribution Map Component
===========================

Component for rendering an interactive map of where a species is present.

Renders, driven live from the species' distribution_and_status data:
  1. A choropleth fill of countries by status (NATIVE / INTRODUCED / UNCERTAIN), built
     from our merged country data.
  2. Point markers for GBIF occurrence records that carry real lat/lon coordinates.
  3. A dashed-outline echo of countries reported only in the literature.

Drawn with Plotly using built-in Natural Earth geometry — no basemap tiles, so it
carries no tile-provider licensing constraints. The figure builder (_build_choropleth)
is shared with the static PDF map (report_generation/map_renderer.py), so the dashboard
and report stay visually consistent.

Data is collected from five sources within the distribution_and_status category:
  - EASIN present_in_countries       → INTRODUCED
  - EASIN first_introductions_in_eu  → INTRODUCED
  - IUCN countries                   → INTRODUCED (or NATIVE if origin field says so)
  - GBIF occurrence_sample           → NATIVE / INTRODUCED / UNCERTAIN based on establishmentMeans
  - AquaNIS introduction_records     → INTRODUCED (full country names converted via inline map)

Per-source statuses are retained (not collapsed). A country is classified as:
  - CONFLICT   when sources genuinely disagree (some say NATIVE, others INTRODUCED)
  - otherwise  the highest-priority single status: NATIVE (3) > INTRODUCED (2) > UNCERTAIN (1)

UNCERTAIN is genuine ambiguity, not a disagreement, so it never triggers a CONFLICT;
it only acts as a fallback when no firmer status exists for a country.

Usage:
    from frontend.ui_components.distribution_map import render_distribution_map
    render_distribution_map(categorized_fields, universal_id)
"""

import json
from pathlib import Path

import streamlit as st
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from frontend.utils.icons import glyph_svg

# Shipped ISO-3 world-country polygons (used for country-name → ISO-3 resolution)
_GEOJSON_PATH = Path(__file__).resolve().parents[2] / "core" / "assets" / "world_countries.geojson"

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

# Single-status precedence, used to pick a winner only when sources AGREE (or are
# silent). Genuine NATIVE↔INTRODUCED disagreement resolves to CONFLICT instead — see
# resolve_status — so CONFLICT is deliberately absent from this table.
STATUS_PRIORITY: Dict[str, int] = {
    "NATIVE":     3,
    "INTRODUCED": 2,
    "UNCERTAIN":  1,
}

COLOR_MAP: Dict[str, str] = {
    "NATIVE":     "#2ecc71",
    "INTRODUCED": "#dc2626",
    "UNCERTAIN":  "#f39c12",
    # Magenta — distinct from INTRODUCED red and the purple literature outline.
    "CONFLICT":   "#db2777",
}

LEGEND_LABELS: Dict[str, str] = {
    "NATIVE":     "Native range",
    "INTRODUCED": "Introduced / Established",
    "UNCERTAIN":  "Observed (status unknown)",
    "CONFLICT":   "Conflicting source data",
}

# Compact one-word status labels for per-source provenance detail (hover + table).
SHORT_LABELS: Dict[str, str] = {
    "NATIVE":     "Native",
    "INTRODUCED": "Introduced",
    "UNCERTAIN":  "Uncertain",
}

# Occurrence point markers — a distinct layer from the status fill (a single non-palette
# colour avoids implying a status, since GBIF rarely reports establishmentMeans).
POINT_COLOR: str = "#2563eb"

# Literature-reported countries — drawn as a distinct outline OVER the status fill, so
# provenance (extracted from papers) is unmistakable and overlaps with API data stay visible.
LITERATURE_COLOR: str = "#7c3aed"

# EU-27 member states (ISO-2).  Used by render_eu_presence to filter the country
# statuses dict to a European subset that is most relevant for IAS policy.
EU_COUNTRIES_ISO2: frozenset = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
    "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK",
})

# ---------------------------------------------------------------------------
# Country name → ISO-2 lookup (covers realistic AquaNIS / marine invasion names)
# ---------------------------------------------------------------------------

COUNTRY_NAME_TO_ISO2: Dict[str, str] = {
    "israel": "IL",
    "turkey": "TR",
    "greece": "GR",
    "italy": "IT",
    "spain": "ES",
    "france": "FR",
    "portugal": "PT",
    "egypt": "EG",
    "tunisia": "TN",
    "algeria": "DZ",
    "morocco": "MA",
    "libya": "LY",
    "lebanon": "LB",
    "syria": "SY",
    "cyprus": "CY",
    "malta": "MT",
    "croatia": "HR",
    "albania": "AL",
    "montenegro": "ME",
    "slovenia": "SI",
    "romania": "RO",
    "bulgaria": "BG",
    "ukraine": "UA",
    "russia": "RU",
    "georgia": "GE",
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "australia": "AU",
    "new zealand": "NZ",
    "south africa": "ZA",
    "japan": "JP",
    "china": "CN",
    "india": "IN",
    "indonesia": "ID",
    "philippines": "PH",
    "thailand": "TH",
    "vietnam": "VN",
    "malaysia": "MY",
    "singapore": "SG",
    "brazil": "BR",
    "argentina": "AR",
    "chile": "CL",
    "mexico": "MX",
    "canada": "CA",
    "iran": "IR",
    "iraq": "IQ",
    "saudi arabia": "SA",
    "kuwait": "KW",
    "bahrain": "BH",
    "qatar": "QA",
    "united arab emirates": "AE",
    "oman": "OM",
    "pakistan": "PK",
    "bangladesh": "BD",
    "sri lanka": "LK",
    "korea": "KR",
    "south korea": "KR",
    "taiwan": "TW",
    "hong kong": "HK",
}


def country_name_to_iso2(name: str) -> Optional[str]:
    """
    Convert a full country name (case-insensitive) to an ISO-2 code.

    The hardcoded dict above is checked first (it handles aliases like "usa"/"uk"); on a
    miss we fall back to the shipped GeoJSON's country names (180 countries), so the long
    tail (e.g. "Kenya") resolves without maintaining a second exhaustive table.
    """
    if not name or not isinstance(name, str):
        return None
    key = name.lower().strip()
    iso2 = COUNTRY_NAME_TO_ISO2.get(key)
    if iso2:
        return iso2
    iso3 = _country_name_to_iso3_index().get(key)
    return ISO3_TO_ISO2.get(iso3) if iso3 else None


# ---------------------------------------------------------------------------
# ISO-2 ↔ ISO-3 conversion (ISO-3 required by Plotly / the GeoJSON feature ids)
# ---------------------------------------------------------------------------

ISO2_TO_ISO3: Dict[str, str] = {
        'AT': 'AUT', 'BE': 'BEL', 'CH': 'CHE', 'CZ': 'CZE', 'DE': 'DEU',
        'ES': 'ESP', 'FR': 'FRA', 'HU': 'HUN', 'IE': 'IRL', 'IL': 'ISR',
        'IM': 'IMN', 'IT': 'ITA', 'JE': 'JEY', 'LU': 'LUX', 'NL': 'NLD',
        'NO': 'NOR', 'PL': 'POL', 'PT': 'PRT', 'SE': 'SWE', 'GB': 'GBR',
        'DK': 'DNK', 'FI': 'FIN', 'GR': 'GRC', 'IS': 'ISL', 'LI': 'LIE',
        'MT': 'MLT', 'MC': 'MCO', 'SM': 'SMR', 'VA': 'VAT', 'AD': 'AND',
        'AL': 'ALB', 'BA': 'BIH', 'BG': 'BGR', 'HR': 'HRV', 'CY': 'CYP',
        'EE': 'EST', 'FO': 'FRO', 'GI': 'GIB', 'GL': 'GRL', 'GG': 'GGY',
        'RS': 'SRB', 'ME': 'MNE', 'MK': 'MKD', 'RO': 'ROU', 'SI': 'SVN',
        'SK': 'SVK', 'TR': 'TUR', 'UA': 'UKR', 'BY': 'BLR', 'MD': 'MDA',
        'LT': 'LTU', 'LV': 'LVA',
        'US': 'USA', 'CA': 'CAN', 'MX': 'MEX', 'BR': 'BRA', 'AR': 'ARG',
        'CL': 'CHL', 'CO': 'COL', 'PE': 'PER', 'VE': 'VEN', 'AU': 'AUS',
        'NZ': 'NZL', 'ZA': 'ZAF', 'EG': 'EGY', 'MA': 'MAR', 'DZ': 'DZA',
        'TN': 'TUN', 'LY': 'LBY', 'JP': 'JPN', 'CN': 'CHN', 'IN': 'IND',
        'KR': 'KOR', 'TH': 'THA', 'VN': 'VNM', 'ID': 'IDN', 'MY': 'MYS',
        'PH': 'PHL', 'SG': 'SGP', 'BD': 'BGD', 'PK': 'PAK', 'IR': 'IRN',
        'IQ': 'IRQ', 'SA': 'SAU', 'AE': 'ARE', 'OM': 'OMN', 'YE': 'YEM',
        'KW': 'KWT', 'QA': 'QAT', 'BH': 'BHR', 'JO': 'JOR', 'LB': 'LBN',
        'SY': 'SYR', 'PS': 'PSE', 'RU': 'RUS', 'KZ': 'KAZ', 'UZ': 'UZB',
        'TM': 'TKM', 'TJ': 'TJK', 'KG': 'KGZ', 'AF': 'AFG', 'MN': 'MNG',
        'KP': 'PRK', 'TW': 'TWN', 'HK': 'HKG', 'MO': 'MAC', 'MM': 'MMR',
        'LA': 'LAO', 'KH': 'KHM', 'BN': 'BRN', 'TL': 'TLS', 'FJ': 'FJI',
        'PG': 'PNG', 'NC': 'NCL', 'PF': 'PYF', 'WS': 'WSM', 'TO': 'TON',
        'VU': 'VUT', 'SB': 'SLB', 'KI': 'KIR', 'TV': 'TUV', 'NR': 'NRU',
        'PW': 'PLW', 'FM': 'FSM', 'MH': 'MHL', 'CK': 'COK', 'NU': 'NIU',
        'TK': 'TKL', 'WF': 'WLF', 'AS': 'ASM', 'GU': 'GUM', 'MP': 'MNP',
        'PR': 'PRI', 'VI': 'VIR', 'VG': 'VGB', 'KY': 'CYM', 'BM': 'BMU',
        'TC': 'TCA', 'MS': 'MSR', 'AI': 'AIA', 'AG': 'ATG', 'AW': 'ABW',
        'BS': 'BHS', 'BB': 'BRB', 'BZ': 'BLZ', 'CW': 'CUW', 'DM': 'DMA',
        'DO': 'DOM', 'GD': 'GRD', 'GP': 'GLP', 'HT': 'HTI', 'JM': 'JAM',
        'MQ': 'MTQ', 'KN': 'KNA', 'LC': 'LCA', 'MF': 'MAF', 'PM': 'SPM',
        'VC': 'VCT', 'SX': 'SXM', 'TT': 'TTO', 'AO': 'AGO', 'BJ': 'BEN',
        'BW': 'BWA', 'BF': 'BFA', 'BI': 'BDI', 'CV': 'CPV', 'CM': 'CMR',
        'CF': 'CAF', 'TD': 'TCD', 'KM': 'COM', 'CG': 'COG', 'CD': 'COD',
        'CI': 'CIV', 'DJ': 'DJI', 'GQ': 'GNQ', 'ER': 'ERI', 'SZ': 'SWZ',
        'ET': 'ETH', 'GA': 'GAB', 'GM': 'GMB', 'GH': 'GHA', 'GN': 'GIN',
        'GW': 'GNB', 'KE': 'KEN', 'LS': 'LSO', 'LR': 'LBR', 'MG': 'MDG',
        'MW': 'MWI', 'ML': 'MLI', 'MR': 'MRT', 'MU': 'MUS', 'YT': 'MYT',
        'MZ': 'MOZ', 'NA': 'NAM', 'NE': 'NER', 'NG': 'NGA', 'RE': 'REU',
        'RW': 'RWA', 'SH': 'SHN', 'ST': 'STP', 'SN': 'SEN', 'SC': 'SYC',
        'SL': 'SLE', 'SO': 'SOM', 'SS': 'SSD', 'SD': 'SDN', 'TZ': 'TZA',
        'TG': 'TGO', 'UG': 'UGA', 'EH': 'ESH', 'ZM': 'ZMB', 'ZW': 'ZWE',
        'BT': 'BTN', 'MV': 'MDV', 'NP': 'NPL', 'LK': 'LKA', 'GE': 'GEO',
}

ISO3_TO_ISO2: Dict[str, str] = {v: k for k, v in ISO2_TO_ISO3.items()}


def iso2_to_iso3(iso2_code: str) -> Optional[str]:
    """
    Convert ISO 3166-1 alpha-2 (2-letter) country code to ISO 3166-1 alpha-3 (3-letter).
    Required because Plotly / the GeoJSON feature ids use ISO-3.
    """
    if not iso2_code or len(iso2_code.strip()) != 2:
        return None
    return ISO2_TO_ISO3.get(iso2_code.upper().strip())


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_nested_data_list(raw_value: Any) -> List[Any]:
    """
    Unwrap the {data: [...]} nesting pattern present in some fields (e.g. introduction_records).
    Returns the flat list of items, or the original value if no nesting is detected.
    """
    if (isinstance(raw_value, list) and
            len(raw_value) == 1 and
            isinstance(raw_value[0], dict) and
            "data" in raw_value[0] and
            isinstance(raw_value[0]["data"], list)):
        return raw_value[0]["data"]
    return raw_value if isinstance(raw_value, list) else []


def _extract_bool_field(distribution_data: Dict, field_name: str) -> bool:
    """Extract a boolean field value from the distribution_and_status data structure."""
    entries = distribution_data.get(field_name, [])
    for entry in entries:
        val = entry.get('value')
        if isinstance(val, bool):
            return val
    return False


def _labeled_status_dicts(distribution_data: Dict[str, Any]) -> List[Tuple[str, Dict[str, str]]]:
    """
    Run every extractor and tag its output with the source it came from, so provenance
    survives the merge. Shared by the dashboard map and the PDF map renderer (single
    source of truth for the source-label mapping). distribution_records (GBIF + WRiMS)
    contributes its own per-source dicts via extract_from_distribution_records.
    """
    labeled = [
        ("EASIN", extract_from_present_in_countries(distribution_data.get('present_in_countries', []))),
        ("EASIN", extract_from_first_introductions(distribution_data.get('first_introductions_in_eu', []))),
        ("IUCN", extract_from_iucn_countries(distribution_data.get('countries', []))),
        ("GBIF", extract_from_occurrence_sample(distribution_data.get('occurrence_sample', []))),
        ("AquaNIS", extract_from_introduction_records(distribution_data.get('introduction_records', []))),
        ("AI-normalized", extract_from_normalized_countries(distribution_data.get('normalized_countries', []))),
        ("AquaNIS", extract_from_source_regions(distribution_data.get('source_regions', []))),
    ]
    dr_labeled, _ = extract_from_distribution_records(distribution_data.get('distribution_records', []))
    labeled.extend(dr_labeled)
    return labeled


def extract_unmapped_localities(distribution_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Marine / open-ocean distribution_records that resolve to no country — surfaced
    (in a list + caption) instead of being silently dropped from the country map."""
    _, unmapped = extract_from_distribution_records(distribution_data.get('distribution_records', []))
    return unmapped


def collect_country_statuses(
    labeled: List[Tuple[str, Dict[str, str]]],
) -> Dict[str, Dict[str, str]]:
    """
    Accumulate per-source statuses per country, preserving provenance.

    Input is a list of (source_label, {iso2 → status}) pairs (one per extractor).
    Returns {iso2 → {source_label → status}}. If two extractors share a label
    (e.g. both EASIN fields) and disagree, the higher-priority status is kept for
    that label so a single source never appears to conflict with itself.
    """
    out: Dict[str, Dict[str, str]] = {}
    for label, status_dict in labeled:
        for iso2, status in status_dict.items():
            per_source = out.setdefault(iso2, {})
            current = per_source.get(label)
            if current is None or STATUS_PRIORITY[status] > STATUS_PRIORITY[current]:
                per_source[label] = status
    return out


def resolve_status(per_source: Dict[str, str]) -> Tuple[str, str]:
    """
    Resolve one country's per-source statuses to a final status + provenance detail.

    - CONFLICT when sources genuinely disagree: at least one says NATIVE and another
      says INTRODUCED. UNCERTAIN is ambiguity, not disagreement, so it never triggers
      a conflict.
    - Otherwise the highest-priority single status via STATUS_PRIORITY.

    Returns (status, detail) where detail is a per-source summary for hover/table,
    e.g. "IUCN: Native · EASIN: Introduced · GBIF: Introduced".
    """
    statuses = set(per_source.values())
    if "NATIVE" in statuses and "INTRODUCED" in statuses:
        final = "CONFLICT"
    else:
        final = max(per_source.values(), key=lambda s: STATUS_PRIORITY[s])

    detail = " · ".join(
        f"{label}: {SHORT_LABELS[status]}"
        for label, status in sorted(per_source.items())
    )
    return final, detail


# ---------------------------------------------------------------------------
# Per-source extractors — each returns Dict[str, str] mapping iso2 → status
# ---------------------------------------------------------------------------

def extract_from_present_in_countries(field_entries: List[Dict]) -> Dict[str, str]:
    """
    EASIN present_in_countries: [{"Country": "BE"}, {"Country": "CY"}, ...]
    All entries classified as INTRODUCED.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                code = item.get('Country') or item.get('country') or item.get('countryCode')
                if code and isinstance(code, str):
                    result[code.upper().strip()] = "INTRODUCED"
            elif isinstance(item, str):
                result[item.upper().strip()] = "INTRODUCED"
    return result


def extract_from_first_introductions(field_entries: List[Dict]) -> Dict[str, str]:
    """
    EASIN first_introductions_in_eu: [{"Country": "CY", "Year": "2023", ...}]
    All entries classified as INTRODUCED.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                code = item.get('Country') or item.get('country')
                if code and isinstance(code, str):
                    result[code.upper().strip()] = "INTRODUCED"
    return result


def extract_from_iucn_countries(field_entries: List[Dict]) -> Dict[str, str]:
    """
    IUCN countries: [] or [{"isoCode": "FR", "origin": "Introduced", ...}]
    Checks for origin field to detect NATIVE; defaults to INTRODUCED.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                code = item.get('isoCode') or item.get('iso_code') or item.get('countryCode')
                if not code or not isinstance(code, str):
                    continue
                origin = str(item.get('origin', '')).lower()
                status = "NATIVE" if "native" in origin else "INTRODUCED"
                result[code.upper().strip()] = status
            elif isinstance(item, str) and item.strip():
                result[item.upper().strip()] = "INTRODUCED"
    return result


def extract_from_occurrence_sample(field_entries: List[Dict]) -> Dict[str, str]:
    """
    GBIF occurrence_sample: records with countryCode (ISO-2) and establishmentMeans.
    - establishmentMeans == "NATIVE"     → NATIVE
    - establishmentMeans == "INTRODUCED" → INTRODUCED
    - establishmentMeans is null         → UNCERTAIN
    Per-country, highest-priority status across multiple records wins.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for record in value:
            if not isinstance(record, dict):
                continue
            code = record.get('countryCode')
            if not code or not isinstance(code, str):
                continue
            code = code.upper().strip()
            status = _status_from_means(record.get('establishmentMeans'))
            # Keep highest priority status seen for this country
            current = result.get(code)
            if current is None or STATUS_PRIORITY[status] > STATUS_PRIORITY[current]:
                result[code] = status
    return result


def extract_from_normalized_countries(field_entries: List[Dict]) -> Dict[str, str]:
    """
    AI-normalized countries field written by GeoNormalizationService.
    Format: value = [{"iso2": "AR", "status": "NATIVE"}, ...]
    Status values map directly to the NATIVE/INTRODUCED/UNCERTAIN constants.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            code = item.get('iso2')
            status = item.get('status')
            if (code and isinstance(code, str) and
                    status in STATUS_PRIORITY):
                result[code.upper().strip()] = status
    return result


def extract_from_extracted_distribution(field_entries: List[Dict]) -> Dict[str, str]:
    """
    Research-extracted (paper) countries written by GeoNormalizationService as a separate,
    provenance-tagged field. Same shape as normalized_countries: value = [{iso2, status}].
    Kept separate so the map can render these as a distinct literature layer.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            code = item.get('iso2')
            status = item.get('status')
            if code and isinstance(code, str) and status in STATUS_PRIORITY:
                result[code.upper().strip()] = status
    return result


def extract_from_introduction_records(field_entries: List[Dict]) -> Dict[str, str]:
    """
    AquaNIS introduction_records: nested [{data: [{RecipientCountry: "Israel", Status: ...}]}]
    Uses full country names converted via country_name_to_iso2().
    All entries classified as INTRODUCED (Status: "Non-indigenous species").
    Silently skips unrecognised country names.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        raw_value = entry.get('value', [])
        records = _extract_nested_data_list(raw_value)
        for record in records:
            if not isinstance(record, dict):
                continue
            name = record.get('RecipientCountry') or record.get('recipientCountry')
            if not name or not isinstance(name, str):
                continue
            iso2 = country_name_to_iso2(name)
            if iso2:
                result[iso2] = "INTRODUCED"
    return result


def extract_from_source_regions(field_entries: List[Dict]) -> Dict[str, str]:
    """
    AquaNIS source_regions: [{"Country": "Kenya", "LME": ...}, {"Country": "USA", ...}].

    A SourceRegion is the donor/origin region of an introduction event — a mix of native
    source and already-invaded secondary populations — so the status is genuinely ambiguous
    and classified UNCERTAIN (the priority merge lets better data override it). Items that
    carry only a marine region (LME/Sea/Ocean) and no Country are skipped: a sea can't fill
    a country polygon.
    """
    result: Dict[str, str] = {}
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get('Country')
            if not name or not isinstance(name, str):
                continue
            iso2 = country_name_to_iso2(name)
            if iso2:
                result[iso2] = "UNCERTAIN"
    return result


def _resolve_record_iso2(record: Dict[str, Any]) -> Optional[str]:
    """
    Resolve a distribution_records entry to an ISO-2 country — clean countries only.

    Chain (first hit wins): GBIF countryCode → country name → WRiMS higher_geography
    → locality. Each name goes through country_name_to_iso2 (exact match), so a value
    that names a sea/ocean ("North Sea", "North Atlantic Ocean") or an EEZ-sea locality
    ("Dutch part of the North Sea") yields None and is treated as unmapped — a sea can't
    fill a country polygon. We deliberately do NOT parse the demonym prefix.
    """
    code = record.get('countryCode')
    if isinstance(code, str) and len(code.strip()) == 2:
        return code.upper().strip()
    for key in ('country', 'higher_geography', 'locality'):
        name = record.get(key)
        if isinstance(name, str) and name.strip():
            iso2 = country_name_to_iso2(name)
            if iso2:
                return iso2
    return None


def extract_from_distribution_records(
    field_entries: List[Dict],
) -> Tuple[List[Tuple[str, Dict[str, str]]], List[Dict[str, str]]]:
    """
    Structured read of distribution_records (GBIF + WRiMS) — the largest distribution
    dataset, previously reachable only via the lossy LLM text path.

    Reads the per-record establishment status directly (no LLM) and resolves each
    record to a country via _resolve_record_iso2. Returns:
      - labeled:  [(source_label, {iso2 → status}), ...], one dict per source entry, so
                  GBIF and WRiMS feed the conflict-aware merge as distinct sources.
      - unmapped: [{locality, status, source}] for records with no resolvable country
                  (genuinely marine / open-ocean), deduplicated — surfaced, never dropped.
    """
    labeled: List[Tuple[str, Dict[str, str]]] = []
    unmapped: List[Dict[str, str]] = []
    seen_unmapped = set()

    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        source = entry.get('source') or 'distribution_records'
        per_iso2: Dict[str, str] = {}
        for record in value:
            if not isinstance(record, dict):
                continue
            status = _status_from_means(record.get('establishment_means'))
            iso2 = _resolve_record_iso2(record)
            if iso2:
                current = per_iso2.get(iso2)
                if current is None or STATUS_PRIORITY[status] > STATUS_PRIORITY[current]:
                    per_iso2[iso2] = status
            else:
                locality = record.get('locality') or record.get('higher_geography')
                if not isinstance(locality, str) or not locality.strip():
                    continue
                key = (locality.strip(), status, source)
                if key not in seen_unmapped:
                    seen_unmapped.add(key)
                    unmapped.append({
                        'locality': locality.strip(),
                        'status': status,
                        'source': source,
                    })
        if per_iso2:
            labeled.append((source, per_iso2))

    return labeled, unmapped


def _status_from_means(means: Any) -> str:
    """Map an establishment-means value to a NATIVE/INTRODUCED/UNCERTAIN status.

    Canonical mapper for every source. Covers the differing vocabularies of GBIF
    occurrence/distribution data ("NATIVE"/"INTRODUCED") and WRiMS/WoRMS
    ("alien"/"native"), plus common synonyms ("naturalised", "invasive", "exotic").
    """
    if isinstance(means, str):
        m = means.strip().upper()
        if m in ("NATIVE", "INDIGENOUS"):
            return "NATIVE"
        if m in ("INTRODUCED", "ALIEN", "NATURALISED", "NATURALIZED",
                 "INVASIVE", "EXOTIC", "NON-NATIVE", "NONNATIVE"):
            return "INTRODUCED"
    return "UNCERTAIN"


def extract_points_from_occurrence_sample(field_entries: List[Dict]) -> List[Dict[str, Any]]:
    """
    GBIF occurrence_sample → point-level records that carry real coordinates.

    These are the precise lat/lon occurrences we'd otherwise lose by collapsing to a
    country. Records without decimalLatitude/decimalLongitude are skipped (they still
    contribute to the choropleth via extract_from_occurrence_sample).

    Returns a list of {lat, lon, status, locality} dicts.
    """
    points: List[Dict[str, Any]] = []
    for entry in field_entries:
        value = entry.get('value', [])
        if not isinstance(value, list):
            continue
        for record in value:
            if not isinstance(record, dict):
                continue
            lat = record.get('decimalLatitude')
            lon = record.get('decimalLongitude')
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            locality = (record.get('locality')
                        or record.get('stateProvince')
                        or record.get('countryCode')
                        or record.get('verbatimLocality')
                        or '')
            points.append({
                'lat': float(lat),
                'lon': float(lon),
                'status': _status_from_means(record.get('establishmentMeans')),
                'locality': str(locality)[:120],
            })
    return points


# ---------------------------------------------------------------------------
# Merge + DataFrame builder
# ---------------------------------------------------------------------------

def resolve_country_statuses(
    per_country: Dict[str, Dict[str, str]],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Resolve every country's per-source statuses to a final status + detail string.

    Takes the {iso2 → {source → status}} map from collect_country_statuses and
    returns two aligned dicts: {iso2 → final_status} and {iso2 → provenance_detail}.
    """
    statuses: Dict[str, str] = {}
    details: Dict[str, str] = {}
    for iso2, per_source in per_country.items():
        statuses[iso2], details[iso2] = resolve_status(per_source)
    return statuses, details


def build_distribution_dataframe(
    statuses: Dict[str, str],
    details: Optional[Dict[str, str]] = None,
) -> Optional[pd.DataFrame]:
    """
    Convert {iso2 → status} to a DataFrame with ISO-3 codes for Plotly.
    Columns: ISO3, iso2, status, status_label, sources_detail
    `details` maps iso2 → per-source provenance string (for hover); missing → ''.
    Returns None if no valid ISO-3 codes are produced.
    """
    details = details or {}
    rows = []
    for iso2, status in statuses.items():
        iso3 = iso2_to_iso3(iso2) if len(iso2) == 2 else (iso2 if len(iso2) == 3 else None)
        if iso3:
            rows.append({
                'ISO3': iso3,
                'iso2': iso2,
                'status': status,
                'status_label': LEGEND_LABELS[status],
                'sources_detail': details.get(iso2, ''),
            })
    if not rows:
        return None
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Choropleth figure builder (shared by the dashboard map and the PDF report)
# ---------------------------------------------------------------------------

def _build_choropleth(df, color_map, legend_labels, points=None, literature_iso3=None, extent="world", bg="white"):
    """
    Build a distribution choropleth figure for the dashboard and report maps.

    Drawn from Plotly's built-in Natural Earth geometry — no basemap tiles, so it has
    no tile-provider licensing constraints. Used interactively in the dashboard
    (st.plotly_chart) and exported as a static PNG for the PDF report (kaleido).

    - extent="world"  → full global view; extent="europe" → lat [30,72], lon [-25,60]
    - CartoDB-light palette: pale grey land, grey-blue ocean, soft white borders,
      translucent status fills
    - bg: background colour for geo/plot/paper. Default 'white' (required for PDF
      kaleido export). Pass the app paper colour (e.g. '#F2F7F8') for dashboard use
      so the map blends with the page background instead of showing a white square.
    - horizontal legend below the map: status fills, plus self-documenting entries
      for the GBIF occurrence dots, the literature outline, and the grey "No data" land
    - optional occurrence points overlaid as a scattergeo trace
    """
    import plotly.express as px
    import plotly.graph_objects as go

    color_discrete_map = {
        legend_labels["NATIVE"]:     color_map["NATIVE"],
        legend_labels["INTRODUCED"]: color_map["INTRODUCED"],
        legend_labels["UNCERTAIN"]:  color_map["UNCERTAIN"],
        legend_labels["CONFLICT"]:   color_map["CONFLICT"],
    }
    category_orders = {
        "status_label": [
            legend_labels["NATIVE"],
            legend_labels["INTRODUCED"],
            legend_labels["UNCERTAIN"],
            legend_labels["CONFLICT"],
        ]
    }

    fig = px.choropleth(
        df,
        locations='ISO3',
        color='status_label',
        locationmode='ISO-3',
        color_discrete_map=color_discrete_map,
        category_orders=category_orders,
        custom_data=['iso2', 'status_label', 'sources_detail'],
        projection='natural earth',
    )

    # Hover shows the resolved status plus the per-source breakdown when present, so a
    # CONFLICT (or any multi-source) country reveals exactly who said what.
    fig.update_traces(
        hovertemplate=(
            '<b>%{customdata[0]}</b><br>%{customdata[1]}'
            '<br><span style="font-size:11px">%{customdata[2]}</span><extra></extra>'
        ),
        marker_line_color='white',
        marker_line_width=0.6,
        marker_opacity=0.6,  # translucent fills so overlapping regions stay legible
    )

    # Overlay precise occurrence points. Single distinct colour (POINT_COLOR) —
    # occurrence markers are their own layer, not a status, since GBIF rarely
    # reports establishmentMeans.
    if points:
        fig.add_trace(go.Scattergeo(
            lat=[p['lat'] for p in points],
            lon=[p['lon'] for p in points],
            mode='markers',
            name='GBIF occurrence record',
            marker=dict(
                size=6,
                color=POINT_COLOR,
                line=dict(width=0.8, color='white'),
            ),
            hoverinfo='skip',
            showlegend=True,
        ))

    # Echo of the literature layer: a transparent-fill choropleth trace that just draws
    # a distinct border on paper-reported countries. Plotly can't do per-feature dashed
    # outlines, so this is a coarse solid border, not an exact match.
    if literature_iso3:
        fig.add_trace(go.Choropleth(
            locations=literature_iso3,
            locationmode='ISO-3',
            z=[1] * len(literature_iso3),
            colorscale=[[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0)']],
            showscale=False,
            marker_line_color=LITERATURE_COLOR,
            marker_line_width=1.8,
            hoverinfo='skip',
            showlegend=False,
        ))
        # Legend-only swatch for the literature outline: the real trace is a border-only
        # choropleth that can't carry a clean legend marker, so draw an off-map square
        # with a purple border to stand in for it.
        fig.add_trace(go.Scattergeo(
            lat=[None], lon=[None],
            mode='markers',
            name='Reported in literature',
            marker=dict(
                size=12, symbol='square',
                color='rgba(0,0,0,0)',
                line=dict(color=LITERATURE_COLOR, width=1.8),
            ),
            hoverinfo='skip',
            showlegend=True,
        ))

    # Legend-only swatch for the base land colour: countries with no data we found keep the
    # grey land fill, so state that grey = no data. Off-map point; always shown.
    fig.add_trace(go.Scattergeo(
        lat=[None], lon=[None],
        mode='markers',
        name='No data',
        marker=dict(
            size=12, symbol='square',
            color='#ececec',
            line=dict(color='#c2cbd1', width=0.5),
        ),
        hoverinfo='skip',
        showlegend=True,
    ))

    # Light CartoDB-style palette keeps the basemap subdued; Europe extent clamps the view.
    geo = dict(
        showframe=False,
        showcoastlines=True,
        coastlinecolor='#c2cbd1',
        coastlinewidth=0.5,
        showocean=True,
        oceancolor='#cdd6db',
        showlakes=True,
        lakecolor='#cdd6db',
        showrivers=False,
        showland=True,
        landcolor='#ececec',
        showcountries=True,
        countrycolor='#ffffff',
        countrywidth=0.6,
        projection_type='natural earth',
        bgcolor=bg,
    )
    if extent == "europe":
        # Europe-focused scope: covers Atlantic coast → Caspian, Mediterranean → Arctic
        geo['lataxis_range'] = [30, 72]
        geo['lonaxis_range'] = [-25, 60]

    fig.update_layout(
        geo=geo,
        plot_bgcolor=bg,
        paper_bgcolor=bg,
        margin=dict(l=0, r=0, t=10, b=50),
        height=480,
        coloraxis_showscale=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.12,
            xanchor="center",
            x=0.5,
            title_text="",
            font=dict(size=12),
        ),
    )

    return fig


# ---------------------------------------------------------------------------
# Country name → ISO-3 index (feeds an extractor's name resolution)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _load_world_geojson() -> Dict[str, Any]:
    """Load the shipped ISO-3 world-country polygons (feature.id == ISO-3)."""
    with open(_GEOJSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


@st.cache_data(show_spinner=False)
def _country_name_to_iso3_index() -> Dict[str, str]:
    """Build a {lower-cased country name → ISO-3} index from the shipped GeoJSON."""
    return {
        feature['properties']['name'].lower().strip(): feature['id']
        for feature in _load_world_geojson().get('features', [])
        if feature.get('id') and feature.get('properties', {}).get('name')
    }


# ---------------------------------------------------------------------------
# Caption
# ---------------------------------------------------------------------------

def _build_map_caption(
    statuses: Dict[str, str],
    is_part_native: bool,
    unmapped_count: int = 0,
) -> str:
    """Build a summary caption showing country counts per status category."""
    counts = {"NATIVE": 0, "INTRODUCED": 0, "UNCERTAIN": 0, "CONFLICT": 0}
    for status in statuses.values():
        counts[status] = counts.get(status, 0) + 1

    parts = []
    if counts["NATIVE"]:
        parts.append(f"{counts['NATIVE']} native range {'country' if counts['NATIVE'] == 1 else 'countries'}")
    if counts["INTRODUCED"]:
        parts.append(f"{counts['INTRODUCED']} introduced {'country' if counts['INTRODUCED'] == 1 else 'countries'}")
    if counts["UNCERTAIN"]:
        parts.append(f"{counts['UNCERTAIN']} {'country' if counts['UNCERTAIN'] == 1 else 'countries'} with uncertain status")
    if counts["CONFLICT"]:
        parts.append(f"{counts['CONFLICT']} {'country' if counts['CONFLICT'] == 1 else 'countries'} with conflicting source data")

    caption = " · ".join(parts) if parts else "No country data available"

    if unmapped_count:
        caption += (
            f" · {unmapped_count} marine/unmapped "
            f"{'locality' if unmapped_count == 1 else 'localities'} not shown on the country map"
        )

    if is_part_native:
        caption += " · EASIN classifies this species as partially native to the European region"

    return caption


def _iso2_to_name(iso2: str) -> str:
    """Best-effort ISO-2 → display country name via the shipped GeoJSON index."""
    iso3 = iso2_to_iso3(iso2)
    if iso3:
        for name, code in _country_name_to_iso3_index().items():
            if code == iso3:
                return name.title()
    return iso2


def render_conflict_table(
    statuses: Dict[str, str],
    details: Dict[str, str],
) -> None:
    """
    Show an expander listing every CONFLICT country and the per-source statuses
    that disagree. No-op when there are no conflicts.
    """
    conflicts = [iso2 for iso2, status in statuses.items() if status == "CONFLICT"]
    if not conflicts:
        return

    rows = [
        {"Country": _iso2_to_name(iso2), "Sources": details.get(iso2, "")}
        for iso2 in sorted(conflicts, key=_iso2_to_name)
    ]
    with st.expander(f":material/warning: Conflicting distribution data ({len(rows)})"):
        st.caption(
            "Sources disagree on whether the species is native or introduced in these "
            "countries. The map shows them in a distinct colour rather than picking a winner."
        )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def render_unmapped_localities(unmapped: List[Dict[str, str]]) -> None:
    """
    Show an expander listing marine / open-ocean localities that resolve to no country
    (e.g. "Dutch part of the North Sea") and so can't be drawn on the country choropleth.
    No-op when empty. Surfaces the data instead of dropping it silently.
    """
    if not unmapped:
        return

    rows = [
        {
            "Locality": u["locality"],
            "Status": SHORT_LABELS.get(u["status"], u["status"]),
            "Source": u["source"],
        }
        for u in sorted(unmapped, key=lambda u: u["locality"])
    ]
    with st.expander(f":material/water: Marine / unmapped localities ({len(rows)})"):
        st.caption(
            "These records name a sea or open ocean with no single sovereign country, "
            "so they can't fill a country polygon — listed here rather than dropped."
        )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# EU presence panel
# ---------------------------------------------------------------------------

def render_eu_presence(statuses: Dict[str, str]) -> None:
    """
    Render a compact list of EU member states where this species has been recorded,
    with a status-coloured dot per country.  Countries are ordered: introduced/conflict
    first (most policy-relevant), then uncertain, then native.
    """
    eu_present = {iso2: status for iso2, status in statuses.items() if iso2 in EU_COUNTRIES_ISO2}
    if not eu_present:
        return

    # Order by policy relevance
    order = {"INTRODUCED": 0, "CONFLICT": 1, "UNCERTAIN": 2, "NATIVE": 3}
    ordered = sorted(eu_present.items(), key=lambda x: (order.get(x[1], 9), x[0]))

    chips_html = ""
    for iso2, status in ordered:
        color = COLOR_MAP.get(status, "#999")
        # Flag emoji from ISO-2 (regional indicator symbols A–Z start at U+1F1E6)
        flag = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2)
        chips_html += (
            f'<span style="display:inline-flex;align-items:center;gap:4px;'
            f'padding:3px 8px;margin:2px;border-radius:4px;font-size:var(--fs-body);'
            f'background:rgba(0,0,0,0.04);border:1px solid rgba(0,0,0,0.08);">'
            f'<span style="width:8px;height:8px;border-radius:50%;'
            f'background:{color};display:inline-block;flex-shrink:0;"></span>'
            f'{flag} {iso2}'
            f'</span>'
        )

    st.markdown(
        f"<div style='margin-top:8px;'>"
        f"<span style='font-size:var(--fs-body);color:#6A828F;font-weight:600;'>"
        f"EU PRESENCE &nbsp;·&nbsp; {len(eu_present)} countries</span><br/>"
        f"{chips_html}</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def render_distribution_map(
    categorized_fields: Dict[str, Any],
    universal_id: Optional[str] = None,
) -> None:
    """
    Render two static distribution maps (worldwide + Europe-focused), mirroring the PDF
    report: a status choropleth of our country data with precise occurrence point markers
    and a literature-provenance outline.

    Drawn with Plotly (Natural Earth geometry, no basemap tiles), so it carries no
    tile-provider licensing constraints and shares its figure builder with the PDF
    report (see _build_choropleth). Rendered with staticPlot — no pan/zoom/hover.

    Args:
        categorized_fields: All categorized data loaded from cache
        universal_id:       Species cache id ('{gbif_key}_{name}'); accepted for caller
                            compatibility, not currently used by the Plotly map.
    """
    distribution_data = categorized_fields.get('distribution_and_status', {})
    if not distribution_data:
        return

    is_part_native = _extract_bool_field(distribution_data, 'is_part_native')

    per_country = collect_country_statuses(_labeled_status_dicts(distribution_data))
    statuses, details = resolve_country_statuses(per_country)
    points = extract_points_from_occurrence_sample(distribution_data.get('occurrence_sample', []))
    literature = extract_from_extracted_distribution(distribution_data.get('extracted_distribution', []))
    unmapped = extract_unmapped_localities(distribution_data)

    df = build_distribution_dataframe(statuses, details)
    if df is None:
        return

    literature_iso3 = [
        iso for iso in (iso2_to_iso3(c) if len(c) == 2 else c for c in literature) if iso
    ]

    # Two static maps side by side: worldwide overview + Europe-focused.
    # staticPlot disables Plotly's pan/zoom/hover; per-source breakdown is in the
    # conflict table below. use_container_width replaces the deprecated width kwarg.
    col_w, col_e = st.columns(2)
    with col_w:
        fig_world = _build_choropleth(
            df, COLOR_MAP, LEGEND_LABELS, points, literature_iso3,
            extent="world", bg="#F2F7F8",
        )
        st.plotly_chart(fig_world, use_container_width=True, config={"staticPlot": True})
    with col_e:
        fig_europe = _build_choropleth(
            df, COLOR_MAP, LEGEND_LABELS, points, literature_iso3,
            extent="europe", bg="#F2F7F8",
        )
        st.plotly_chart(fig_europe, use_container_width=True, config={"staticPlot": True})

    render_eu_presence(statuses)
    st.caption(_build_map_caption(statuses, is_part_native, len(unmapped)))
    st.markdown(
        f"<span style='font-size:var(--fs-body);color:#6A828F;'>"
        f"{glyph_svg('warning', size=14)} Map shows occurrences GIAS found across sources — absence from a country "
        "does not confirm absence; this species may have spread further."
        "</span>",
        unsafe_allow_html=True,
    )
    render_conflict_table(statuses, details)
    render_unmapped_localities(unmapped)
