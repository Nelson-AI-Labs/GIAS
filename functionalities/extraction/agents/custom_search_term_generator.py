#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Search Term Generator Agent
Generates intelligent search terms for invasive species research using AI.
"""

from typing import List, Dict, Any
from pathlib import Path
from haystack import component
from haystack.dataclasses import ChatMessage
from core.utils.generator_factory import create_generator

_PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "custom_search_terms_prompt.md"

@component
class SearchTermGeneratorAgent:
    """
    Agent that generates targeted search terms using AI based on research topic and optional species name.
    """

    def __init__(self):
        """Initialize the search term generator agent."""
        self.generator = create_generator("custom_search_term_generator")
        self._prompt_template = _PROMPT_FILE.read_text(encoding="utf-8")
    
    @component.output_types(search_terms=List[str], research_topic=str, species_name=str)
    def run(self, 
            research_topic: str,
            species_name: str,
            num_terms: int = 5) -> Dict[str, Any]:
        """
        Generate targeted search terms using AI based on research topic and species name.
        
        Args:
            research_topic: Research focus area
            species_name: Scientific name of the species (required)
            num_terms: Total number of search terms to generate
            
        Returns:
            Dict with search terms list, research topic, and species name
        """
        
        genus_name = species_name.split()[0] if " " in species_name else species_name
        prompt = (
            self._prompt_template
            .replace("[NUM_TERMS]", str(num_terms))
            .replace("[SPECIES_NAME]", species_name)
            .replace("[RESEARCH_TOPIC]", research_topic)
            .replace("[GENUS_NAME]", genus_name)
        )

        # Use Mistral to generate search terms
        messages = [ChatMessage.from_user(prompt)]
        result = self.generator.run(messages=messages)
        
        # Parse response into list
        response = result["replies"][0].text.strip()
        search_terms = [s.strip() for s in response.split('\n') if s.strip()]
        
        # Remove duplicates while preserving order
        final_terms = []
        seen = set()
        for term in search_terms:
            if term.lower() not in seen:
                final_terms.append(term)
                seen.add(term.lower())
        
        return {
            "search_terms": final_terms[:num_terms],
            "research_topic": research_topic,
            "species_name": species_name
        }