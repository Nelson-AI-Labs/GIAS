#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Data Extraction Agent

AI-powered component that extracts structured data from markdown-formatted research papers.
Uses swappable AI generators (Mistral, Gemini, etc.) via dependency injection.

The agent focuses on extracting relevant information for a specific research topic
(e.g., biological traits, distribution, etc.) from the provided text.

Loads topic-specific extraction prompts from:
1. Session cache (for custom topics)
2. Extraction prompts directory (for predefined topics)
3. Default template (fallback)
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from haystack import component
from haystack.dataclasses import ChatMessage

# Import registries and utilities
from core.registries.topic_registry import StandardTopicRegistry
from core.registries.context_registry import ContextPromptRegistry
from core.services.species_context_service import get_wrong_species
from functionalities.extraction.utils.json_parser import parse_and_validate_extraction
from functionalities.extraction.utils.prompt_loader import load_prompt_with_fallback
from functionalities.extraction.utils.paragraph_resolver import ParagraphResolver
from functionalities.extraction.utils.tool_args import coerce_tool_args


# Mapping from research topics to prompt filenames - loaded from centralized registry
TOPIC_PROMPT_MAPPING = StandardTopicRegistry.get_prompt_file_mapping()

# Mapping from context keys to prompt filenames
CONTEXT_PROMPT_MAPPING = ContextPromptRegistry.get_prompt_file_mapping()

# Observability guard for find_passage tool calls per source-topic. All calls are
# always processed; exceeding this only logs a warning so a runaway model is visible.
_MAX_TOOL_CALLS_WARN = 200


def _classify_api_error(exc: Exception) -> tuple:
    """
    Classify an API exception into a user-facing error type and message.
    Matches on the string representation to handle Haystack's wrapped exceptions.
    Returns (error_type, user_message).
    """
    msg = str(exc).lower()
    if "429" in msg or "rate" in msg or "too many" in msg:
        return ("rate_limit", "Mistral API rate limit reached — try again in a few minutes.")
    if "503" in msg or "unavailable" in msg or ("service" in msg and "error" in msg):
        return ("service_unavailable", "Mistral AI is temporarily unavailable. Please try again shortly.")
    if "401" in msg or "unauthorized" in msg or "api key" in msg or "apikey" in msg:
        return ("auth_error", "Mistral API key rejected — check your secrets.toml.")
    if "context" in msg or "too long" in msg or ("token" in msg and ("limit" in msg or "exceed" in msg)):
        return ("token_limit", "Document too long for Mistral — the PDF may need to be split.")
    return ("unknown", f"Extraction error: {exc}")


@component
class DataExtractionAgent:
    """
    Haystack component that uses AI to extract structured data from markdown text.

    The AI generator is injected at initialization, allowing easy swapping between
    Mistral, Gemini, OpenAI, or other providers following the Haystack pattern.
    """

    def __init__(
        self,
        generator: Any,
        prompts_directory: Optional[str] = None,
        coverage_check: bool = True,
        bm25_alpha: float | None = None,
    ):
        """
        Initialize the data extraction agent.

        Args:
            generator: Any Haystack ChatGenerator (MistralChatGenerator,
                      GoogleAIGeminiChatGenerator, OpenAIChatGenerator, etc.)
            prompts_directory: Optional path to directory containing prompt files.
                              If None, uses default location: components/SEP_components/extraction prompts/
            coverage_check: If True, run a second LLM pass after initial extraction to
                            catch facts the first pass missed. Improves recall at the cost
                            of one additional LLM call per source-topic pair.
            bm25_alpha: Override BM25 weight in hybrid scoring. None → default (0.85).
                        Pass 0.50 for context extraction where fields are terse metadata
                        with zero BM25 token overlap.
        """
        self.generator = generator
        self.coverage_check = coverage_check
        self._bm25_alpha = bm25_alpha
        # Optional callback(label) — set externally before pipeline.run().
        self.progress_callback = None

        # Set prompts directory for topic-specific prompts
        if prompts_directory is None:
            # Default to extraction/prompts/topics/ (relative to extraction/ module root)
            self.prompts_directory = os.path.join(
                os.path.dirname(__file__),
                '..',
                'prompts',
                'topics'
            )
        else:
            self.prompts_directory = prompts_directory

        # Context prompts directory (default to extraction/prompts/contexts/)
        self.context_prompts_directory = os.path.join(
            os.path.dirname(__file__),
            '..',
            'prompts',
            'contexts'
        )

        # Cache for loaded prompts (shared between topic and context prompts)
        self._prompt_cache = {}

    @component.output_types(
        extracted_data=Dict[str, Any],
        extraction_status=str,
        error_message=Optional[str],
        error_type=Optional[str],
        fields_extracted=int
    )
    def run(
        self,
        markdown_text: str,
        species_name: str,
        research_topic: str,
        search_terms: List[str],
        universal_id: str = "",
        session_id: Optional[str] = None,
        synonym_list: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Extract structured data from markdown text using AI.

        Args:
            markdown_text: Markdown-formatted text from PDF
            species_name: Name of the species being researched
            research_topic: Research topic (e.g., "biological characteristics")
            search_terms: List of search terms used to find this source
            universal_id: Universal species ID for species context cache lookup
            session_id: Explicit session ID for species context cache path (pass from
                        pipeline caller to avoid Streamlit thread-context loss)
            synonym_list: All valid name variants for this species (from species_resolver)

        Returns:
            Dict containing:
                - extracted_data: Dict with format {field_name: {value, reasoning}}
                - extraction_status: "success" or "failed"
                - error_message: Error description if failed, None otherwise
                - fields_extracted: Number of fields successfully extracted
        """
        if self.progress_callback:
            self.progress_callback("Extracting data")
        try:
            # Build paragraph index for this document (used by find_passage tool)
            resolver = ParagraphResolver(markdown_text, bm25_alpha=self._bm25_alpha)
            find_passage_tool = resolver.make_haystack_tool()

            # Build the extraction prompt
            prompt = self._build_prompt(
                markdown_text=markdown_text,
                species_name=species_name,
                research_topic=research_topic,
                search_terms=search_terms,
                universal_id=universal_id,
                session_id=session_id,
                synonym_list=synonym_list
            )

            # First pass: call LLM — makes parallel find_passage tool calls, one per fact.
            messages = [ChatMessage.from_user(prompt)]
            result = self.generator.run(messages=messages, tools=[find_passage_tool])
            assistant_msg = result["replies"][0]

            tool_calls = assistant_msg.tool_calls or []

            if not tool_calls:
                # LLM found nothing relevant in this document — valid empty result
                return {
                    "extracted_data": {},
                    "extraction_status": "success",
                    "error_message": None,
                    "fields_extracted": 0
                }

            extracted_data = self._collect_tool_calls(tool_calls, find_passage_tool)

            # Coverage check pass: ask the LLM to review what it may have missed.
            # Uses a fresh ParagraphResolver so dedup state from the first pass doesn't
            # prevent the second pass from retrieving already-used paragraphs.
            if self.coverage_check and extracted_data:
                fresh_resolver = ParagraphResolver(markdown_text, bm25_alpha=self._bm25_alpha)
                fresh_tool = fresh_resolver.make_haystack_tool()
                coverage_prompt = self._build_coverage_prompt(
                    markdown_text=markdown_text,
                    species_name=species_name,
                    research_topic=research_topic,
                    already_extracted=list(extracted_data.keys())
                )
                cov_result = self.generator.run(
                    messages=[ChatMessage.from_user(coverage_prompt)],
                    tools=[fresh_tool]
                )
                cov_calls = (cov_result["replies"][0].tool_calls or [])
                if cov_calls:
                    new_fields = self._collect_tool_calls(cov_calls, fresh_tool)
                    added = 0
                    for field_name, field_data in new_fields.items():
                        # Skip fields whose passage duplicates a first-pass result
                        if field_name not in extracted_data and field_data.get("candidate_source_quote"):
                            extracted_data[field_name] = field_data
                            added += 1
                    if added:
                        print(f"[CoverageCheck] Added {added} new field(s) in second pass")

            fields_found = sum(1 for f in extracted_data.values() if f.get("candidate_source_quote"))
            return {
                "extracted_data": extracted_data,
                "extraction_status": "success",
                "error_message": None,
                "fields_extracted": fields_found
            }

        except Exception as e:
            error_type, user_message = _classify_api_error(e)
            return {
                "extracted_data": {},
                "extraction_status": "failed",
                "error_message": user_message,
                "error_type": error_type,
                "fields_extracted": 0
            }

    def _collect_tool_calls(
        self,
        tool_calls: list,
        find_passage_tool: Any,
    ) -> Dict[str, Any]:
        """Execute a list of find_passage tool calls and return the extracted data dict."""
        extracted_data: Dict[str, Any] = {}
        # Process every tool call — never silently drop facts. The model's own
        # per-response output budget bounds how many it can emit; the ceiling below
        # is an observability guard that warns (does not truncate) on abnormal counts.
        if len(tool_calls) > _MAX_TOOL_CALLS_WARN:
            print(f"[DataExtraction] WARNING: {len(tool_calls)} tool calls "
                  f"(> {_MAX_TOOL_CALLS_WARN}) — processing all; unusually high, "
                  f"check for runaway extraction.")
        for tc in tool_calls:
            args = coerce_tool_args(tc)
            if args is None:
                continue
            field_name = (args.get("field_name") or f"field_{len(extracted_data)}").strip()
            reasoning = args.get("reasoning", "").strip()
            llm_value = args.get("value", "").strip()

            raw = find_passage_tool.invoke(**args)
            passage = json.loads(raw)

            if passage.get("found"):
                extracted_data[field_name] = {
                    "reasoning": reasoning,
                    "candidate_source_quote": passage["text"],
                    # Prefer the LLM's concise value (context extraction) over raw passage.
                    # Topic extraction prompts don't set 'value', so passage text is used.
                    "value": llm_value if llm_value else passage["text"],
                    "pdf_page_index": passage["page_index"],
                }
            else:
                # No matching paragraph — mark as unresolved so verification drops it
                extracted_data[field_name] = {
                    "reasoning": reasoning,
                    "candidate_source_quote": "",
                }
        return extracted_data

    def _build_coverage_prompt(
        self,
        markdown_text: str,
        species_name: str,
        research_topic: str,
        already_extracted: List[str],
    ) -> str:
        """Build the second-pass prompt that asks the LLM to find missed facts."""
        field_list = "\n".join(f"- {f}" for f in already_extracted)
        return f"""You are reviewing a research paper for additional facts about **{species_name}** on the topic **{research_topic}**.

The following fields were already extracted in a first pass:
{field_list}

Review the paper text below. Are there any additional facts about **{species_name}** related to **{research_topic}** that are NOT covered by the fields listed above?

Call find_passage ONLY for genuinely new, distinct facts that were missed. If all relevant facts have already been captured, do not make any tool calls.

---

**RESEARCH PAPER TEXT:**

{markdown_text}"""

    def _build_prompt(
        self,
        markdown_text: str,
        species_name: str,
        research_topic: str,
        search_terms: List[str],
        universal_id: str = "",
        session_id: Optional[str] = None,
        synonym_list: Optional[List[str]] = None
    ) -> str:
        """
        Build the extraction prompt for the AI.

        Loads topic-specific prompt from file if available, otherwise uses default.
        Injects species name, synonym list, and wrong-species examples into the template.

        Args:
            markdown_text: The text to extract from
            species_name: Species being researched
            research_topic: Topic to focus on
            search_terms: Search terms used to find this source
            universal_id: Universal species ID for species context cache lookup
            session_id: Explicit session ID for cache path
            synonym_list: All valid name variants for this species (from species_resolver)

        Returns:
            Complete prompt string
        """
        # Load topic-specific prompt
        prompt_template = self._load_prompt_for_topic(research_topic)

        # Build synonym string — italicised list for prompt readability
        if synonym_list and len(synonym_list) > 1:
            synonym_str = ", ".join(f"*{s}*" for s in synonym_list)
        else:
            synonym_str = f"*{species_name}*"

        # Inject species name, synonyms, and wrong-species examples into the template
        wrong_species = get_wrong_species(species_name, universal_id, session_id=session_id) if universal_id else {}
        prompt_template = prompt_template.replace("[SPECIES_NAME]", species_name)
        prompt_template = prompt_template.replace("[SYNONYM_LIST]", synonym_str)
        prompt_template = prompt_template.replace("[OTHER_SPECIES_1]", wrong_species.get("other_species_1", "[OTHER_SPECIES_1]"))
        prompt_template = prompt_template.replace("[OTHER_SPECIES_2]", wrong_species.get("other_species_2", "[OTHER_SPECIES_2]"))

        # Format search terms
        search_terms_str = ", ".join(f'"{term}"' for term in search_terms)

        # Build complete prompt — no JSON response block needed; the LLM responds
        # via find_passage tool calls rather than a freeform JSON reply.
        prompt = f"""You are extracting information about **{species_name}** for the research topic: **{research_topic}**.

**Search Terms Used to Find This Source:** {search_terms_str}

---

{prompt_template}

---

**RESEARCH PAPER TEXT:**

{markdown_text}"""

        return prompt

    def _load_prompt_for_topic(self, research_topic: str) -> str:
        """
        Load prompt from file for a given topic or context key.

        Uses the consolidated prompt_loader utility for hierarchical loading:
        1. Memory cache (previously loaded prompts)
        2. Session cache (for custom topic prompts)
        3. Predefined topic prompts directory (StandardTopicRegistry)
        4. Context prompts directory (ContextPromptRegistry)

        Args:
            research_topic: Research topic string or context key (e.g., "geographic_context")

        Returns:
            Prompt content from file
        """
        # Use consolidated utility function
        prompt_content, source_type = load_prompt_with_fallback(
            topic_key=research_topic,
            topic_registry=StandardTopicRegistry,
            context_registry=ContextPromptRegistry,
            prompts_directory=self.prompts_directory,
            context_prompts_directory=self.context_prompts_directory,
            cache=self._prompt_cache
        )

        return prompt_content


    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse the AI response into structured data with robust error recovery.

        Uses the consolidated json_parser utility for parsing and validation.

        Args:
            response_text: Raw text response from AI

        Returns:
            Parsed dictionary with extracted data

        Raises:
            json.JSONDecodeError: If response is not valid JSON after all recovery attempts
        """
        # Use consolidated utility function
        return parse_and_validate_extraction(response_text, strict=True)
