#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Topic Interpreter Agent (CTS Agent 1)

Interprets custom research topics and generates clear explanations
of what will be extracted for that topic.

Part of the Custom Topic System (CTS) three-agent workflow.

The interpretation explains:
- What concepts/keywords will be prioritized in papers
- What types of information will be considered relevant
- How the topic relates to the species context
"""

from typing import Dict, Any
from pathlib import Path
from haystack import component
from haystack.dataclasses import ChatMessage
from core.utils.generator_factory import create_generator

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "custom_topic_interpreter_prompt.md"

@component
class TopicInterpreterAgent:
    """
    CTS Agent 1: Topic Interpreter

    Interprets custom research topics and generates explanations of:
    - What types of information will be extracted
    - What keywords and concepts will be prioritized
    - What is included vs excluded from this topic
    """

    def __init__(self):
        """Initialize the topic interpreter agent."""
        self.generator = create_generator("custom_topic_interpreter")
        # Template loaded lazily inside run() — run_turn() uses an inline prompt

    def run_turn(
        self,
        custom_topic: str,
        species_name: str,
        history: list,
        questions_asked: int,
    ) -> Dict[str, Any]:
        """
        Multi-turn conversation turn for topic negotiation.

        Args:
            custom_topic: The custom research topic being negotiated
            species_name: Optional species name for context
            history: List of {"role": "ai"|"user", "text": str} dicts
            questions_asked: Number of clarifying questions already asked by the AI

        Returns:
            Dict with:
                - message: AI response text (question stripped out)
                - question: Clarifying question string, or None
                - interpretation: Updated topic interpretation
                - key_concepts: Updated list of key concepts
                - scope_boundaries: Updated scope boundaries text
        """
        species_context_str = f" for {species_name}" if species_name else ""

        # Build history block
        history_block = ""
        if history:
            lines = []
            for msg in history:
                role = "AI" if msg["role"] == "ai" else "User"
                lines.append(f"{role}: {msg['text']}")
            history_block = "\n\nCONVERSATION HISTORY:\n" + "\n\n".join(lines)

        # Question guidance based on remaining quota
        if questions_asked < 2:
            question_guidance = (
                "\nIf one key dimension of this topic is genuinely ambiguous, ask EXACTLY ONE "
                "clarifying question. Choose it from this fixed, ordered set of categories and "
                "pick the FIRST one that is actually unresolved for this topic — do not skip "
                "ahead for the sake of variety:\n"
                "  1. SCOPE — the geographic or ecological boundary of interest\n"
                "  2. DATA TYPE — the kind of evidence wanted (quantitative measurements, "
                "qualitative/descriptive observations, or both)\n"
                "  3. TIMEFRAME — the temporal window (historical, recent, or all periods)\n"
                "  4. TAXONOMY — the taxonomic scope (this species only, the genus, or a wider group)\n"
                "Phrase the question for this specific topic, but keep its intent tied to the "
                "chosen category so the same topic yields the same question on every run. "
                "Place it at the very end of your response using this exact format:\n"
                "[QUESTION]: <your question for the chosen category>\n"
                "[OPTION]: <option 1>\n"
                "[OPTION]: <option 2>\n"
                "[OPTION]: <option 3>\n"
                "Provide exactly 3 distinct options matching the canonical choices listed for "
                "that category above. Only ask if genuinely unresolved."
            )
        else:
            question_guidance = (
                "\nDo NOT ask any further questions. You have already asked the maximum allowed. "
                "Finalize your interpretation with the information available."
            )

        prompt = (
            f"You are helping a researcher define a custom research topic for data extraction "
            f"from scientific papers.\n\n"
            f"CUSTOM TOPIC: \"{custom_topic}\"{species_context_str}"
            f"{history_block}\n\n"
            f"Your task: Provide or update a clear, specific interpretation of this topic. Explain:\n"
            f"1. What types of information will be extracted from papers\n"
            f"2. What keywords and concepts will be prioritized\n"
            f"3. What is included vs excluded from this topic\n"
            f"{question_guidance}\n\n"
            f"Be specific and concrete. Focus on what would actually appear in scientific papers. "
            f"Keep the interpretation concise (2-3 sentences).\n\n"
            f"OUTPUT FORMAT (use exactly this structure):\n\n"
            f"**Topic Interpretation:**\n"
            f"[2-3 sentences explaining what this topic covers and how it will be interpreted]\n\n"
            f"**Key Concepts to Prioritize:**\n"
            f"- [Concept 1]\n"
            f"- [Concept 2]\n"
            f"- [Concept 3]\n"
            f"- [Concept 4]\n"
            f"- [Concept 5]\n\n"
            f"**Scope Boundaries:**\n"
            f"Includes: [What IS covered by this topic]\n"
            f"Excludes: [What is NOT covered]\n\n"
            f"Generate the interpretation:"
        )

        messages = [ChatMessage.from_user(prompt)]
        result = self.generator.run(messages=messages)
        response_text = result["replies"][0].text.strip()

        # Split out [QUESTION]: and [OPTION]: markers if present
        question = None
        options = []
        message = response_text
        if "[QUESTION]:" in response_text:
            q_start = response_text.find("[QUESTION]:")
            raw_question_block = response_text[q_start + len("[QUESTION]:"):].strip()
            message = response_text[:q_start].strip()

            # Separate question text from [OPTION]: lines
            question_lines = []
            for line in raw_question_block.split("\n"):
                if line.strip().startswith("[OPTION]:"):
                    opt = line.strip()[len("[OPTION]:"):].strip()
                    if opt:
                        options.append(opt)
                else:
                    question_lines.append(line)
            question = "\n".join(question_lines).strip() or None

        return {
            "message": message,
            "question": question,
            "options": options,
            "interpretation": self._extract_section(response_text, "Topic Interpretation:"),
            "key_concepts": self._extract_key_concepts(response_text),
            "scope_boundaries": self._extract_section(response_text, "Scope Boundaries:"),
        }

    @component.output_types(interpretation=str, key_concepts=list, scope_boundaries=str, full_interpretation=str)
    def run(self, custom_topic: str, species_name: str = "") -> Dict[str, Any]:
        """
        Generate an interpretation of a custom research topic.

        Args:
            custom_topic: The user's custom research topic (e.g., "invasive potential")
            species_name: Optional species name for context

        Returns:
            Dict with:
                - interpretation: Clear explanation of what will be extracted
                - key_concepts: List of keywords/concepts to prioritize
                - scope_boundaries: What is included vs excluded
        """

        species_context_str = f" for {species_name}" if species_name else ""
        prompt_template = _PROMPT_FILE.read_text(encoding="utf-8")
        prompt = (
            prompt_template
            .replace("[CUSTOM_TOPIC]", custom_topic)
            .replace("[SPECIES_CONTEXT]", species_context_str)
        )

        # Call Mistral to generate interpretation
        messages = [ChatMessage.from_user(prompt)]
        result = self.generator.run(messages=messages)

        # Parse response
        response_text = result["replies"][0].text.strip()

        # Extract sections
        interpretation = self._extract_section(response_text, "Topic Interpretation:")
        key_concepts = self._extract_key_concepts(response_text)
        scope_boundaries = self._extract_section(response_text, "Scope Boundaries:")

        return {
            "interpretation": interpretation,
            "key_concepts": key_concepts,
            "scope_boundaries": scope_boundaries,
            "full_interpretation": response_text
        }

    # The fixed section headers emitted by the prompt's OUTPUT FORMAT, in order.
    _SECTION_HEADERS = (
        "Topic Interpretation:",
        "Key Concepts to Prioritize:",
        "Scope Boundaries:",
    )

    def _extract_section(self, text: str, section_header: str) -> str:
        """Extract content from a specific section."""
        try:
            start = text.find(section_header)
            if start == -1:
                return ""

            # Content begins on the line AFTER the header line. Starting from the
            # next line avoids the header's own closing '**' bold markers.
            content_start = text.find("\n", start)
            if content_start == -1:
                return ""
            content_start += 1

            # The section ends at the next KNOWN header or the clarifying-question
            # block. Searching for the bold-wrapped form (rather than any '**')
            # is essential because the interpretation prose itself contains inline
            # **emphasis** that must not be treated as a section boundary.
            boundaries = []
            for header in self._SECTION_HEADERS:
                if header == section_header:
                    continue
                idx = text.find(f"**{header}", content_start)
                if idx != -1:
                    boundaries.append(idx)
            q_idx = text.find("[QUESTION]", content_start)
            if q_idx != -1:
                boundaries.append(q_idx)

            end = min(boundaries) if boundaries else len(text)
            return text[content_start:end].strip()

        except Exception:
            return ""

    def _extract_key_concepts(self, text: str) -> list:
        """Extract key concepts list from response."""
        try:
            start = text.find("**Key Concepts to Prioritize:**")
            if start == -1:
                return []

            # Find content between this header and next section
            content_start = start + len("**Key Concepts to Prioritize:**")
            next_section = text.find("**Scope Boundaries:**", content_start)

            if next_section == -1:
                concepts_text = text[content_start:].strip()
            else:
                concepts_text = text[content_start:next_section].strip()

            # Extract bullet points
            concepts = []
            for line in concepts_text.split('\n'):
                line = line.strip()
                if line.startswith('-') or line.startswith('•'):
                    concept = line.lstrip('-•').strip()
                    if concept:
                        concepts.append(concept)

            return concepts

        except Exception:
            return []


# ============================================================================
# TEST EXECUTION
# ============================================================================

if __name__ == "__main__":
    """Test the topic interpreter agent."""

    print("=== Testing CTS Topic Interpreter Agent ===\n")

    # Create agent
    agent = TopicInterpreterAgent()

    # Test cases
    test_topics = [
        ("invasive potential", "Dreissena polymorpha"),
        ("climate change resilience", ""),
        ("economic impact on fisheries", "Procambarus clarkii")
    ]

    for custom_topic, species_name in test_topics:
        print(f"\nTest: '{custom_topic}'" + (f" for {species_name}" if species_name else ""))
        print("-" * 80)

        result = agent.run(custom_topic=custom_topic, species_name=species_name)

        print("\nFull Interpretation:")
        print(result['full_interpretation'])
        print("\n" + "=" * 80)

    print("\n=== Tests Complete ===")
