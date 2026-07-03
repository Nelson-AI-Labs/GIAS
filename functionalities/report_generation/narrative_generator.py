#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Narrative Generator Component
==============================

Haystack component that converts JSON categorized data into narrative text using Mistral AI.
Follows STRICT anti-hallucination protocol (Level 1: pure reformatting, no interpretation).

Chunked architecture: one Mistral call per category to prevent timeouts on large datasets.
"""

import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import markdown as _markdown
from haystack import component
from haystack.dataclasses import ChatMessage
from core.utils.generator_factory import create_generator


# Section ordering — taxonomic_identity first, then the standard dossier flow.
# This is the order sections appear in the rendered report.
_CATEGORY_PRIORITY = [
    'taxonomic_identity',
    'distribution_and_status',
    'habitat_ecology',
    'habitat_and_ecology',
    'impacts',
    'impact_and_risk',
    'introduction_pathways',
    'pathways_and_introduction',
    'management_biosecurity',
    'management_and_biosecurity',
    'species_interactions',
    'biological_traits',
    'detection_monitoring',
]

# Fact values exceeding this byte threshold are replaced with a placeholder.
# Raw record lists (occurrence_sample, introduction_records) are table data —
# sending 80KB of GBIF occurrence rows to the LLM gains nothing and causes timeouts.
_FIELD_SIZE_LIMIT = 10_000


@component
class NarrativeGeneratorComponent:
    """
    Converts filtered categorized JSON data into narrative text using Mistral AI.

    One Mistral call per category — avoids timeouts on large species datasets where
    a single combined prompt can exceed 100K characters.
    """

    def __init__(self):
        """Load the narrative LLM generator and the base prompt template from disk."""
        self.generator = create_generator("narrative_generator")
        prompt_path = Path(__file__).parent / "report_generation_prompt.md"
        with open(prompt_path, 'r') as f:
            self.base_prompt = f.read()
        # Set by pipeline before run() when a UI progress callback is wired in.
        # Signature: callback(fraction: float, message: str) where fraction is 0.0–1.0.
        self.progress_callback = None

    @component.output_types(narratives=Dict[str, str], ai_narrative_categories=List[str])
    def run(
        self,
        cleaned_data: Dict[str, Any],
        species_name: str,
        reference_style: str = "numbered",
        citation_map: Optional[Dict[str, str]] = None,
        all_sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Convert cleaned minimal JSON data into per-category narrative HTML.

        Args:
            cleaned_data: Minimal JSON from DataCleanerComponent (fact + sources only)
            species_name: Scientific name of the species
            reference_style: "numbered" (default, [1][2] inline) or "apa" ((Author, Year) inline)
            citation_map: For APA style — {source_name: "Author, Year"} mapping.
            all_sources: For numbered style — ordered source list for pre-assigned [N] numbers.

        Returns:
            Dict with `narratives`: {category_name: section HTML}. The report
            template supplies each section's heading, so the leading `## N. Name`
            heading is stripped here; inline [N] citation markers are preserved.
        """
        if not cleaned_data:
            return {'narratives': {}, 'ai_narrative_categories': []}

        citation_block = self._build_citation_block(reference_style, citation_map, all_sources)
        ordered = self._order_categories(cleaned_data)

        print(f"\n[DIAG] NarrativeGenerator: {len(ordered)} categories, style={reference_style!r}")

        total = len([c for c in ordered if c[1]])
        narratives: Dict[str, str] = {}
        ai_categories: List[str] = []  # categories whose narrative came from the LLM (not fallback)
        for idx, (category_name, category_data) in enumerate(ordered, start=1):
            if not category_data:
                continue
            if self.progress_callback:
                from functionalities.report_generation.display_utils import humanize_field_name
                display = humanize_field_name(category_name)
                fraction = 0.05 + (idx - 1) / max(total, 1) * 0.75
                self.progress_callback(fraction, f"Writing section {idx}/{total}: {display}")
            section_text, is_ai = self._generate_section(
                category_name=category_name,
                category_data=category_data,
                species_name=species_name,
                citation_block=citation_block,
                section_number=idx,
            )
            if section_text:
                narratives[category_name] = self._to_html(section_text)
                if is_ai:
                    ai_categories.append(category_name)

        return {'narratives': narratives, 'ai_narrative_categories': ai_categories}

    @staticmethod
    def _to_html(section_text: str) -> str:
        """Strip the leading `## N. Name` heading (the report template renders
        the section heading itself) and convert the remaining markdown to HTML.
        Inline [N] citation markers pass through untouched."""
        text = re.sub(r'^\s*#{1,6}\s.*(?:\n|$)', '', section_text, count=1)
        return _markdown.markdown(text.strip(), extensions=['tables'])

    # -------------------------------------------------------------------------
    # Orchestration helpers
    # -------------------------------------------------------------------------

    def _build_citation_block(
        self,
        reference_style: str,
        citation_map: Optional[Dict[str, str]],
        all_sources: Optional[List[str]],
    ) -> str:
        if reference_style == "apa" and citation_map:
            return self._build_apa_citation_instructions(citation_map)
        if reference_style == "harvard" and citation_map:
            return self._build_harvard_citation_instructions(citation_map)
        # Numbered and Vancouver superscript both use [N] bracket markers in
        # the narrative; the visual difference (brackets vs <sup>) is a renderer
        # concern, not an AI-prompt concern.
        if reference_style in ("numbered", "vancouver_superscript") and all_sources:
            return self._build_numbered_citation_instructions(all_sources)
        return ""

    def _order_categories(self, cleaned_data: Dict[str, Any]) -> List[Tuple[str, Any]]:
        def sort_key(item: Tuple[str, Any]) -> Tuple[int, str]:
            """Order categories by their position in _CATEGORY_PRIORITY, unknown ones last (alphabetical)."""
            name = item[0]
            try:
                return (_CATEGORY_PRIORITY.index(name), name)
            except ValueError:
                return (len(_CATEGORY_PRIORITY), name)

        return sorted(cleaned_data.items(), key=sort_key)

    # -------------------------------------------------------------------------
    # Per-section generation
    # -------------------------------------------------------------------------

    def _generate_section(
        self,
        category_name: str,
        category_data: Dict[str, Any],
        species_name: str,
        citation_block: str,
        section_number: int,
    ) -> Tuple[str, bool]:
        """Returns (section_text, is_ai) where is_ai is False when the LLM call
        failed and the deterministic fallback was used instead."""
        from functionalities.report_generation.display_utils import humanize_field_name
        display_name = humanize_field_name(category_name)
        section_json = self._format_single_category(category_name, category_data)

        prompt = (
            f"{self.base_prompt}{citation_block}\n\n"
            "---\n\n"
            "## DATA TO CONVERT — SINGLE SECTION\n\n"
            f"Species: {species_name}\n\n"
            f"{section_json}\n\n"
            "---\n\n"
            f'Generate ONLY the "{display_name}" section above. '
            f'Use `## {section_number}. {display_name}` as the section heading. '
            "Do not add any other sections. Do not add a References section. "
            "Follow all formatting and citation rules above."
        )

        t0 = time.monotonic()
        print(f"[DIAG] Section '{category_name}' ({section_number}): prompt {len(prompt)} chars")

        try:
            result = self.generator.run(messages=[ChatMessage.from_user(prompt)])
            elapsed = time.monotonic() - t0
            reply = result["replies"][0]
            meta = getattr(reply, 'meta', {}) or {}
            print(
                f"[DIAG] Section '{category_name}': {elapsed:.1f}s  "
                f"finish={meta.get('finish_reason', '?')}  "
                f"response {len(reply.text)} chars"
            )
            text = reply.text
            text = re.sub(
                r'\n#{1,3}\s*(References|Sources\s+Cited|Sources|Bibliography)\b.*$',
                '',
                text,
                flags=re.DOTALL | re.IGNORECASE,
            ).rstrip()
            return text, True

        except Exception as e:
            elapsed = time.monotonic() - t0
            print(
                f"ERROR NarrativeGeneratorComponent: section '{category_name}' "
                f"failed after {elapsed:.1f}s: {e}"
            )
            import traceback
            traceback.print_exc()
            return self._generate_fallback_section(
                category_name, category_data, species_name, section_number
            ), False

    def _format_single_category(self, category_name: str, category_data: Dict[str, Any]) -> str:
        """
        Serialise one category to a JSON block for the LLM prompt.

        Humanises field keys but leaves fact values as-is (compact ISO codes, raw strings).
        Replaces any individual fact value exceeding _FIELD_SIZE_LIMIT bytes with a
        placeholder — raw record lists (occurrence_sample etc.) are table data, not prose.
        """
        from functionalities.report_generation.display_utils import humanize_field_name

        display_category = humanize_field_name(category_name)
        display_fields: Dict[str, Any] = {}

        for field_name, entries in category_data.items():
            display_field = humanize_field_name(field_name)

            if not isinstance(entries, list):
                display_fields[display_field] = entries
                continue

            trimmed = []
            for entry in entries:
                if not isinstance(entry, dict):
                    trimmed.append(entry)
                    continue
                fact = entry.get('fact')
                fact_size = len(json.dumps(fact, ensure_ascii=False))
                if fact_size > _FIELD_SIZE_LIMIT:
                    print(
                        f"[DIAG] dropped oversized fact in "
                        f"'{category_name}.{field_name}' ({fact_size} bytes)"
                    )
                    entry = dict(entry)
                    entry['fact'] = (
                        "[large dataset omitted from narrative — see structured tables in report]"
                    )
                trimmed.append(entry)

            display_fields[display_field] = trimmed

        return (
            f"\n### Category: {display_category}\n"
            f"```json\n"
            f"{json.dumps(display_fields, indent=2, ensure_ascii=False)}\n"
            f"```"
        )

    def _generate_fallback_section(
        self,
        category_name: str,
        category_data: Dict[str, Any],
        species_name: str,
        section_number: int,
    ) -> str:
        """Plain-text fallback for a single section when Mistral is unavailable."""
        from core.registries.topic_registry import StandardTopicRegistry
        topic = StandardTopicRegistry.get_topic(category_name)
        display_name = topic.display_name if topic else category_name.replace('_', ' ').title()

        lines = [
            f"## {section_number}. {display_name}\n",
            "*Note: AI narrative generation unavailable for this section.*\n",
        ]

        for field_name, field_entries in category_data.items():
            humanized_field = field_name.replace('_', ' ').title()
            lines.append(f"### {humanized_field}")

            if not field_entries or not isinstance(field_entries, list):
                continue

            for entry in field_entries:
                if not isinstance(entry, dict):
                    continue
                fact = entry.get('fact')
                sources = entry.get('sources', [])
                source_str = ', '.join(str(s) for s in sources)
                if fact is None:
                    continue
                elif isinstance(fact, list):
                    for item in fact:
                        lines.append(f"- {item} ({source_str})")
                else:
                    lines.append(f"- {fact} ({source_str})")

            lines.append("")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Citation instruction builders
    # -------------------------------------------------------------------------

    def _build_apa_citation_instructions(self, citation_map: Dict[str, str]) -> str:
        map_lines = "\n".join(f'  - "{src}" → ({key})' for src, key in citation_map.items())
        return f"""

---

## ⚠ CITATION STYLE OVERRIDE: USE AUTHOR-DATE (APA)

**Ignore the numbered [1][2] citation rule above. Use author-date format instead.**

- Cite inline as: (Author, Year) or (Author et al., Year)
- Use the exact citation keys from this mapping:
{map_lines}
- If a source is not in the mapping, use the source name directly: (SourceName, {__import__('datetime').datetime.now().year})
- Do NOT create a References section — the system adds it automatically
- Do NOT use [1], [2], [3] style numbering anywhere

"""

    def _build_harvard_citation_instructions(self, citation_map: Dict[str, str]) -> str:
        """Harvard author-date instructions — like APA but no comma between name and year."""
        # Strip the comma from each "Author, Year" citation_map value to get
        # "Author Year" Harvard form (e.g. "Gherardi, 2006" → "Gherardi 2006").
        def _to_harvard(v: str) -> str:
            parts = v.rsplit(", ", 1)
            return " ".join(parts) if len(parts) == 2 else v

        map_lines = "\n".join(
            f'  - "{src}" → ({_to_harvard(key)})'
            for src, key in citation_map.items()
        )
        year_now = __import__('datetime').datetime.now().year
        return f"""

---

## ⚠ CITATION STYLE OVERRIDE: USE HARVARD AUTHOR-DATE

**Ignore the numbered [1][2] citation rule above. Use Harvard author-date format instead.**

- Cite inline as: (Author Year) or (Author et al. Year)  — NO comma between name and year
- Use the exact citation keys from this mapping:
{map_lines}
- If a source is not in the mapping, use the source name directly: (SourceName {year_now})
- Do NOT create a References section — the system adds it automatically
- Do NOT use [1], [2], [3] style numbering anywhere

"""

    def _build_numbered_citation_instructions(self, all_sources: List[str]) -> str:
        _db_keys = {'GBIF', 'WRiMS', 'WoRMS', 'IUCN', 'EASIN', 'AquaNIS', 'CABI'}
        _internal = {'AI-normalization', 'Unknown', 'Research Source'}

        db_sources = [s for s in all_sources if s in _db_keys]
        research_sources = [s for s in all_sources if s not in _db_keys and s not in _internal]

        citation_map: Dict[str, int] = {}
        for i, s in enumerate(db_sources, start=1):
            citation_map[s] = i
        for i, s in enumerate(research_sources, start=len(db_sources) + 1):
            citation_map[s] = i

        if not citation_map:
            return ""

        map_lines = "\n".join(
            f'  - "{src}" → [{num}]' for src, num in citation_map.items()
        )

        return f"""

---

## ⚠ CITATION NUMBERS PRE-ASSIGNED: USE EXACTLY AS SHOWN

**Ignore the general numbered citation rule above. Use these exact pre-assigned numbers.**

These numbers match the References section the system will append after your content.
Using any other numbers will cause mismatches between inline citations and the reference list.

{map_lines}

Rules:
- Match each source name you see in the JSON `sources` field to its number above.
- Multiple sources for one fact: combine as [1,2] not [1][2].
- If a source in the JSON is NOT listed above, cite it by name: (SourceName).
- Do NOT assign new numbers to any source.
- **CRITICAL:** If a source name is `AI-normalization`, `Unknown`, or `Research Source`, do NOT cite it at all — omit the citation entirely for that fact. These are internal processing labels, not real sources.

"""


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Testing NarrativeGeneratorComponent (chunked)")
    print("=" * 40)

    mock_data = {
        'taxonomic_identity': {
            'kingdom': [{'fact': 'Animalia', 'sources': ['GBIF'], 'agreement': 'consensus'}],
            'species': [{'fact': 'Procambarus clarkii', 'sources': ['GBIF'], 'agreement': 'consensus'}],
        },
        'morphological_traits': {
            'adult_size': [{'fact': 'Carapace length up to 12 cm', 'sources': ['GBIF'], 'agreement': 'single'}],
        },
    }

    generator = NarrativeGeneratorComponent()
    result = generator.run(cleaned_data=mock_data, species_name="Procambarus clarkii")

    print("\nGenerated narrative (per category):")
    print("=" * 40)
    for cat, html in result['narratives'].items():
        print(f"\n## {cat}\n{html}")
    print("\nNarrativeGeneratorComponent test completed!")
