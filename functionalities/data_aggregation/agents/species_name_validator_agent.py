#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Name Validator Agent

AI-powered agent that validates and corrects species names using Mistral AI.
Handles:
- Spell checking and correction
- Common name to Latin name translation
- Name validation against taxonomic databases
"""

import json
from typing import Dict, Any
from pydantic import BaseModel, Field
from haystack import component
from haystack.dataclasses import ChatMessage
from functionalities.extraction.utils.json_parser import recover_json_from_response
from core.utils.generator_factory import create_generator


class SpeciesValidationResponse(BaseModel):
    """Pydantic model for Mistral AI response validation."""

    class Config:
        """Reject any field not declared on the model."""
        extra = "forbid"

    corrected_name: str = Field(
        description="Corrected scientific name in Latin binomial format (Genus species)"
    )
    translation_applied: bool = Field(
        description="Whether common name to Latin translation was performed"
    )
    confidence: str = Field(
        description="Confidence level: high, medium, or low"
    )
    explanation: str = Field(
        description="Brief plain-text explanation without special formatting characters"
    )


@component
class SpeciesNameValidatorAgent:
    """
    AI agent that validates and corrects species names.

    Uses Mistral AI to:
    1. Validate and correct misspelled scientific names
    2. Translate common names to Latin scientific names
    3. Assess confidence in the validation result
    """

    def __init__(self):
        """Create the Mistral generator used for name validation."""
        self.generator = create_generator("species_name_validator")

    @component.output_types(corrected_name=str, translation_applied=bool, confidence=str, original_input=str, explanation=str)
    def run(self, user_input: str) -> Dict[str, Any]:
        """
        Validate and correct a species name input.

        Args:
            user_input: User's input (scientific name, common name, or misspelled name)

        Returns:
            Dictionary with:
                - corrected_name: str - The corrected scientific name
                - translation_applied: bool - Whether common→Latin translation was done
                - confidence: str - "high", "medium", or "low"
                - original_input: str - The original user input
                - explanation: str - Human-readable explanation of changes

        Examples:
            >>> agent = SpeciesNameValidatorAgent()
            >>> result = agent.validate("Red Swamp Crayfish")
            >>> print(result['corrected_name'])
            'Procambarus clarkii'
            >>> print(result['translation_applied'])
            True

            >>> result = agent.validate("Procamabrus clarkii")  # misspelled
            >>> print(result['corrected_name'])
            'Procambarus clarkii'
            >>> print(result['translation_applied'])
            False
        """
        prompt = self._build_validation_prompt(user_input)
        messages = [ChatMessage.from_user(prompt)]

        try:
            response = self.generator.run(messages=messages)
            ai_response = response['replies'][0].text
            result = self._parse_ai_response(ai_response, user_input)

            print(f"  Original: '{user_input}'")
            print(f"  Corrected: '{result['corrected_name']}'")
            print(f"  Confidence: {result['confidence']}")

            return result

        except Exception as e:
            print(f"ERROR SpeciesNameValidatorAgent: Validation failed: {e}")
            return {
                'corrected_name': user_input,
                'translation_applied': False,
                'confidence': 'low',
                'original_input': user_input,
                'explanation': f"Validation failed: {str(e)}. Using original input."
            }

    def _build_validation_prompt(self, user_input: str) -> str:
        prompt = f"""You are a taxonomic expert specializing in species identification and nomenclature.

CRITICAL OUTPUT FORMAT REQUIREMENTS:
- Your response MUST be a valid JSON object
- Do NOT wrap your response in markdown code blocks (no triple backticks)
- Do NOT use asterisks, bullets, or special formatting in the explanation field
- Use plain text only in all string fields
- Ensure all special characters are properly escaped

Your task: Validate and correct the following species name input.

User input: "{user_input}"

Instructions:
1. Determine if the input is:
   - A scientific name (Latin binomial) - correct if needed
   - A common name - translate to the accepted scientific name
   - A misspelled name - correct the spelling

2. Provide the ACCEPTED scientific name (Latin binomial format: Genus species)
   - First word capitalized, second word lowercase, no author names or dates

3. Assess your confidence:
   - "high": You are very confident in the identification
   - "medium": The identification is likely correct but has some uncertainty
   - "low": The input is ambiguous or unclear

4. Provide a brief explanation of what you did

Return your response as VALID JSON in this exact format (no markdown, no code blocks):
{{
  "corrected_name": "Genus species",
  "translation_applied": true,
  "confidence": "high",
  "explanation": "Brief explanation of what you did"
}}

Example 1 - Common name translation:
Input: "Red Swamp Crayfish"
{{
  "corrected_name": "Procambarus clarkii",
  "translation_applied": true,
  "confidence": "high",
  "explanation": "Translated common name Red Swamp Crayfish to accepted scientific name."
}}

Example 2 - Spelling correction:
Input: "Procamabrus clarkii"
{{
  "corrected_name": "Procambarus clarkii",
  "translation_applied": false,
  "confidence": "high",
  "explanation": "Corrected spelling from Procamabrus to Procambarus."
}}

Example 3 - Already correct:
Input: "Vespa velutina"
{{
  "corrected_name": "Vespa velutina",
  "translation_applied": false,
  "confidence": "high",
  "explanation": "Name is already correct."
}}

Now process the user input: "{user_input}"

IMPORTANT: Return ONLY the JSON object. No markdown code blocks. No triple backticks. No additional text."""

        return prompt

    def _parse_ai_response(self, ai_response: str, original_input: str) -> Dict[str, Any]:
        try:
            result, _ = recover_json_from_response(ai_response)

            required_fields = ['corrected_name', 'translation_applied', 'confidence', 'explanation']
            for field in required_fields:
                if field not in result:
                    raise ValueError(f"Missing required field: {field}")

            result['original_input'] = original_input

            if result['confidence'] not in ['high', 'medium', 'low']:
                print(f"  WARNING: Invalid confidence '{result['confidence']}', defaulting to 'medium'")
                result['confidence'] = 'medium'

            return result

        except Exception as e:
            print(f"ERROR SpeciesNameValidatorAgent: Response processing failed: {e}")
            print(f"  Raw response (first 500 chars): {ai_response[:500]}")
            raise ValueError(f"Failed to process AI response: {e}\nResponse: {ai_response}")


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    print("=== Testing SpeciesNameValidatorAgent ===\n")

    agent = SpeciesNameValidatorAgent()

    test_cases = [
        "Red Swamp Crayfish",   # Common name
        "Procamabrus clarkii",  # Misspelled
        "Procambarus clarkii",  # Correct
        "Vespa velutina",       # Correct, different species
        "Asian Hornet",         # Common name
    ]

    for test_input in test_cases:
        print(f"\n{'='*60}")
        print(f"Testing: '{test_input}'")
        print('='*60)

        result = agent.run(user_input=test_input)

        print("\nResult:")
        print(f"  Corrected Name: {result['corrected_name']}")
        print(f"  Translation Applied: {result['translation_applied']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Explanation: {result['explanation']}")

    print("\n=== Tests Complete ===")
