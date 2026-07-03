#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Prompt Generator Agent (CTS Agent 2)

Generates extraction prompts for custom topics using the
Mistral-optimized template.

Part of the Custom Topic System (CTS) three-agent workflow.

Uses:
- extraction_prompt_template_mistral.md (Mistral-optimized template)
- Topic interpretation from TopicInterpreterAgent
"""

from typing import Dict, Any
from pathlib import Path
from haystack import component
from haystack.dataclasses import ChatMessage
from core.utils.generator_factory import create_generator

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "custom_prompt_generator_prompt.md"

@component
class PromptGeneratorAgent:
    """
    CTS Agent 2: Prompt Generator

    Generates extraction prompts for custom topics by filling
    the Mistral-optimized template with topic-specific content.
    """

    def __init__(self):
        """Initialize the prompt generator agent."""
        self.generator = create_generator("custom_prompt_generator")
        self._prompt_template = _PROMPT_FILE.read_text(encoding="utf-8")

        # Load extraction template for [TEMPLATE] substitution
        template_dir = Path(__file__).parent.parent / 'prompts' / 'templates'
        self.template = self._load_file(template_dir / 'extraction_prompt_template_mistral.md')

    def _load_file(self, filepath: Path) -> str:
        """Load content from a file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Could not load {filepath}: {e}")
            return ""

    @component.output_types(extraction_prompt=str, generation_status=str)
    def run(
        self,
        custom_topic: str,
        topic_interpretation: str,
        key_concepts: list,
        scope_boundaries: str,
        species_name: str = ""
    ) -> Dict[str, Any]:
        """
        Generate a complete extraction prompt for a custom topic.

        Args:
            custom_topic: The custom topic name (e.g., "invasive potential")
            topic_interpretation: Interpretation from TopicInterpreterAgent
            key_concepts: List of key concepts to prioritize
            scope_boundaries: Scope boundaries (includes/excludes)
            species_name: Optional species name for context

        Returns:
            Dict with:
                - extraction_prompt: Complete markdown extraction prompt
                - generation_status: "success" or "failed"
        """

        if not self.template:
            return {
                "extraction_prompt": "",
                "generation_status": "failed - missing template file"
            }

        species_context_str = f" (in context of {species_name})" if species_name else ""
        key_concepts_text = "\n".join(f"- {concept}" for concept in key_concepts)
        prompt = (
            self._prompt_template
            .replace("[CUSTOM_TOPIC]", custom_topic)
            .replace("[SPECIES_CONTEXT]", species_context_str)
            .replace("[TOPIC_INTERPRETATION]", topic_interpretation)
            .replace("[KEY_CONCEPTS]", key_concepts_text)
            .replace("[SCOPE_BOUNDARIES]", scope_boundaries)
            .replace("[TEMPLATE]", self.template)
        )

        try:
            # Call Mistral to generate prompt
            messages = [ChatMessage.from_user(prompt)]
            result = self.generator.run(messages=messages)

            # Extract generated prompt
            extraction_prompt = result["replies"][0].text.strip()

            # Validate that it follows the structure
            required_sections = [
                "EXTRACTION PROMPT",
                "ROLE AND TASK",
                "WHAT TO EXTRACT",
                "WHAT NOT TO EXTRACT",
                "OUTPUT FORMAT",
                "EXTRACTION EXAMPLES",
                "VERIFICATION CHECKLIST"
            ]

            missing_sections = [
                section for section in required_sections
                if section not in extraction_prompt
            ]

            if missing_sections:
                print(f"Warning: Generated prompt missing sections: {missing_sections}")

            return {
                "extraction_prompt": extraction_prompt,
                "generation_status": "success"
            }

        except Exception as e:
            return {
                "extraction_prompt": "",
                "generation_status": f"failed - {str(e)}"
            }


# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================

def generate_custom_extraction_prompt(
    custom_topic: str,
    topic_interpretation: str,
    key_concepts: list,
    scope_boundaries: str,
    species_name: str = ""
) -> str:
    """
    Convenience function to generate a custom extraction prompt.

    Args:
        custom_topic: Custom topic name
        topic_interpretation: Interpretation text
        key_concepts: List of key concepts
        scope_boundaries: Scope boundaries text
        species_name: Optional species name

    Returns:
        str: Generated extraction prompt (markdown)
    """
    generator = PromptGeneratorAgent()
    result = generator.run(
        custom_topic=custom_topic,
        topic_interpretation=topic_interpretation,
        key_concepts=key_concepts,
        scope_boundaries=scope_boundaries,
        species_name=species_name
    )

    return result["extraction_prompt"]


# ============================================================================
# TEST EXECUTION
# ============================================================================

if __name__ == "__main__":
    """Test the prompt generator agent."""

    print("=== Testing CTS Prompt Generator Agent ===\n")

    # Test with sample interpretation
    test_topic = "invasive potential"
    test_interpretation = "This topic covers risk factors and characteristics that predict invasive success, including traits, environmental tolerance, and establishment likelihood."
    test_concepts = [
        "Invasion risk factors",
        "Establishment success predictors",
        "Environmental tolerance ranges",
        "Reproductive potential in new environments",
        "Competitive advantages over native species"
    ]
    test_boundaries = "Includes: Predictive traits and risk assessments. Excludes: Actual invasion history (that's Distribution), current impacts (that's Impacts category)"
    test_species = "Dreissena polymorpha"

    print(f"Generating prompt for: '{test_topic}'")
    print(f"Species: {test_species}")
    print("-" * 80)

    generator = PromptGeneratorAgent()
    result = generator.run(
        custom_topic=test_topic,
        topic_interpretation=test_interpretation,
        key_concepts=test_concepts,
        scope_boundaries=test_boundaries,
        species_name=test_species
    )

    print(f"\nGeneration Status: {result['generation_status']}")
    print("\n" + "=" * 80)
    print("GENERATED PROMPT:")
    print("=" * 80)
    print(result['extraction_prompt'][:500] + "..." if len(result['extraction_prompt']) > 500 else result['extraction_prompt'])
    print("=" * 80)

    # Check length
    print(f"\nPrompt length: {len(result['extraction_prompt'])} characters")
    print(f"Prompt lines: {len(result['extraction_prompt'].splitlines())} lines")

    print("\n=== Test Complete ===")
