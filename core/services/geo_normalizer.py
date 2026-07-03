# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Geo Normalization Service
==========================

Extracts country names from free-text fields in the distribution_and_status
category and normalizes them to ISO-2 codes with establishment status.

Called after data is written to cache by both:
  - data aggregation pipeline (core/services/categorize_to_json.py)
  - extraction merge pipeline (functionalities/extraction/merge_engine.py)

The result is written as a `normalized_countries` field back into the
distribution_and_status.json category file, making it available to the
distribution map and report generation without re-running normalization.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from functionalities.extraction.utils.json_parser import recover_json_array_from_response

from haystack.dataclasses import ChatMessage
from core.utils.generator_factory import create_generator

from core.cache_layer.categorized_data_helpers import (
    CATEGORY_FILENAMES,
    get_default_cache_dir,
    get_species_folder,
    load_category_file,
)

_PROMPT_FILE = Path(__file__).parent / "prompts" / "geo_normalization_prompt.md"
_NORMALIZATION_PROMPT = _PROMPT_FILE.read_text(encoding="utf-8")

# Per-LLM-call character budget. We never truncate: text is split into chunks under this
# size and each chunk is normalized separately, then the results are unioned.
_CHUNK_CHAR_BUDGET = 3000

# Single-status precedence when unioning chunk results for the same country.
_STATUS_PRIORITY = {"NATIVE": 3, "INTRODUCED": 2, "UNCERTAIN": 1}


def _chunk_texts(parts: List[str], budget: int = _CHUNK_CHAR_BUDGET) -> List[str]:
    """Group text parts into newline-joined chunks each <= budget chars, without cutting.

    A single part larger than the budget is emitted whole as its own chunk (with a
    warning) rather than truncated — nothing is silently dropped.
    """
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for part in parts:
        part_len = len(part) + 1  # +1 for the joining newline
        if current and current_len + part_len > budget:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        if part_len > budget and not current:
            print(f"WARNING geo_normalizer: a single field's text exceeds {budget} chars; "
                  f"sending it whole (not truncating)")
            chunks.append(part)
            continue
        current.append(part)
        current_len += part_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _collect_text_from_fields(distribution_fields: Dict[str, Any]) -> List[str]:
    """
    Extract readable text from the free-text fields that may contain country mentions.

    Reads: native_range, discussion, distribution. distribution_records is intentionally
    NOT read here — it is handled structurally by the distribution map's
    extract_from_distribution_records (per-record countryCode/higher_geography + status),
    which is lossless, so routing it through the LLM would only re-introduce truncation.

    Returns the list of text parts (NOT joined or truncated); the caller chunks them so
    nothing is ever silently cut.
    """
    text_parts: List[str] = []

    # --- native_range ---
    for entry in distribution_fields.get('native_range', []):
        value = entry.get('value')
        if isinstance(value, dict):
            desc = value.get('description') or value.get('text', '')
            if desc:
                text_parts.append(f"[native_range] {desc}")
        elif isinstance(value, str) and value:
            text_parts.append(f"[native_range] {value}")

    # --- discussion ---
    for entry in distribution_fields.get('discussion', []):
        value = entry.get('value')
        if isinstance(value, dict):
            desc = value.get('description') or value.get('text', '')
            if desc:
                text_parts.append(f"[discussion] {desc}")
        elif isinstance(value, str) and value:
            text_parts.append(f"[discussion] {value}")

    # --- distribution ---
    for entry in distribution_fields.get('distribution', []):
        value = entry.get('value')
        if isinstance(value, dict):
            desc = value.get('description') or value.get('text', '')
            if desc:
                text_parts.append(f"[distribution] {desc}")
        elif isinstance(value, str) and value:
            text_parts.append(f"[distribution] {value}")

    return text_parts


def _value_to_text(value: Any) -> str:
    """Best-effort readable text from a field value (str or {description}/{text} dict)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('description') or value.get('text') or value.get('locality') or ''
    return ''


def _collect_research_text(distribution_fields: Dict[str, Any]) -> tuple:
    """
    Gather text from *every* field whose entries are research-extracted
    (entry['is_research_data'] is True), regardless of field name. Paper-extracted geography
    lands under arbitrary field names (native_range, european_spread_regions,
    lake_naivasha_establishment_kenya, ...), so we scan by provenance, not by field name.

    Returns (text_parts, research_entry_count). The parts are NOT joined or truncated — the
    caller chunks them. The count is a cheap change-signature: it lets normalize_distribution
    recompute the literature layer only when new papers merged.
    """
    text_parts: List[str] = []
    count = 0
    for field_name, entries in distribution_fields.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get('is_research_data'):
                continue
            count += 1
            value = entry.get('value')
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = _value_to_text(item)
                if text:
                    text_parts.append(f"[{field_name}] {text}")

    return text_parts, count


def _stored_research_count(distribution_fields: Dict[str, Any]) -> Optional[int]:
    """Read the research_entry_count stamped on a prior extracted_distribution entry, if any."""
    for entry in distribution_fields.get('extracted_distribution', []):
        if isinstance(entry, dict) and 'research_entry_count' in entry:
            return entry['research_entry_count']
    return None


def _parse_llm_response(response_text: str) -> List[Dict[str, str]]:
    """
    Parse the LLM response, which should be a JSON array.
    Returns list of {iso2, status} dicts, or [] on any parse failure.
    """
    parsed = recover_json_array_from_response(response_text)
    return [
        {'iso2': item['iso2'].upper().strip(), 'status': item['status']}
        for item in parsed
        if (isinstance(item, dict)
            and 'iso2' in item and 'status' in item
            and isinstance(item['iso2'], str)
            and item['status'] in ('NATIVE', 'INTRODUCED', 'UNCERTAIN'))
    ]


class GeoNormalizationService:
    """
    Normalizes free-text geographic data in distribution_and_status to ISO-2 codes.

    Reads text from native_range, distribution_records, discussion, and distribution
    fields, uses Mistral to extract country names with establishment status, and
    writes the result as a `normalized_countries` field back into the category JSON.
    """

    def __init__(self):
        """Create the Mistral generator used for country normalization."""
        self._generator = create_generator("geo_normalizer")

    def _run_normalization(self, text: str) -> List[Dict[str, str]]:
        """Run the Mistral country-normalization prompt over `text`; [] on any failure."""
        try:
            prompt = _NORMALIZATION_PROMPT.replace("[COMBINED_TEXT]", text)
            messages = [ChatMessage.from_user(prompt)]
            response = self._generator.run(messages=messages)
            return _parse_llm_response(response['replies'][0].text)
        except Exception as e:
            print(f"LLM call failed: {e}")
            return []

    def _run_normalization_chunked(self, parts: List[str]) -> List[Dict[str, str]]:
        """Normalize text parts losslessly: chunk under the per-call budget, run each chunk,
        and union the results per country (higher-priority status wins). Never truncates."""
        merged: Dict[str, str] = {}
        for chunk in _chunk_texts(parts):
            for item in self._run_normalization(chunk):
                iso2, status = item['iso2'], item['status']
                current = merged.get(iso2)
                if current is None or _STATUS_PRIORITY[status] > _STATUS_PRIORITY[current]:
                    merged[iso2] = status
        return [{'iso2': iso2, 'status': status} for iso2, status in merged.items()]

    def normalize_distribution(self, universal_id: str) -> bool:
        """
        Run geo-normalization for a species and update its distribution_and_status.json.

        Two independent outputs are written:
          - normalized_countries:   countries from API/general free-text (computed once).
          - extracted_distribution: countries from research-extracted (paper) text, kept
            separate so provenance is preserved and the map can show it as a distinct layer.
            Recomputed whenever the number of research-extracted entries changes (i.e. new
            papers merged), so post-extraction geography reaches the map.

        Returns:
            True if anything was (re)computed and saved, or already up to date; False on error.
        """
        print(f"  [GeoNormalizer] Normalizing distribution text for {universal_id}...", end=" ")

        distribution_fields = load_category_file(universal_id, 'distribution_and_status')
        if not distribution_fields:
            print("no distribution_and_status data found")
            return False

        changed = False

        # --- API / general free-text → normalized_countries (compute once) ---
        if 'normalized_countries' not in distribution_fields:
            text_parts = _collect_text_from_fields(distribution_fields)
            if text_parts:
                normalized = self._run_normalization_chunked(text_parts)
                if normalized:
                    distribution_fields['normalized_countries'] = [{
                        'value': normalized,
                        'data_type': 'list',
                        'source': 'AI-normalization',
                        'categorization_method': 'ai',
                    }]
                    changed = True
                    print(f"normalized_countries: {len(normalized)} countries.", end=" ")

        # --- Research-extracted (paper) free-text → extracted_distribution (recompute on change) ---
        research_parts, research_count = _collect_research_text(distribution_fields)
        if research_parts and research_count != _stored_research_count(distribution_fields):
            extracted = self._run_normalization_chunked(research_parts)
            if extracted:
                distribution_fields['extracted_distribution'] = [{
                    'value': extracted,
                    'data_type': 'list',
                    'source': 'AI-normalization (research)',
                    'categorization_method': 'ai',
                    'research_entry_count': research_count,
                }]
                changed = True
                print(f"extracted_distribution: {len(extracted)} countries from {research_count} research entries.", end=" ")

        if not changed:
            print("up to date, nothing to do")
            return True

        success = self._save_category_file(universal_id, 'distribution_and_status', distribution_fields)
        print("done" if success else "failed to save")
        return success

    def _save_category_file(
        self,
        universal_id: str,
        category_name: str,
        fields: Dict[str, Any],
        cache_dir: Optional[Path] = None,
    ) -> bool:
        """Write a single category file back to disk without touching other categories."""
        try:
            if cache_dir is None:
                cache_dir = get_default_cache_dir()
            species_folder = get_species_folder(universal_id, cache_dir)
            if not species_folder.exists():
                print(f"Species folder not found: {species_folder}")
                return False
            category_filename = CATEGORY_FILENAMES.get(category_name, f"{category_name}.json")
            category_path = species_folder / category_filename
            content = {
                'category_name': category_name,
                'fields': fields,
            }
            with open(category_path, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2, ensure_ascii=False)
            return True
        except (IOError, OSError) as e:
            print(f"Error saving category file: {e}")
            return False
