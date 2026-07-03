#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Data Categorization Agent
AI-powered agent that reads raw JSON data and categorizes uncategorized fields
using Mistral AI to map fields to existing schema categories.
"""

import os
import json
from typing import Dict, List, Any
from haystack import component
from haystack.dataclasses import ChatMessage
from functionalities.data_aggregation.preprocessors.typed_array_processor import TypedArrayProcessor
from core.registries.topic_registry import StandardTopicRegistry
from core.utils.generator_factory import create_generator
from functionalities.extraction.utils.json_parser import recover_json_array_from_response


@component
class DataCategorizationAgent:
    """
    AI agent that categorizes uncategorized fields from raw API data.
    Uses Mistral to intelligently map fields to existing database schema categories.
    """

    # Schema categories loaded from centralized registry
    SCHEMA_CATEGORIES = StandardTopicRegistry.get_full_schema()

    def __init__(self):
        """Initialize the categorization agent."""
        self.generator = create_generator("data_categorization")
        self.typed_array_processor = TypedArrayProcessor()
        self.field_mappings = self._load_field_mappings()

    def _load_field_mappings(self) -> Dict[str, Any]:
        """
        Load database field mappings from JSON configuration file.

        Returns:
            Dictionary containing field mapping configuration
        """
        try:
            mapping_path = os.path.join(
                os.path.dirname(__file__),
                '..',
                'tools',
                'database_field_mapping.json'
            )
            with open(mapping_path, 'r', encoding='utf-8') as f:
                mappings = json.load(f)
            return mappings
        except Exception as e:
            print(f"⚠️  Failed to load field mappings: {e}")
            return {'databases': {}}

    @component.output_types(categorizations=List[Dict[str, Any]])
    def run(self, uncategorized_fields: Dict[str, Any], source: str) -> Dict[str, Any]:
        """Haystack component entrypoint — delegates to categorize_fields_by_source."""
        return {"categorizations": self.categorize_fields_by_source(uncategorized_fields, source)}

    def categorize_fields_by_source(self, uncategorized_fields: Dict[str, Any], source: str) -> List[Dict[str, Any]]:
        """
        Categorize all uncategorized fields from a single source.
        Uses database_field_mapping.json for rule-based categorization and typed array splitting.
        Falls back to AI for unmapped fields.

        Args:
            uncategorized_fields: Dictionary of field_name: field_value
            source: Data source name (GBIF, WRiMS, IUCN)

        Returns:
            List of categorized fields with metadata and optional AI reasoning
        """
        if not uncategorized_fields:
            return []

        categorizations = []
        ai_fallback_fields = {}

        # Get database configuration from mappings
        db_config = self.field_mappings.get('databases', {}).get(source, {})

        if not db_config:
            return self._categorize_with_ai(uncategorized_fields, source)

        # Step 1: Process typed_arrays (GBIF descriptions, WRiMS attributes)
        typed_arrays_config = db_config.get('typed_arrays', {})
        special_handling_config = db_config.get('special_handling', {})

        for field_name, field_value in uncategorized_fields.items():
            field_path = f"data.{field_name}"

            # Check if this field is a typed array
            if field_path in typed_arrays_config and isinstance(field_value, list):

                array_config = typed_arrays_config[field_path]
                discriminator = array_config.get('discriminator')

                # Handle special cases first if defined
                special_items = []
                remaining_items = field_value

                if field_path in special_handling_config:
                    special_items, remaining_items = self.typed_array_processor.handle_special_cases(
                        field_value,
                        special_handling_config[field_path],
                        source,
                        field_name,
                        discriminator
                    )

                    # Add special items to categorizations
                    for item, metadata, target_category in special_items:
                        # Clean field name: remove prefix and use semantic name
                        semantic_name = self._get_semantic_field_name(metadata['discriminator_type'])
                        categorizations.append({
                            'field_name': semantic_name,
                            'field_value': item,
                            'data_type': self._detect_data_type(item),
                            'ai_suggested_category': target_category,
                            'source': metadata['source'],
                            'original_field': metadata['original_field'],
                            'discriminator_type': metadata['discriminator_type'],
                            'categorization_method': 'special_handling',
                            'note': metadata.get('note', '')
                        })

                # Split remaining items by discriminator
                split_result = self.typed_array_processor.split_typed_array(
                    remaining_items,
                    array_config,
                    source,
                    field_name
                )

                # Add categorized items
                for category, items_with_metadata in split_result['categorized'].items():
                    for item, metadata in items_with_metadata:
                        # Clean field name: remove prefix and use semantic name
                        semantic_name = self._get_semantic_field_name(metadata['discriminator_type'])
                        categorizations.append({
                            'field_name': semantic_name,
                            'field_value': item,
                            'data_type': self._detect_data_type(item),
                            'ai_suggested_category': category,
                            'source': metadata['source'],
                            'original_field': metadata['original_field'],
                            'discriminator_type': metadata['discriminator_type'],
                            'categorization_method': 'rule-based'
                        })

                # Collect unmapped items for AI fallback
                # Use semantic name as key (discriminator value is unique)
                for item, disc_value in split_result['unmapped']:
                    semantic_key = self._get_semantic_field_name(disc_value)
                    ai_fallback_fields[semantic_key] = {
                        'item': item,
                        'discriminator_value': disc_value,
                        'original_field': field_name
                    }

                # Collect multi-category items for AI decision
                # Use semantic name as key (discriminator value is unique)
                for item, categories, disc_value in split_result['multi_category']:
                    semantic_key = self._get_semantic_field_name(disc_value)
                    ai_fallback_fields[semantic_key] = {
                        'item': item,
                        'possible_categories': categories,
                        'discriminator_value': disc_value,
                        'original_field': field_name
                    }

            # Step 2: Check direct_mappings
            elif field_path in db_config.get('direct_mappings', {}):
                category = db_config['direct_mappings'][field_path]

                # Handle multi-category direct mappings
                if isinstance(category, list):
                    # Send to AI to decide
                    ai_fallback_fields[field_name] = {
                        'value': field_value,
                        'possible_categories': category
                    }
                else:
                    categorizations.append({
                        'field_name': field_name,
                        'field_value': field_value,
                        'data_type': self._detect_data_type(field_value),
                        'ai_suggested_category': category,
                        'source': source,
                        'original_field': field_name,
                        'categorization_method': 'direct-mapping'
                    })

            # Step 3: Unknown field - send to AI
            else:
                ai_fallback_fields[field_name] = field_value

        # Step 4: Process AI fallback items if any
        if ai_fallback_fields:
            ai_categorizations = self._categorize_with_ai(ai_fallback_fields, source)
            categorizations.extend(ai_categorizations)

        return categorizations

    def _build_categorization_prompt(self, fields: Dict[str, Any], source: str) -> str:
        """
        Build a comprehensive prompt for Mistral to categorize fields.
        Uses strict criteria, exclusion rules, and priority ordering from StandardTopicRegistry.

        Args:
            fields: Dictionary of uncategorized fields
            source: Data source name

        Returns:
            Formatted prompt string
        """
        # Build field descriptions with data types
        field_descriptions = []
        for field_name, field_value in fields.items():
            data_type = self._detect_data_type(field_value)

            # Get sample value (truncate if too long)
            sample_value = str(field_value)
            if len(sample_value) > 100:
                sample_value = sample_value[:100] + "..."

            field_descriptions.append(f"  - {field_name}: {sample_value} (type: {data_type})")

        fields_text = "\n".join(field_descriptions)

        # Get strict criteria and exclusion rules from registry
        strict_criteria = StandardTopicRegistry.get_strict_criteria()
        exclusion_rules = StandardTopicRegistry.get_exclusion_rules()

        # Build detailed category guide
        categories_text = []
        for i, (cat_key, short_desc) in enumerate(self.SCHEMA_CATEGORIES.items(), 1):
            if cat_key in strict_criteria:  # Only for standard topics (not system categories)
                categories_text.append(
                    f"{i}. {cat_key}:\n"
                    f"   Description: {short_desc}\n"
                    f"   Criteria: {strict_criteria[cat_key]}\n"
                    f"   Exclusions: {exclusion_rules[cat_key]}"
                )
            else:
                # System categories (data_metadata, needs_review)
                categories_text.append(f"{i}. {cat_key}: {short_desc}")

        categories_guide = "\n\n".join(categories_text)

        # Get categorization guide with priority order and examples
        categorization_guide = StandardTopicRegistry.get_categorisation_guide()

        prompt = f"""You are a data categorization expert for biological species databases.

{categorization_guide}

AVAILABLE CATEGORIES WITH STRICT CRITERIA:
{categories_guide}

Data Source: {source}

Uncategorized fields from API:
{fields_text}

TASK: For each field above, categorize using the strict criteria and exclusion rules.
- Apply the FIRST category that matches based on priority order
- Each field goes to EXACTLY ONE category
- Provide brief reasoning referencing the criteria

IMPORTANT: Your response must be ONLY a valid JSON array with this exact structure:
[
  {{
    "field_name": "exact_field_name",
    "suggested_category": "category_key",
    "reasoning": "brief explanation citing criteria/exclusion"
  }}
]

Do not include any other text, markdown formatting, or explanations outside the JSON array."""

        return prompt

    def _categorize_with_ai(self, fields: Dict[str, Any], source: str) -> List[Dict[str, Any]]:
        """
        Use AI to categorize fields that couldn't be handled by rule-based mappings.

        Args:
            fields: Dictionary of field_name: field_value (or complex objects for multi-category)
            source: Data source name

        Returns:
            List of categorizations with AI reasoning
        """
        if not fields:
            return []

        try:
            # Build prompt
            prompt = self._build_categorization_prompt(fields, source)

            # Call Mistral API
            messages = [ChatMessage.from_user(prompt)]
            response = self.generator.run(messages=messages)

            # Extract response text
            if response and 'replies' in response and response['replies']:
                ai_response = response['replies'][0].text

                # Parse AI response
                categorizations = self._parse_ai_response(ai_response, fields)
                return categorizations
            else:
                return self._create_fallback_categorizations(fields)

        except Exception as e:
            return self._create_fallback_categorizations(fields)

    def _parse_ai_response(self, response: str, original_fields: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse Mistral's JSON response into categorization data.

        Args:
            response: AI response string
            original_fields: Original uncategorized fields

        Returns:
            List of categorization dictionaries
        """
        try:
            categorizations_raw = recover_json_array_from_response(response)

            # Build result with data types
            categorizations = []
            for item in categorizations_raw:
                field_name = item.get('field_name')  # Already semantic name
                if field_name in original_fields:
                    field_value = original_fields[field_name]

                    # Check if this has typed array metadata
                    discriminator_value = None
                    original_field = None

                    if isinstance(field_value, dict) and 'discriminator_value' in field_value:
                        # Extract metadata and actual item value
                        discriminator_value = field_value['discriminator_value']
                        original_field = field_value.get('original_field', field_name)
                        field_value = field_value.get('item', field_value)

                    result = {
                        'field_name': field_name,  # Already semantic
                        'field_value': field_value,
                        'data_type': self._detect_data_type(field_value),
                        'ai_suggested_category': item.get('suggested_category', 'unknown'),
                        'ai_reasoning': item.get('reasoning', 'No reasoning provided'),
                        'categorization_method': 'ai'
                    }

                    # Add metadata if available
                    if discriminator_value:
                        result['discriminator_type'] = discriminator_value
                    if original_field:
                        result['original_field'] = original_field

                    categorizations.append(result)

            return categorizations

        except json.JSONDecodeError as e:
            return self._create_fallback_categorizations(original_fields)
        except Exception as e:
            return self._create_fallback_categorizations(original_fields)

    def _create_fallback_categorizations(self, fields: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Create fallback categorizations when AI fails.

        Args:
            fields: Uncategorized fields

        Returns:
            List of categorizations with 'needs_review' category
        """
        categorizations = []
        for field_name, field_value in fields.items():
            # Check if this has typed array metadata
            discriminator_value = None
            original_field = None

            if isinstance(field_value, dict) and 'discriminator_value' in field_value:
                # Extract metadata and actual item value
                discriminator_value = field_value['discriminator_value']
                original_field = field_value.get('original_field', field_name)
                field_value = field_value.get('item', field_value)

            result = {
                'field_name': field_name,  # Already semantic
                'field_value': field_value,
                'data_type': self._detect_data_type(field_value),
                'ai_suggested_category': 'needs_review',
                'ai_reasoning': 'AI categorization failed, requires manual review',
                'categorization_method': 'fallback'
            }

            # Add metadata if available
            if discriminator_value:
                result['discriminator_type'] = discriminator_value
            if original_field:
                result['original_field'] = original_field

            categorizations.append(result)
        return categorizations

    def _detect_data_type(self, value: Any) -> str:
        """
        Detect the data type of a value.

        Args:
            value: Value to analyze

        Returns:
            Type string: 'string', 'number', 'boolean', 'list', 'dict', 'null'
        """
        if value is None:
            return 'null'
        elif isinstance(value, bool):
            return 'boolean'
        elif isinstance(value, (int, float)):
            return 'number'
        elif isinstance(value, list):
            return 'list'
        elif isinstance(value, dict):
            return 'dict'
        else:
            return 'string'

    def _get_semantic_field_name(self, discriminator_value: str) -> str:
        """
        Convert discriminator values to clean, semantic field names.

        Args:
            discriminator_value: The discriminator value (e.g., "native range", "Etymology classification")

        Returns:
            Clean semantic field name
        """
        # Mapping of discriminator values to semantic field names
        semantic_mapping = {
            # GBIF descriptions
            'native range': 'native_range',
            'pathway': 'pathways',
            'introduction pathway': 'pathways',
            'invasion stage': 'invasion_stage',
            'degree of establishment': 'establishment_degree',
            'Introduced species abundance': 'abundance',
            'Introduced species impact': 'ecological_impacts',
            'Introduced species remark': 'impact_remarks',
            'Introduced species vector dispersal': 'dispersal_vectors',
            'eunis habitat': 'habitat_types',
            'ecofunctional group': 'ecological_role',
            'behaviour': 'behavior',
            'reproduction': 'reproduction',
            'lifecycle': 'lifecycle',

            # WRiMS attributes
            'Body size': 'body_size',
            'Body size (qualitative)': 'body_size_qualitative',
            'Etymology classification': 'etymology',
            'Species exhibits underwater soniferous behaviour': 'soniferous_behavior',
            'Species importance to society': 'societal_importance',
            'Gametophyte arrangement': 'gametophyte_arrangement',
            'Reproduction': 'reproduction',
            'Gamete type': 'gamete_type',
            'Spawning': 'spawning',
            'Life span': 'lifespan',
            'Seasonality': 'seasonality',
            'Macroalgal blooming': 'macroalgal_blooming',
            'AMBI ecological group': 'ambi_ecological_group',
            'Functional group': 'functional_group'
        }

        # Return mapped name or create one from the discriminator value
        if discriminator_value in semantic_mapping:
            return semantic_mapping[discriminator_value]
        else:
            # Fallback: convert to snake_case
            return discriminator_value.lower().replace(' ', '_').replace('-', '_')
