#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Data Cleaner Component
=======================

Haystack component that preprocesses categorized data for report generation.

Strips metadata, deduplicates identical values across sources, and detects
contradictions — so downstream components (AI or structured) receive only
minimal {fact, sources, agreement} entries.
"""

import json
import logging
import re
import unicodedata
from typing import Dict, List, Any, Optional, Set
from haystack import component
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# Module-level cache for translated strings so the same value is only sent to
# Google Translate once per process, regardless of how many facts share it.
_TRANSLATION_CACHE: Dict[str, str] = {}

# token_set_ratio score (0–100) at or above which two string facts in the same
# field are treated as the same fact phrased differently and merged. Set high
# (92) so only cosmetic variants collapse — casing, punctuation, word order,
# minor inserted words — never genuinely distinct facts that share vocabulary.
_NEAR_DUP_THRESHOLD = 92


@component
class DataCleanerComponent:
    """
    Preprocesses categorized data for report generation.

    Tasks:
    1. Strip metadata fields (data_type, categorization_method, original_field, ai_reasoning)
    2. Filter out null/empty values
    3. Deduplicate identical values across sources
    4. Detect contradictions and flag with agreement status
    5. Collect unique sources list
    """

    _NULL_STRINGS: Set[str] = {
        'not_specified', 'not specified', 'uncertain', 'unknown',
        'n/a', 'na', 'none', 'null', '—', '-', 'unspecified',
        'no data', 'no information', 'not available', 'not applicable',
        # E2.5: Human-readable null equivalents that databases emit verbatim
        'no habitat details available', 'data deficient', 'not recorded',
        'not reported', 'not assessed', 'no information available',
    }

    # Pattern: "FieldName: value; AnotherField: value; ..." (raw DB record dumps)
    _RAW_DUMP_PATTERN = re.compile(
        r'^[A-Z][a-zA-Z]+(?:ID|Full|Name|Region|Status):\s+.+;\s+[A-Z]',
    )

    # E2.2: BOLD barcode-of-life BIN identifiers — not taxonomy, never useful
    _BOLD_ID_PATTERN = re.compile(r'^BOLD:[A-Z]+\d+$')

    # E2.1: Normalise ISO-639-2 language codes to full names so
    # {"name": "X", "language": "eng"} and {"name": "X", "language": "English"}
    # produce the same dedup hash.
    _LANG_NORMALISE: Dict[str, str] = {
        'eng': 'english', 'nld': 'dutch', 'deu': 'german', 'fra': 'french',
        'spa': 'spanish', 'por': 'portuguese', 'ita': 'italian',
        'zho': 'chinese', 'jpn': 'japanese', 'kor': 'korean',
        'rus': 'russian', 'ara': 'arabic', 'pol': 'polish',
    }

    # Boolean descriptor values → Yes/No, applied *after* translation so it stays
    # language-agnostic: a source flag like "el_taxón_es_salobre: FALSO" is first
    # translated to "false" by the general pipeline, then rendered here as "No".
    _BOOL_RENDER: Dict[str, str] = {
        'true': 'Yes', 'false': 'No', 'yes': 'Yes', 'no': 'No',
    }

    def __init__(self):
        pass

    @component.output_types(
        cleaned_data=Dict[str, Any],
        all_sources=List[str],
        stats=Dict[str, int]
    )
    def run(self, filtered_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean and deduplicate categorized data.

        Args:
            filtered_data: Categorized data filtered to selected categories

        Returns:
            Dict with:
                - cleaned_data: Minimal JSON (fact + sources + agreement only)
                - all_sources: List of all unique sources encountered
                - stats: Processing statistics
        """
        if not filtered_data:
            return {
                'cleaned_data': {},
                'all_sources': [],
                'stats': {'categories_processed': 0, 'fields_processed': 0, 'values_deduplicated': 0}
            }

        cleaned_data = {}
        all_sources = set()
        total_fields = 0
        total_deduplicated = 0

        for category_name, category_data in filtered_data.items():
            if not isinstance(category_data, dict):
                logger.warning(f"DataCleaner: Unexpected type for category '{category_name}': {type(category_data)}")
                continue

            cleaned_category, field_count, dedup_count, sources = self._clean_category(category_data)

            if cleaned_category:
                cleaned_data[category_name] = cleaned_category
                all_sources.update(sources)
                total_fields += field_count
                total_deduplicated += dedup_count

        stats = {
            'categories_processed': len(cleaned_data),
            'fields_processed': total_fields,
            'values_deduplicated': total_deduplicated
        }

        logger.info(f"DataCleaner: {stats}")

        return {
            'cleaned_data': cleaned_data,
            'all_sources': sorted(all_sources),
            'stats': stats
        }

    def _clean_category(self, category_data: Dict[str, List]) -> tuple:
        """
        Process all fields in a category.

        Returns:
            Tuple of (cleaned_fields_dict, field_count, dedup_count, sources_set)
        """
        cleaned_fields = {}
        field_count = 0
        dedup_count = 0
        sources = set()

        for field_name, field_entries in category_data.items():
            if not isinstance(field_entries, list):
                logger.warning(f"DataCleaner: Field '{field_name}' is not a list, skipping")
                continue

            # Translate non-English field keys to English instead of dropping them
            # (e.g. the Colombian GBIF "rango_de_elevación" → "elevation_range").
            # English keys pass through untouched and never hit the translator.
            original_field = field_name
            field_name = self._translate_field_key(field_name)
            # A changed key means the field was non-English and its content was
            # translated — detect the source language so the report can flag it.
            translated_from = (self._detect_field_language(field_entries, original_field)
                               if field_name != original_field else None)

            deduplicated, deduped, field_sources = self._deduplicate_field(field_entries)

            if deduplicated:
                if translated_from:
                    for entry in deduplicated:
                        entry['translated_from'] = translated_from
                # Two source-language keys may translate to the same English key;
                # merge their entries rather than overwrite.
                if field_name in cleaned_fields:
                    cleaned_fields[field_name].extend(deduplicated)
                else:
                    cleaned_fields[field_name] = deduplicated
                    field_count += 1
                dedup_count += deduped
                sources.update(field_sources)

        return cleaned_fields, field_count, dedup_count, sources

    def _translate_field_key(self, field_name: str) -> str:
        """Translate a non-English field key to an English snake_case key.

        English keys are returned unchanged with no API call. A key is treated as
        non-English when it contains non-ASCII characters (accented/non-Latin
        scripts) OR langdetect confidently flags the de-underscored phrase as
        non-English (catches unaccented Dutch/German). The confidence guard keeps
        English/Latin keys away from the translator so they can't be mangled.
        """
        detect_phrase = field_name.replace('_', ' ').strip()
        if not detect_phrase:
            return field_name

        if field_name.isascii():
            try:
                from core.utils.language_utils import detect_language
                lang_result = detect_language(detect_phrase)
                if (lang_result.get('detection_failed')
                        or lang_result.get('is_english')
                        or lang_result.get('confidence', 0) <= 0.5):
                    return field_name
            except Exception:
                return field_name  # langdetect unavailable — keep original

        cache_key = f"__key__{field_name}"
        cached = _TRANSLATION_CACHE.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Translate the raw underscored key: Google preserves the underscore
            # token boundary and yields cleaner results than the spaced phrase
            # ("rango_de_elevación" → "elevation_range", not "lifting range").
            from core.utils.language_utils import translate_to_english
            result = translate_to_english(field_name, 'auto')
            if result.get('success'):
                english = result['translated_text'].strip()
                if english and english.lower() != field_name.lower():
                    slug = re.sub(r'\s+', '_', english.lower())
                    _TRANSLATION_CACHE[cache_key] = slug
                    logger.debug(
                        f"DataCleaner: translated field key '{field_name}' → '{slug}'")
                    return slug
        except Exception:
            pass  # deep-translator unavailable — keep original

        _TRANSLATION_CACHE[cache_key] = field_name
        return field_name

    def _detect_field_language(self, field_entries: List[Dict], original_key: str) -> Optional[str]:
        """Detect the source language of a translated field for report flagging.

        Detection needs enough text to be reliable (short phrases fail), so it runs
        on the original key phrase plus the first entry's free-text content
        (type + description). Returns the language name (e.g. "Spanish") only when
        confidently non-English, else None (no flag rather than a wrong one).
        """
        parts = [original_key.replace('_', ' ')]
        for entry in field_entries:
            if not isinstance(entry, dict):
                continue
            value = entry.get('value')
            if isinstance(value, dict):
                for key in ('type', 'description'):
                    text = value.get(key)
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            elif isinstance(value, str) and value.strip():
                parts.append(value.strip())
            break  # first entry is enough to identify the language

        text = ' '.join(parts).strip()
        if len(text) < 8:
            return None
        try:
            from core.utils.language_utils import detect_language
            result = detect_language(text)
            if (not result.get('detection_failed')
                    and not result.get('is_english')
                    and result.get('confidence', 0) > 0.5):
                return result.get('language_name')
        except Exception:
            pass
        return None

    def _deduplicate_field(self, field_entries: List[Dict]) -> tuple:
        """
        Deduplicate field entries by grouping identical values.

        Steps:
        1. Extract value and source from each entry
        2. Filter out null/empty values
        3. Group identical values together (collecting sources)
        4. Calculate agreement status based on source counts
        5. Return list of {fact, sources, agreement}

        Returns:
            Tuple of (deduplicated_list, dedup_count, sources_set)
        """
        # Group: hashable_key -> {"value": original_value, "sources": set()}
        groups: Dict[str, Dict[str, Any]] = {}
        all_sources = set()
        original_count = 0

        for entry in field_entries:
            if not isinstance(entry, dict):
                continue

            value = entry.get('value')
            source = entry.get('source', 'Unknown')

            if self._is_null_or_empty(value):
                continue

            value = self._clean_value(value)
            if value is None:
                continue

            original_count += 1
            all_sources.add(source)

            hashable_key = self._make_hashable(value)

            if hashable_key in groups:
                groups[hashable_key]['sources'].add(source)
            else:
                groups[hashable_key] = {
                    'value': value,
                    'sources': {source}
                }

        if not groups:
            return [], 0, set()

        # Calculate agreement status and build output
        total_sources = len(all_sources)
        result = []

        for group in groups.values():
            source_count = len(group['sources'])

            if total_sources == 1 or source_count == 1:
                agreement = "single"
            elif source_count > total_sources / 2:
                agreement = "consensus"
            else:
                agreement = "minority"

            result.append({
                'fact': group['value'],
                'sources': sorted(group['sources']),
                'agreement': agreement
            })

        # Collapse near-duplicate phrasings of the same fact (e.g. the same fact
        # reported by GBIF/WRiMS/IUCN with cosmetic wording differences). Exact-hash
        # grouping above only merges identical normalised values; this catches the rest.
        result = self._merge_near_duplicates(result, total_sources)

        # Sort: consensus first, then minority, then single
        agreement_order = {'consensus': 0, 'single': 1, 'minority': 2}
        result.sort(key=lambda x: agreement_order.get(x['agreement'], 3))

        dedup_count = original_count - len(result)
        return result, dedup_count, all_sources

    def _merge_near_duplicates(self, entries: List[Dict], total_sources: int) -> List[Dict]:
        """
        Merge string facts that are near-duplicate phrasings of the same fact.

        Posture: consolidate, never delete. Merging preserves every source and
        retains each collapsed phrasing under 'merged_variants' for audit — no
        information is lost. Only string facts are clustered; dict/list facts keep
        their exact-hash grouping (fuzzy-merging structured values could silently
        drop distinct sub-values).

        Clustering is greedy and longest-first, so the most complete phrasing
        becomes the canonical 'fact'. Agreement is recomputed from the merged
        source count, upgrading near-dupes that previously read as several weak
        single-source facts into one multi-source consensus fact.
        """
        string_entries = [e for e in entries if isinstance(e.get('fact'), str)]
        passthrough = [e for e in entries if not isinstance(e.get('fact'), str)]

        if len(string_entries) < 2:
            return entries

        # Longest fact first → cluster representative is the most complete phrasing.
        string_entries.sort(key=lambda e: len(e['fact']), reverse=True)

        clusters: List[List[Dict]] = []
        for entry in string_entries:
            candidate = entry['fact'].strip().lower()
            cand_nums = self._numeric_tokens(candidate)
            placed = False
            for cluster in clusters:
                rep = cluster[0]['fact'].strip().lower()
                # Numbers are load-bearing facts (sizes, ranges, dates, counts):
                # "tolerates 5-35 C" and "tolerates 5-30 C" are different facts that
                # score ~95 lexically. Refuse to merge unless the numeric content matches.
                if self._numeric_tokens(rep) != cand_nums:
                    continue
                if fuzz.token_set_ratio(candidate, rep) >= _NEAR_DUP_THRESHOLD:
                    cluster.append(entry)
                    placed = True
                    break
            if not placed:
                clusters.append([entry])

        merged: List[Dict] = []
        for cluster in clusters:
            if len(cluster) == 1:
                merged.append(cluster[0])
                continue

            sources = sorted({s for e in cluster for s in e.get('sources', [])})
            source_count = len(sources)
            if total_sources == 1 or source_count == 1:
                agreement = "single"
            elif source_count > total_sources / 2:
                agreement = "consensus"
            else:
                agreement = "minority"

            merged.append({
                'fact': cluster[0]['fact'],  # longest phrasing (canonical)
                'sources': sources,
                'agreement': agreement,
                'merged_variants': [e['fact'] for e in cluster[1:]],
            })

        return passthrough + merged

    @staticmethod
    def _numeric_tokens(text: str) -> tuple:
        """Sorted multiset of numbers in a fact, for the near-dup numeric guard.

        Matches integers and decimals (e.g. 12, 5, 35, 1.5). Two facts may only be
        merged as near-duplicates if these match exactly — a difference in any
        number means a difference in the fact itself.
        """
        return tuple(sorted(re.findall(r'\d+(?:\.\d+)?', text)))

    def _make_hashable(self, value: Any) -> str:
        """
        Convert any value type to a hashable string for deduplication.

        Handles strings, numbers, booleans, lists, dicts, and nested structures.

        G4: Dict string values are lowercased before serialisation so that
        sources like IUCN (which returns taxonomy in ALL CAPS) hash identically
        to GBIF/EASIN (mixed-case) and collapse into one deduplicated entry.
        """
        if isinstance(value, str):
            return value.strip().lower()
        elif isinstance(value, (int, float, bool)):
            return str(value)
        elif isinstance(value, list):
            return json.dumps(
                [self._make_hashable(i) for i in value], default=str
            )
        elif isinstance(value, dict):
            normalized = {
                k: (v.strip().lower() if isinstance(v, str) else self._make_hashable(v))
                for k, v in value.items()
            }
            return json.dumps(normalized, sort_keys=True, default=str)
        else:
            return str(value)

    def _is_null_or_empty(self, value: Any) -> bool:
        """Check if value should be filtered out (including null-equivalent strings)."""
        if value is None:
            return True
        if isinstance(value, str):
            stripped = value.strip().lower()
            if not stripped or stripped in self._NULL_STRINGS:
                return True
            # E2.5 fix: databases emit sentences like "No habitat details available."
            # with trailing punctuation — strip it before the null-string check.
            stripped_no_punct = stripped.rstrip('.,:;!?')
            if stripped_no_punct in self._NULL_STRINGS:
                return True
        if isinstance(value, (list, dict)) and len(value) == 0:
            return True
        # H3: Dicts where every value is null/empty carry no information.
        # IUCN returns geographic_range and population as {key: null, ...} — these
        # should be suppressed rather than rendered as "range_size_km2: ; ...".
        if isinstance(value, dict) and all(self._is_null_or_empty(v) for v in value.values()):
            return True
        return False

    def _clean_value(self, value: Any) -> Any:
        """
        Clean a value before deduplication.

        - Normalises string encoding to UTF-8 NFC (fixes "MillA;n" → "Millán") (B4)
        - Detects raw database record dumps and converts to structured dicts (A4)
        - Filters out non-English prose from database-sourced text fields (B5)
        - Cleans list values: BOLD filter, blank-coord filter, intra-list dedup (E2)
        """
        if isinstance(value, list):
            return self._clean_list_value(value)

        if isinstance(value, dict):
            return self._clean_dict_value(value)

        if not isinstance(value, str):
            return value

        # B4: Normalise to NFC — fixes garbled characters from Latin-1/Windows-1252
        # sources (e.g. "MillA;n" becomes "Millán", broken dashes become proper em-dashes)
        value = unicodedata.normalize('NFC', value)

        # E1.4: Strip inline [N] citation markers embedded in extracted research text.
        # These are the source paper's own reference numbers (e.g. [22], [23] from
        # Jackson 2012) — they point to entries in the source paper's bibliography,
        # not GIAS's reference list. Leaving them causes dangling citations in the
        # rendered report (readers see [22] but the References section only goes to [6]).
        # GIAS's own [N] markers are added downstream by the narrative generator
        # after this cleaning step, so this strip is safe.
        value = re.sub(r'\[\d+\]', '', value).strip()

        # E2.8: Strip paper preamble artefacts (affiliation line + received/accepted date
        # + "Abstract" heading) that PDF extractors capture before the actual text.
        # Pattern: anything up to "(Received DD Mon YYYY...)" followed by optional
        # "Abstract" heading. Cap lookahead at 400 chars — legitimate abstracts start
        # further in only when the extractor captured extra boilerplate.
        value = re.sub(
            r'^.{0,400}?\(Received\s+\d+\s+\w+\s+\d{4}[^)]*\)\s*(?:Abstract\s*)?',
            '', value, flags=re.DOTALL
        ).strip()
        value = re.sub(r'^(?:Abstract|ABSTRACT)\s+', '', value).strip()
        if not value:
            return None

        # E2.3: Detect raw tabular-data dumps from PDF extraction (e.g. isotope tables,
        # data matrices extracted as flat text: "Chironomids 218.760.7 5.760.4 7 ...").
        # Heuristic: ≥8 float-like tokens and floats outnumber long words → suppress.
        # Long-word guard prevents false positives on numeric-heavy prose (rare).
        float_tokens = re.findall(r'\d+\.\d+', value)
        if len(float_tokens) >= 8:
            long_words = re.findall(r'[a-zA-Z]{5,}', value)
            if len(float_tokens) > len(long_words):
                logger.debug(
                    f"DataCleaner: suppressed raw tabular dump "
                    f"({len(float_tokens)} floats, {len(long_words)} long words): "
                    f"{value[:60]}…"
                )
                return None

        # Translate non-English text to English, then render boolean values
        # (true/false → Yes/No) — generic and language-agnostic because the
        # translation has already happened (e.g. "FALSO" → "false" → "No").
        value = self._translate_text(value)
        value = self._BOOL_RENDER.get(value.strip().lower(), value)

        # Detect raw DB dump pattern: "Key: val; Key: val; ..."
        if self._RAW_DUMP_PATTERN.match(value):
            pairs = re.split(r';\s*', value)
            parsed = {}
            for pair in pairs:
                if ':' in pair:
                    k, v = pair.split(':', 1)
                    k = k.strip()
                    v = v.strip()
                    if v and v.lower() not in self._NULL_STRINGS:
                        # Humanize key: "RecipientRegionFull" -> "Recipient Region"
                        human_key = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', k)
                        human_key = human_key.replace('Full', '').replace('ID', '').strip()
                        if human_key and v:
                            parsed[human_key] = v
            if parsed:
                return parsed
            return None  # All values were null-equivalent

        return value

    def _translate_text(self, value: str) -> str:
        """Translate a non-English string to English via the shared pipeline.

        Returns the original string when already English, when translation fails,
        or when the translator is unavailable — never drops content. Each value is
        cached module-wide so it is only sent to Google Translate once per process.
        """
        # G1: Short strings (3–8 chars) — langdetect confidence is too low at this
        # length, so skip detection and translate via auto. Restrict to all-lower or
        # all-upper tokens (e.g. "herb", "FALSO"); Latin taxonomic names are
        # Title-case (Animalia, Decapoda…) and are deliberately excluded.
        if (3 <= len(value) <= 8 and any(c.isalpha() for c in value)
                and value in (value.lower(), value.upper())):
            try:
                from core.utils.language_utils import translate_to_english
                cached = _TRANSLATION_CACHE.get(value)
                if cached is not None:
                    return cached
                translation = translate_to_english(value, 'auto')
                if translation.get('success'):
                    translated = translation['translated_text']
                    _TRANSLATION_CACHE[value] = translated
                    return translated
            except Exception:
                pass  # deep-translator unavailable — keep value as-is
            return value

        if len(value) > 8:
            try:
                from core.utils.language_utils import detect_language, translate_to_english
                cached = _TRANSLATION_CACHE.get(value)
                if cached is not None:
                    return cached
                lang_result = detect_language(value)
                if (not lang_result.get('detection_failed')
                        and not lang_result.get('is_english')
                        and lang_result.get('confidence', 0) > 0.5):
                    lang_code = lang_result.get('language_code', 'auto')
                    translation = translate_to_english(value, lang_code)
                    if translation.get('success'):
                        translated = translation['translated_text']
                        _TRANSLATION_CACHE[value] = translated
                        logger.debug(
                            f"DataCleaner: translated "
                            f"({lang_result.get('language_name', '?')} → en): "
                            f"{value[:60]}…"
                        )
                        return translated
                    else:
                        # Translation failed — keep original rather than silently drop
                        logger.debug(
                            f"DataCleaner: translation failed for "
                            f"({lang_result.get('language_name', '?')}), keeping original: "
                            f"{value[:60]}…"
                        )
            except Exception:
                pass  # langdetect/deep-translator unavailable — keep value as-is

        return value

    def _clean_dict_value(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Translate the free-text members of a source descriptor dict
        ({description, type, language, source}) to English; leave the DB name
        ('source') and the language code untouched. A boolean 'description'
        (true/false, post-translation) renders as Yes/No.
        """
        cleaned = dict(d)
        for key in ('description', 'type'):
            text = cleaned.get(key)
            if isinstance(text, str) and text.strip():
                text = self._translate_text(unicodedata.normalize('NFC', text))
                if key == 'description':
                    text = self._BOOL_RENDER.get(text.strip().lower(), text)
                cleaned[key] = text
        return cleaned

    def _clean_list_value(self, items: list) -> Optional[list]:
        """
        Clean a list value:
        - Drop BOLD BIN identifiers masquerading as children taxa (E2.2)
        - Drop occurrence records with no coordinates (E2.6)
        - Deduplicate items by normalised hash (E2.1)
        """
        seen: set = set()
        result = []
        for item in items:
            if isinstance(item, dict):
                # E2.2: Drop BOLD barcode-of-life BIN IDs (GBIF returns these as
                # "children taxa" but they are DNA sequence cluster identifiers,
                # not taxonomic children)
                sci_name = item.get('scientificName', '') or ''
                if self._BOLD_ID_PATTERN.match(str(sci_name)):
                    continue

                # E2.6 / F1: Drop occurrence records that carry no geographic coordinates.
                # GBIF returns camelCase keys (decimalLatitude), so normalise to lowercase
                # before checking to ensure the filter always fires.
                item_lower = {k.lower(): v for k, v in item.items()}
                if 'decimallatitude' in item_lower or 'decimallongitude' in item_lower:
                    lat = item_lower.get('decimallatitude')
                    lon = item_lower.get('decimallongitude')
                    lat_empty = lat is None or str(lat).strip() == ''
                    lon_empty = lon is None or str(lon).strip() == ''
                    if lat_empty and lon_empty:
                        continue

            key = self._normalize_for_dedup(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)

        return result if result else None

    def _normalize_for_dedup(self, value: Any) -> str:
        """
        Produce a normalised hash for intra-list deduplication.

        Normalises language tags (ISO-639-2 → full name, e.g. 'nld' → 'dutch')
        and lowercases strings so entries that differ only in capitalisation or
        language-tag format collapse to a single entry.
        """
        if isinstance(value, str):
            return value.strip().lower()
        if isinstance(value, dict):
            normalised = {}
            for k, v in value.items():
                k_norm = k.strip().lower()
                if isinstance(v, str):
                    v_norm = v.strip().lower()
                    if k_norm in ('language', 'lang'):
                        v_norm = self._LANG_NORMALISE.get(v_norm, v_norm)
                    normalised[k_norm] = v_norm
                else:
                    normalised[k_norm] = v
            return json.dumps(normalised, sort_keys=True, default=str)
        if isinstance(value, list):
            return json.dumps(
                [self._normalize_for_dedup(i) for i in value], default=str
            )
        return str(value)
