#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Extraction Verification Agent

Custom Haystack component that verifies extracted facts against source text.
Uses direct Mistral API calls with structured JSON output format.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING
from haystack import component
from haystack.dataclasses import ChatMessage

from functionalities.extraction.utils.output_saver import get_source_folder
from functionalities.extraction.utils.json_parser import recover_json_from_response
from functionalities.extraction.utils.tool_args import coerce_tool_args
from core.services.species_context_service import get_wrong_species

if TYPE_CHECKING:
    from functionalities.extraction.utils.paragraph_resolver import ParagraphResolver

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "verification_prompt.md"

# Observability guard for verifier context look-ups. All look-ups are always
# processed; exceeding this only logs a warning, it does not truncate.
_MAX_VERIFY_LOOKUPS_WARN = 50


@component
class ExtractionVerificationAgent:
    """
    Verifies extracted data against source text using custom Mistral prompts.

    Simpler than LLMEvaluator - directly calls Mistral with verification prompt
    and parses JSON response.
    """

    def __init__(self, generator):
        """
        Initialize verification agent.

        Args:
            generator: Haystack ChatGenerator (MistralChatGenerator, etc.)
        """
        self.generator = generator
        self._prompt_template = _PROMPT_FILE.read_text(encoding="utf-8")
        # Optional callback(label) — set externally before pipeline.run().
        self.progress_callback = None

        # Track IDs for cache saving
        self.universal_id = None
        self.source_id = None
        self.source_title = None
        self.research_topic = None
        self.extracted_data_dir = None

    @component.output_types(
        verified_data=Dict[str, Any],
        removed_fields=Dict[str, Any],
        removed_hallucinations=list,
        removed_wrong_species=list,
        verification_report=Dict[str, Any],
        fields_removed_count=int
    )
    def run(
        self,
        extracted_data: Dict[str, Any],
        source_text: str = "",  # kept for backward compatibility; no longer used by the prompt
        species_name: str = "",
        research_topic: str = "",
        universal_id: Optional[str] = None,
        source_id: Optional[str] = None,
        source_title: Optional[str] = None,
        extracted_data_dir: Optional[Path] = None,
        session_id: Optional[str] = None,
        paragraph_resolver: Optional[Any] = None,  # ParagraphResolver; typed as Any to avoid circular import
    ) -> Dict[str, Any]:
        """
        Verify extracted data against source text.

        Args:
            extracted_data: Dict with format {field_name: {value, reasoning}}
            source_text: Markdown text from PDF
            species_name: Species being researched
            research_topic: Research topic
            universal_id: Species universal ID (for cache path)
            source_id: Source identifier (for cache filename)
            source_title: Source title (for per-source folder naming)
            extracted_data_dir: Pre-resolved extracted data directory (for thread safety)
            session_id: Explicit session ID for species context cache path

        Returns:
            Dict containing:
                - verified_data: Fields that passed both verification checks
                - removed_fields: All fields that were removed (hallucinations + wrong species)
                - removed_hallucinations: Field names removed because value was not in source
                - removed_wrong_species: Field names removed because value was about another species
                - verification_report: Per-field verification details
                - fields_removed_count: Number of fields removed
        """
        # Store IDs for cache saving
        self.universal_id = universal_id
        self.source_id = source_id or "unknown"
        self.source_title = source_title or ""
        self.research_topic = research_topic
        self.extracted_data_dir = extracted_data_dir

        if not extracted_data:
            # Nothing to verify: return before emitting the progress label so the UI
            # does not show "Verifying facts" for a source that produced no data.
            return {
                "verified_data": {},
                "removed_fields": {},
                "removed_hallucinations": [],
                "removed_wrong_species": [],
                "verification_report": {},
                "fields_removed_count": 0
            }

        if self.progress_callback:
            self.progress_callback("Verifying facts")

        # A ParagraphResolver cannot travel through a Haystack connection (complex
        # object), so when one is not supplied, build a fresh one from source_text.
        if paragraph_resolver is None and source_text:
            from functionalities.extraction.utils.paragraph_resolver import ParagraphResolver
            paragraph_resolver = ParagraphResolver(source_text)

        # Separate fields by whether anchor resolution found a passage.
        # Fields without a candidate_source_quote are auto-removed — no Mistral call needed.
        fields_with_passage = {
            name: content for name, content in extracted_data.items()
            if isinstance(content, dict) and content.get("candidate_source_quote")
        }
        fields_without_passage = {
            name: content for name, content in extracted_data.items()
            if name not in fields_with_passage
        }

        # Pre-verifier: flag duplicate source passages across sibling fields.
        # When the same verbatim passage fills ≥2 different field labels, the LLM
        # is padding coverage by reusing one paragraph. Keep the first occurrence;
        # mark the rest as duplicate_source so they skip the Mistral call.
        fields_with_passage, duplicate_removed = self._deduplicate_passages(fields_with_passage)

        verified_data = {}
        removed_fields = {}
        removed_hallucinations = []
        removed_wrong_species = []
        removed_duplicates = []
        verification_report = {}

        # Absorb pre-verifier duplicates into removed_fields
        for field_name, field_content in duplicate_removed.items():
            removed_duplicates.append(field_name)
            removed_hallucinations.append(field_name)
            removed_fields[field_name] = {
                **field_content,
                "removal_reason": "duplicate_source",
                "confidence": "high",
                "source_quote": field_content.get("candidate_source_quote", "")
            }
            verification_report[field_name] = {
                "verdict": "duplicate_source",
                "confidence": "high",
                "note": "identical passage already assigned to a sibling field"
            }

        # Auto-remove fields whose anchor was not found in the document
        for field_name, field_content in fields_without_passage.items():
            if not isinstance(field_content, dict):
                continue  # Non-dict entries cannot be spread; skip silently
            removed_hallucinations.append(field_name)
            removed_fields[field_name] = {
                **field_content,
                "removal_reason": "passage_not_found",
                "confidence": "low",
                "source_quote": ""
            }
            verification_report[field_name] = {
                "verdict": "passage_not_found",
                "confidence": "low",
                "note": "passage could not be located in the source document"
            }

        if not fields_with_passage:
            # Nothing left to verify with Mistral
            if removed_fields and self.universal_id:
                self._save_removed_fields(removed_fields, removed_hallucinations, removed_wrong_species, removed_duplicates, species_name)
            return {
                "verified_data": verified_data,
                "removed_fields": removed_fields,
                "removed_hallucinations": removed_hallucinations,
                "removed_wrong_species": removed_wrong_species,
                "verification_report": verification_report,
                "fields_removed_count": len(removed_fields)
            }

        # Build verification prompt with only fields that have passages
        prompt = self._build_verification_prompt(
            extracted_data=fields_with_passage,
            species_name=species_name,
            research_topic=research_topic,
            universal_id=universal_id or "",
            session_id=session_id
        )

        try:
            messages = [ChatMessage.from_user(prompt)]

            # If a ParagraphResolver is provided, wire find_passage as a tool so
            # the LLM can look up additional context when species attribution is
            # ambiguous (e.g. to check the Methods section for species list).
            find_passage_tool = paragraph_resolver.make_haystack_tool() if paragraph_resolver else None

            if find_passage_tool:
                result = self.generator.run(messages=messages, tools=[find_passage_tool])
            else:
                result = self.generator.run(messages=messages)

            assistant_msg = result["replies"][0]
            tool_calls = getattr(assistant_msg, "tool_calls", None) or []

            if tool_calls and find_passage_tool:
                # LLM requested additional document context — execute every lookup
                # and feed results back. Never silently drop; the ceiling below only
                # warns (does not truncate) if the count is abnormally high.
                if len(tool_calls) > _MAX_VERIFY_LOOKUPS_WARN:
                    print(f"[VerificationAgent] WARNING: {len(tool_calls)} context "
                          f"lookups (> {_MAX_VERIFY_LOOKUPS_WARN}) — processing all.")
                tool_results = []
                for tc in tool_calls:
                    args = coerce_tool_args(tc)
                    if args is None:
                        continue
                    raw = find_passage_tool.invoke(**args)
                    tool_results.append(ChatMessage.from_tool(raw, origin=tc))
                    print(f"[VerificationAgent] Cross-reference lookup: {args.get('query', '')[:60]!r}")

                messages_with_context = messages + [assistant_msg] + tool_results
                result2 = self.generator.run(messages=messages_with_context)
                response_text = result2["replies"][0].text.strip()
            else:
                response_text = (assistant_msg.text or "").strip()

            # Parse JSON response
            verdicts = self._parse_verification_response(response_text)

            for field_name, field_content in fields_with_passage.items():
                # source_quote is the Python-extracted verbatim passage, not Mistral's output
                source_quote = field_content.get("candidate_source_quote", "")

                if field_name in verdicts:
                    verdict_info = verdicts[field_name]
                    verdict = verdict_info.get("verdict", "unverified").lower()
                    confidence = verdict_info.get("confidence", "low").lower()

                    # Store in report (include passage for traceability)
                    verification_report[field_name] = {**verdict_info, "source_quote": source_quote}

                    # Decide keep or remove
                    if verdict == "verified" or (verdict == "partial" and confidence in ["medium", "high"]):
                        # Strip internal keys; value == source_quote == passage (set by find_passage tool)
                        _internal = ("candidate_source_quote", "text_anchor")
                        clean = {k: v for k, v in field_content.items() if k not in _internal}
                        # Trim the rendered value to the sentences where the target
                        # species participates (the verifier returns cleaned_value for
                        # kept fields). This drops co-mentioned other-species sentences
                        # that would otherwise be attributed to the target. The wide
                        # source_quote is kept intact as verification/citation evidence.
                        cleaned_value = (verdict_info.get("cleaned_value") or "").strip()
                        if cleaned_value:
                            clean["value"] = cleaned_value
                        verified_data[field_name] = {
                            **clean,
                            "source_quote": source_quote,
                            "verification_verdict": verdict,
                            "verification_confidence": confidence,
                        }
                    elif verdict == "wrong_species":
                        removed_wrong_species.append(field_name)
                        removed_fields[field_name] = {
                            **field_content,
                            "removal_reason": "wrong_species",
                            "confidence": confidence,
                            "source_quote": source_quote
                        }
                    elif verdict == "synthesized":
                        removed_hallucinations.append(field_name)
                        removed_fields[field_name] = {
                            **field_content,
                            "removal_reason": "synthesized",
                            "confidence": confidence,
                            "source_quote": source_quote
                        }
                    else:
                        # unverified / partial-low / figure_reference / anything else → hallucination
                        removed_hallucinations.append(field_name)
                        removed_fields[field_name] = {
                            **field_content,
                            "removal_reason": verdict,
                            "confidence": confidence,
                            "source_quote": source_quote
                        }
                else:
                    # No verdict from Mistral - keep to be safe, attach source_quote
                    _internal = ("candidate_source_quote", "text_anchor")
                    clean = {k: v for k, v in field_content.items() if k not in _internal}
                    verified_data[field_name] = {**clean, "source_quote": source_quote}
                    verification_report[field_name] = {
                        "verdict": "no_verdict",
                        "note": "Kept by default",
                        "source_quote": source_quote
                    }

            # Save removed fields to cache
            if removed_fields and self.universal_id:
                self._save_removed_fields(removed_fields, removed_hallucinations, removed_wrong_species, removed_duplicates, species_name)

            return {
                "verified_data": verified_data,
                "removed_fields": removed_fields,
                "removed_hallucinations": removed_hallucinations,
                "removed_wrong_species": removed_wrong_species,
                "verification_report": verification_report,
                "fields_removed_count": len(removed_fields)
            }

        except Exception as e:
            print(f"WARNING: Verification failed: {e}")
            print(f"         Keeping all fields to avoid false removals")
            # Strip internal anchor resolver keys so downstream consumers get the clean schema
            _internal = ("candidate_source_quote", "text_anchor")
            clean_fallback = {
                name: {k: v for k, v in content.items() if k not in _internal}
                if isinstance(content, dict) else content
                for name, content in extracted_data.items()
            }
            return {
                "verified_data": clean_fallback,
                "removed_fields": {},
                "removed_hallucinations": [],
                "removed_wrong_species": [],
                "verification_report": {"error": str(e)},
                "fields_removed_count": 0
            }

    @staticmethod
    def _deduplicate_passages(
        fields: Dict[str, Any]
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Detect fields that share an identical source passage.

        When ≥2 fields quote the exact same verbatim passage (after whitespace
        normalisation and line-number strip) the LLM has padded coverage by
        reusing one paragraph for multiple labels. Keep the first occurrence;
        return the rest as `duplicate_removed` so they skip Mistral and go
        straight into removed_fields.

        Returns:
            (deduplicated_fields, duplicate_removed)
        """
        seen_passages: dict[str, str] = {}  # normalised_passage → first field_name
        kept: Dict[str, Any] = {}
        dupes: Dict[str, Any] = {}

        for field_name, content in fields.items():
            if not isinstance(content, dict):
                kept[field_name] = content
                continue
            raw = content.get("candidate_source_quote", "")
            # Normalise: collapse whitespace, strip bare line numbers
            normalised = re.sub(r'\s+', ' ', re.sub(r'\b\d{1,4}\b', '', raw)).strip()

            if len(normalised) < 80:
                # Short passages — don't deduplicate, overlap may be coincidental
                kept[field_name] = content
                continue

            if normalised in seen_passages:
                print(
                    f"[VerificationAgent] Duplicate passage: '{field_name}' "
                    f"shares passage with '{seen_passages[normalised]}' — removing"
                )
                dupes[field_name] = content
            else:
                seen_passages[normalised] = field_name
                kept[field_name] = content

        return kept, dupes

    def _build_verification_prompt(
        self,
        extracted_data: Dict[str, Any],
        species_name: str,
        research_topic: str,
        universal_id: str = "",
        session_id: Optional[str] = None
    ) -> str:
        """Build verification prompt. Each field shows its verbatim passage and reasoning.
        Value == passage by construction — no separate value line needed."""
        wrong_species = get_wrong_species(species_name, universal_id, session_id=session_id) if universal_id else {}
        other_species_1 = wrong_species.get("other_species_1", "Astacus astacus")

        field_lines = []
        for field_name, content in extracted_data.items():
            if not isinstance(content, dict):
                continue
            passage = content.get("candidate_source_quote", "")
            reasoning = content.get("reasoning", "")
            value = content.get("value", "")
            # Include synthesized value when it differs from the raw passage
            # (context extraction provides a concise answer; topic extraction does not).
            if value and value != passage:
                field_lines.append(
                    f"- **{field_name}**:\n"
                    f"  Extracted value: \"{value}\"\n"
                    f"  Supporting passage: \"{passage}\"\n"
                    f"  Reasoning: \"{reasoning}\""
                )
            else:
                field_lines.append(
                    f"- **{field_name}**:\n"
                    f"  Source passage: \"{passage}\"\n"
                    f"  Reasoning: \"{reasoning}\""
                )
        fields_text = "\n\n".join(field_lines)

        return (
            self._prompt_template
            .replace("[SPECIES_NAME]", species_name)
            .replace("[RESEARCH_TOPIC]", research_topic)
            .replace("[OTHER_SPECIES_1]", other_species_1)
            .replace("[FIELDS_TEXT]", fields_text)
        )

    def _parse_verification_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON verification response using shared json_parser utility."""
        try:
            verdicts, _ = recover_json_from_response(response_text)
            return verdicts
        except json.JSONDecodeError as e:
            print(f"WARNING: Failed to parse verification JSON: {e}")
            print(f"         Response: {response_text[:500]}")
            return {}

    def _save_removed_fields(
        self,
        removed_fields: Dict[str, Any],
        removed_hallucinations: list,
        removed_wrong_species: list,
        removed_duplicates: list,
        species_name: str
    ):
        """Save removed fields to per-source folder for user review."""
        try:
            # Get per-source directory
            output_dir = get_source_folder(self.universal_id, self.source_id, self.source_title, self.extracted_data_dir)

            # Create filename (source_id is in folder name, not filename)
            topic_safe = self.research_topic.lower().replace(' ', '_')
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"removed_fields_{topic_safe}_{timestamp}.json"
            filepath = output_dir / filename

            # Prepare output data
            output_data = {
                "metadata": {
                    "species_name": species_name,
                    "universal_id": self.universal_id,
                    "research_topic": self.research_topic,
                    "source_id": self.source_id,
                    "removal_timestamp": datetime.now().isoformat(),
                    "fields_removed_count": len(removed_fields),
                    "hallucinations_removed": len(removed_hallucinations),
                    "wrong_species_removed": len(removed_wrong_species),
                    "duplicates_removed": len(removed_duplicates),
                    "removed_hallucination_fields": removed_hallucinations,
                    "removed_wrong_species_fields": removed_wrong_species,
                    "removed_duplicate_fields": removed_duplicates
                },
                "removed_fields": removed_fields
            }

            # Save to file
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            halluc_count = len(removed_hallucinations)
            species_count = len(removed_wrong_species)
            dup_count = len(removed_duplicates)
            print(f"Saved {len(removed_fields)} removed field(s) to: {filepath} "
                  f"({halluc_count} hallucination(s), {species_count} wrong-species, {dup_count} duplicate(s))")

        except Exception as e:
            print(f"WARNING: Failed to save removed fields: {e}")
