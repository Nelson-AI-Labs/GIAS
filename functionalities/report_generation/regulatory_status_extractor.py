#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Regulatory Status Extractor Component
======================================

Haystack component that extracts regulatory/listing/status fields from cleaned
species data and renders them as a traceable "Regulatory Status" box.

Every line in the box cites its source database. No AI judgements — facts only.

Scaling mechanism: a Mistral Small classification call semantically identifies
which fields are regulatory status vs. narrative content, so new databases and
field names are handled automatically without code changes.

Graceful fallback: if the classifier is unavailable, all data passes through
unchanged and the box is omitted — the rest of the pipeline is unaffected.
"""

import copy
import json
import logging
from typing import Any, Dict, List, Set, Tuple

from haystack import component
from haystack.dataclasses import ChatMessage

from core.utils.generator_factory import create_generator

logger = logging.getLogger(__name__)

_CLASSIFICATION_PROMPT = """You are a data classifier for invasive species reports.

Below is a list of data fields with sample values extracted from species databases.
Classify each field as either "status" or "content".

"status" = regulatory listings, legal designations, official classifications, formal status flags,
           entry-into-force dates, horizon scanning flags, boolean indicators of regulatory concern,
           official risk assessment scores (e.g. "Alto", "High"), CITES listings,
           EU Regulation 1143/2014 listings, member state concern flags, outermost region concern flags,
           any field that represents a formal regulatory or legal determination about the species.

"content" = narrative descriptions, detailed analyses, management measures, conservation actions,
            habitat descriptions, species traits, life history, pathway descriptions,
            sector-by-sector impact analyses, bibliographic data, species interaction descriptions,
            occurrence records, population data — anything that belongs in the body of a report.

IMPORTANT — do NOT classify as "status":
- Taxonomic status fields (e.g. "accepted", "synonym", "invalid", "doubtful") — these describe
  nomenclature, not legal status.
- Boolean data quality or presence flags from EASIN or similar databases: fields named
  has_impact, is_part_native, part_native, has_distribution_data, has_record, is_established —
  these are database metadata flags, not regulatory determinations.
- Fields whose value is derived from a taxonomic database record rather than a legal or
  official regulatory instrument (e.g. a field saying "Accepted" from a taxonomy table).
- Conservation status from an ecological assessment (e.g. IUCN Red List categories like
  "LC", "VU") is "content", not "status" — it is not a legal/regulatory listing.

Fields to classify:
{field_list}

Return ONLY a JSON array of objects with no explanation and no markdown fencing:
[{{"category": "...", "field": "...", "class": "status"}}]
Include only fields classified as "status". Omit all "content" fields from the response.
"""

# Internal processing labels — never shown as citable sources in the rendered box.
# Keep in sync with report_formatter.py and narrative_generator.py until those are
# consolidated into core/utils/source_labels.py (Phase E2).
_INTERNAL_SOURCE_LABELS: set = {'AI-normalization', 'Unknown', 'Research Source'}

# E3.3: NUTS / EU Outermost Region codes → human-readable names.
_NUTS_OUTERMOST: dict = {
    "FRY1": "Guadeloupe (FR)", "FRY2": "Martinique (FR)",
    "FRY3": "French Guiana (FR)", "FRY4": "Mayotte (FR)",
    "FRY5": "Réunion (FR)",
    "PT2": "Azores (PT)", "PT3": "Madeira (PT)",
    "ES7": "Canary Islands (ES)",
}

# E3.2: ISO 3166-1 alpha-2 → country name (subset used in EASIN member states).
_ISO2_TO_NAME: dict = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia",
    "ES": "Spain", "FI": "Finland", "FR": "France", "GR": "Greece",
    "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta",
    "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
}

_KNOWN_LABELS = {
    "is_eu_concern": "EU Reg. 1143/2014",
    "is_ms_concern": "Member State concern",
    "is_outermost_concern": "Outermost region concern",
    "is_horizon_scanning": "Horizon scanning",
    "entry_into_force": "Entry into force",
    "concerned_member_states": "Concerned member states",
    "concerned_outermost_regions": "Concerned outermost regions",
}


@component
class RegulatoryStatusExtractor:
    """
    Extracts regulatory/status fields from cleaned data and renders a traceable box.

    Sits in the pipeline between DistributionTableExtractor and the content generator.
    Pops classified fields from cleaned_data so the content generator does not
    render them again.
    """

    def __init__(self):
        """Initialise with a Mistral Small classifier. Fails gracefully if unavailable."""
        try:
            self.classifier = create_generator("regulatory_classifier")
        except Exception as e:
            logger.warning(
                "RegulatoryStatusExtractor: classifier unavailable (%s). "
                "Regulatory Status box will not be rendered.",
                e,
            )
            self.classifier = None

    @component.output_types(
        remaining_data=Dict[str, Any],
        regulatory_status=List[Dict[str, Any]],
    )
    def run(self, cleaned_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify fields and extract status entries as structured rows.

        Args:
            cleaned_data: Cleaned species data from DataCleanerComponent.
                          Structure: {category: {field: [{fact, sources, agreement}]}}

        Returns:
            remaining_data: cleaned_data with status fields removed (for content generator)
            regulatory_status: list of {label, value, source} rows, or [] if no status data
        """
        remaining_data = copy.deepcopy(cleaned_data)

        if self.classifier is None or not cleaned_data:
            return {"remaining_data": remaining_data, "regulatory_status": []}

        # Build inventory: one entry per field across all categories
        inventory = self._build_inventory(cleaned_data)
        if not inventory:
            return {"remaining_data": remaining_data, "regulatory_status": []}

        # Ask Mistral Small which fields are regulatory status
        status_keys = self._classify_fields(inventory)
        if not status_keys:
            return {"remaining_data": remaining_data, "regulatory_status": []}

        # Pop status fields from remaining_data and collect entries for rendering
        status_entries = []
        for category, field_name in status_keys:
            category_data = remaining_data.get(category, {})
            field_entries = category_data.pop(field_name, None)
            if not field_entries:
                continue
            # Each field may have multiple fact entries (e.g. same field from multiple sources)
            # Flatten: collect all unique facts + all sources
            for entry in field_entries:
                status_entries.append({
                    "field_name": field_name,
                    "fact": entry.get("fact"),
                    "sources": entry.get("sources", []),
                })

        # Drop empty categories left after popping
        empty_cats = [cat for cat, fields in remaining_data.items() if not fields]
        for cat in empty_cats:
            remaining_data.pop(cat)

        if not status_entries:
            return {"remaining_data": remaining_data, "regulatory_status": []}

        rows = self._build_status_rows(status_entries)
        return {"remaining_data": remaining_data, "regulatory_status": rows}

    def _build_inventory(
        self, cleaned_data: Dict[str, Any]
    ) -> List[Tuple[str, str, str]]:
        """Build list of (category, field_name, sample_value_str) for classification."""
        inventory = []
        for category, fields in cleaned_data.items():
            for field_name, entries in fields.items():
                if not entries:
                    continue
                # Use the first entry's fact as a representative sample
                sample = entries[0].get("fact", "")
                sample_str = self._truncate_sample(sample)
                inventory.append((category, field_name, sample_str))
        return inventory

    def _truncate_sample(self, value: Any, max_len: int = 80) -> str:
        """Produce a short string representation of a field value for the prompt."""
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, str):
            return value[:max_len] + ("…" if len(value) > max_len else "")
        if isinstance(value, dict):
            desc = value.get("description") or value.get("type") or next(iter(value.values()), "")
            return str(desc)[:max_len]
        if isinstance(value, list):
            if not value:
                return "[]"
            first = value[0]
            if isinstance(first, dict):
                return str(first)[:max_len]
            return str(first)[:max_len]
        return str(value)[:max_len]

    def _classify_fields(
        self, inventory: List[Tuple[str, str, str]]
    ) -> Set[Tuple[str, str]]:
        """
        Call Mistral Small to classify fields as 'status' or 'content'.
        Returns a set of (category, field_name) tuples classified as 'status'.
        Returns empty set on any failure.
        """
        field_list = "\n".join(
            f'- category: "{cat}", field: "{field}", sample: {sample}'
            for cat, field, sample in inventory
        )
        prompt = _CLASSIFICATION_PROMPT.format(field_list=field_list)

        try:
            messages = [ChatMessage.from_user(prompt)]
            result = self.classifier.run(messages=messages)
            response_text = result["replies"][0].text.strip()

            # Strip markdown fences if the model adds them despite the instruction
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]

            classified = json.loads(response_text)
            return {
                (item["category"], item["field"])
                for item in classified
                if item.get("class") == "status"
            }
        except Exception as e:
            logger.warning(
                "RegulatoryStatusExtractor: classification failed (%s). "
                "Skipping regulatory box.",
                e,
            )
            return set()

    def _build_status_rows(self, status_entries: List[Dict]) -> List[Dict[str, Any]]:
        """Build structured status rows {label, value, source} for the report
        template. Rows whose only sources are internal processing labels are
        dropped (no citable origin); identical label+value rows are merged. The
        template renders one source chip per row, so `source` is the primary
        (first) visible source."""
        rows: List[Dict[str, Any]] = []
        seen_rows = set()
        for entry in status_entries:
            label = self._humanize_field_name(entry["field_name"])
            value = self._format_value(entry["fact"])
            visible_sources = [s for s in entry["sources"] if s not in _INTERNAL_SOURCE_LABELS]
            if not visible_sources:
                continue

            row_key = (label, value)
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)

            rows.append({"label": label, "value": value, "source": visible_sources[0]})

        return rows

    def _humanize_field_name(self, field_name: str) -> str:
        """Convert a field_name to a human-readable label."""
        if field_name in _KNOWN_LABELS:
            return _KNOWN_LABELS[field_name]
        # Fallback: strip is_ prefix, replace underscores, title-case
        label = field_name
        if label.startswith("is_"):
            label = label[3:]
        return label.replace("_", " ").title()

    def _format_value(self, fact: Any) -> str:
        """Convert an arbitrary fact value to a readable string."""
        if fact is None:
            return "—"
        if isinstance(fact, bool):
            return "Yes" if fact else "No"
        if isinstance(fact, str):
            return fact if fact.strip() else "—"
        if isinstance(fact, dict):
            # Prefer 'description' key (GBIF pattern); fall back to first value
            if "description" in fact:
                return str(fact["description"]).strip() or "—"
            first_val = next(iter(fact.values()), None)
            return str(first_val).strip() if first_val is not None else "—"
        if isinstance(fact, list):
            if not fact:
                return "—"
            first = fact[0]
            if isinstance(first, dict):
                # EASIN member states: [{MS: "ES"}, {MS: "IE"}]
                if "MS" in first:
                    codes = [str(item.get("MS", "")) for item in fact if item.get("MS")]
                    return ", ".join(_ISO2_TO_NAME.get(c, c) for c in codes)
                # EASIN outermost regions: [{Region: "FRY3"}, ...]  E3.3
                if "Region" in first:
                    codes = [str(item.get("Region", "")) for item in fact if item.get("Region")]
                    return ", ".join(_NUTS_OUTERMOST.get(c, c) for c in codes)
                # Generic: first dict's first non-empty value
                first_val = next((v for v in first.values() if v), None)
                return str(first_val) if first_val is not None else "—"
            return ", ".join(str(v) for v in fact if v)
        return str(fact)
