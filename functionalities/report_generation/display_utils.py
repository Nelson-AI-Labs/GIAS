#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Display utilities used by the NarrativeGeneratorComponent.

Contains:
  - Reference look-up dicts (ISO-2, ISO-639-2, NUTS/outermost, field aliases)
  - humanize_field_name()    — snake_case / camelCase → readable label
  - resolve_value()          — walk nested values, resolve codes/language dicts
  - preprocess_for_display() — transform cleaned_data keys+values for human readability
"""

import re
from typing import Any, Dict


# ──────────────────────────────────────────────────────────────────────────────
# ISO 3166-1 alpha-2 → full country name
# Covers all codes that appear in GBIF/EASIN/WRiMS/IUCN datasets GIAS queries.
# Note: GE = Georgia (not Germany); DE = Germany.
# ──────────────────────────────────────────────────────────────────────────────
_ISO2_COUNTRY: Dict[str, str] = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan",
    "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AR": "Argentina",
    "AT": "Austria", "AU": "Australia", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BD": "Bangladesh", "BE": "Belgium",
    "BG": "Bulgaria", "BH": "Bahrain", "BJ": "Benin", "BO": "Bolivia",
    "BR": "Brazil", "BY": "Belarus",
    "CA": "Canada", "CH": "Switzerland", "CI": "Côte d'Ivoire",
    "CL": "Chile", "CM": "Cameroon", "CN": "China", "CO": "Colombia",
    "CR": "Costa Rica", "CU": "Cuba", "CY": "Cyprus", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "DZ": "Algeria",
    "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt", "ES": "Spain",
    "ET": "Ethiopia",
    "FI": "Finland", "FJ": "Fiji", "FR": "France",
    "GB": "United Kingdom", "GE": "Georgia", "GH": "Ghana",
    "GN": "Guinea", "GR": "Greece", "GT": "Guatemala",
    "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia", "HU": "Hungary",
    "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India",
    "IQ": "Iraq", "IR": "Iran", "IS": "Iceland", "IT": "Italy",
    "JM": "Jamaica", "JO": "Jordan", "JP": "Japan",
    "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia", "KR": "South Korea",
    "KW": "Kuwait", "KZ": "Kazakhstan",
    "LA": "Laos", "LB": "Lebanon", "LK": "Sri Lanka", "LT": "Lithuania",
    "LU": "Luxembourg", "LV": "Latvia",
    "MA": "Morocco", "MD": "Moldova", "ME": "Montenegro",
    "MK": "North Macedonia", "ML": "Mali", "MM": "Myanmar",
    "MN": "Mongolia", "MT": "Malta", "MU": "Mauritius", "MX": "Mexico",
    "MY": "Malaysia", "MZ": "Mozambique",
    "NA": "Namibia", "NG": "Nigeria", "NI": "Nicaragua",
    "NL": "Netherlands", "NO": "Norway", "NP": "Nepal", "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama", "PE": "Peru", "PG": "Papua New Guinea",
    "PH": "Philippines", "PK": "Pakistan", "PL": "Poland",
    "PR": "Puerto Rico", "PT": "Portugal", "PY": "Paraguay",
    "QA": "Qatar",
    "RO": "Romania", "RS": "Serbia", "RU": "Russia",
    "SA": "Saudi Arabia", "SD": "Sudan", "SE": "Sweden",
    "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia",
    "SN": "Senegal", "SO": "Somalia", "SR": "Suriname", "SY": "Syria",
    "TH": "Thailand", "TJ": "Tajikistan", "TN": "Tunisia",
    "TR": "Turkey", "TW": "Taiwan", "TZ": "Tanzania",
    "UA": "Ukraine", "UG": "Uganda", "UK": "United Kingdom",
    "US": "United States", "UY": "Uruguay", "UZ": "Uzbekistan",
    "VE": "Venezuela", "VN": "Vietnam",
    "YE": "Yemen", "ZA": "South Africa", "ZM": "Zambia", "ZW": "Zimbabwe",
}

# ──────────────────────────────────────────────────────────────────────────────
# NUTS / EU Outermost Region codes → human-readable names
# ──────────────────────────────────────────────────────────────────────────────
_NUTS_OUTERMOST: Dict[str, str] = {
    "FRY1": "Guadeloupe (FR)", "FRY2": "Martinique (FR)",
    "FRY3": "French Guiana (FR)", "FRY4": "Mayotte (FR)",
    "FRY5": "Réunion (FR)",
    "PT2": "Azores (PT)", "PT3": "Madeira (PT)",
    "ES7": "Canary Islands (ES)",
}

# ──────────────────────────────────────────────────────────────────────────────
# Field name aliases — maps raw DB field keys to English display labels.
# Applied in both structured tables and narrative AI prompt preprocessing.
# ──────────────────────────────────────────────────────────────────────────────
_FIELD_LABEL_ALIASES: Dict[str, str] = {
    # Common abbreviations / opaque keys
    "usos": "Uses",
    "riesgo": "Risk",
    "taxon": "Taxon",
    "ms": "Member State",
    "MS": "Member State",
    "is_eu_concern": "EU Reg. 1143/2014 Listed",
    "is_ms_concern": "Member State Concern",
    "is_outermost_concern": "Outermost Region Concern",
    "is_horizon_scanning": "Horizon Scanning",
    "entry_into_force": "Entry into Force",
    "eicat_score": "EICAT Score",
    "eicat_mechanism": "EICAT Mechanism",
    "eicat_assessment": "EICAT Assessment",
    "seicat_score": "SEICAT Score",
    "seicat_mechanism": "SEICAT Mechanism",
    "iucn_red_list": "IUCN Red List",
    "iucn_category": "IUCN Category",
    "conservation_status": "Conservation Status",
    "gbif_key": "GBIF Taxon Key",
    "accepted_name_usage_id": "Accepted Name Usage ID",
    "canonical_name": "Canonical Name",
    "scientific_name_authorship": "Authorship",
    "name_published_in_year": "Year Published",
    "taxonomic_status": "Taxonomic Status",
    "number_of_occurrences": "Number of Occurrences",
    "vernacular_names": "Vernacular Names",
    "children_taxa": "Children Taxa",
    "distribution_records": "Distribution Records",
    "present_in_countries": "Present in Countries",
    "first_introductions_in_eu": "First Introductions in EU",
    "european_spread_establishment": "European Spread and Establishment",
    "diet_composition": "Diet Composition",
    "habitats_list": "Habitat Types",
    "trophic_level": "Trophic Level",
    "trophic_position_shift": "Trophic Position Shift",
    "majorimportance": "Major Importance",
    "iso2": "ISO-2 Code",
    "impactreference": "Impact Reference",
    "impacturl": "Impact URL",
    "impactsectorid": "Impact Sector ID",
    "sectorname": "Sector Name",
}

# ──────────────────────────────────────────────────────────────────────────────
# ISO-639-2/B (bibliographic) 3-letter language codes → full English names.
# GBIF/IUCN embed these as 'language' values in list-of-dict records.
# ──────────────────────────────────────────────────────────────────────────────
_ISO639_2: Dict[str, str] = {
    'eng': 'English', 'nld': 'Dutch', 'deu': 'German', 'fra': 'French',
    'spa': 'Spanish', 'por': 'Portuguese', 'ita': 'Italian',
    'zho': 'Chinese', 'jpn': 'Japanese', 'kor': 'Korean',
    'rus': 'Russian', 'ara': 'Arabic', 'pol': 'Polish',
    'swe': 'Swedish', 'nor': 'Norwegian', 'dan': 'Danish',
    'fin': 'Finnish', 'ces': 'Czech', 'slk': 'Slovak',
    'hun': 'Hungarian', 'ron': 'Romanian', 'bul': 'Bulgarian',
    'hrv': 'Croatian', 'slv': 'Slovenian', 'est': 'Estonian',
    'lat': 'Latvian', 'lit': 'Lithuanian', 'ell': 'Greek',
    'tur': 'Turkish', 'ukr': 'Ukrainian', 'srp': 'Serbian',
}

# Regex for ISO-2: exactly 2 uppercase ASCII letters
_ISO2_RE = re.compile(r'^[A-Z]{2}$')
# Regex for ISO-639-2: exactly 3 lowercase ASCII letters
_ISO639_RE = re.compile(r'^[a-z]{3}$')


# ──────────────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────────────

def humanize_field_name(field_name: str) -> str:
    """
    Convert a raw DB field key to a human-readable label.

    Priority:
      1. _FIELD_LABEL_ALIASES lookup (exact match)
      2. Split camelCase ("decimalLatitude" → "decimal Latitude")
      3. Replace underscores with spaces, title-case

    Used by the narrative generator and preprocess_for_display().
    """
    if field_name in _FIELD_LABEL_ALIASES:
        return _FIELD_LABEL_ALIASES[field_name]
    # Split camelCase
    name = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', field_name)
    return name.replace('_', ' ').title()


def resolve_value(value: Any) -> Any:
    """
    Recursively resolve codes and language-keyed dicts within a value.

    Handles:
    - Bare ISO-2 string ("AT") → "Austria"
    - Bare ISO-639-2 string ("nld") → "Dutch"
    - Language-keyed dict ({"en": "Wetlands", "fr": "Zones humides"}) → "Wetlands"
    - IUCN-style description dict ({"description": {...}, "code": "0"}) → unwrap description
    - list → recurse
    - dict with normal keys → recurse values (preserving keys)
    - else → pass through
    """
    if isinstance(value, str):
        if _ISO2_RE.match(value) and value in _ISO2_COUNTRY:
            return _ISO2_COUNTRY[value]
        if _ISO639_RE.match(value) and value in _ISO639_2:
            return _ISO639_2[value]
        if value in _NUTS_OUTERMOST:
            return _NUTS_OUTERMOST[value]
        return value

    if isinstance(value, list):
        resolved = [resolve_value(item) for item in value]
        return resolved

    if isinstance(value, dict):
        if not value:
            return value
        # Language-keyed dict: all keys are short (1-3 chars), e.g. {"en": "...", "nl": "..."}
        if all(len(k) <= 3 for k in value.keys()):
            preferred = (
                value.get('en') or value.get('eng')
                or next((v for v in value.values() if v), None)
            )
            if preferred is not None:
                return resolve_value(preferred)
        # IUCN-style {"description": {...}, "code": "0"} — prefer description
        if 'description' in value and value['description']:
            return resolve_value(value['description'])
        # General dict: recurse into values
        return {k: resolve_value(v) for k, v in value.items()}

    return value


def preprocess_for_display(cleaned_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform cleaned_data into human-readable form for the narrative AI prompt.

    Transformations applied (does NOT mutate input):
    1. Category keys: snake_case keys → display names via StandardTopicRegistry
    2. Field keys: raw DB keys → aliases via _FIELD_LABEL_ALIASES / humanize_field_name
    3. Fact values: ISO-2 codes, ISO-639-2 codes, language-keyed dicts all resolved

    Used by NarrativeGeneratorComponent._format_json_for_ai() so Mistral receives
    "Distribution & Status" not "distribution_and_status", "Austria" not "AT", etc.
    """
    from core.registries.topic_registry import StandardTopicRegistry

    result: Dict[str, Any] = {}

    for category_key, category_data in cleaned_data.items():
        # Category key → display name
        topic = StandardTopicRegistry.get_topic(category_key)
        display_category = topic.display_name if topic else humanize_field_name(category_key)

        if not isinstance(category_data, dict):
            result[display_category] = category_data
            continue

        display_fields: Dict[str, Any] = {}
        for field_key, field_entries in category_data.items():
            display_field = humanize_field_name(field_key)

            if not isinstance(field_entries, list):
                display_fields[display_field] = field_entries
                continue

            # Walk each {fact, sources, agreement} entry and resolve the fact value
            resolved_entries = []
            for entry in field_entries:
                if not isinstance(entry, dict):
                    resolved_entries.append(entry)
                    continue
                resolved_entry = dict(entry)
                if 'fact' in resolved_entry:
                    resolved_entry['fact'] = resolve_value(resolved_entry['fact'])
                resolved_entries.append(resolved_entry)

            display_fields[display_field] = resolved_entries

        result[display_category] = display_fields

    return result
