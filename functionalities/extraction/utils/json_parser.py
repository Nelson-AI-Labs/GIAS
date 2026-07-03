# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
JSON Parsing and Recovery Utilities

Provides robust JSON parsing with multiple recovery strategies for AI-generated responses.
"""

import json
import re
from typing import Dict, Any, List, Tuple


def recover_json_from_response(response_text: str) -> Tuple[Dict[str, Any], List[str]]:
    """
    Multi-strategy JSON recovery from AI responses.

    Applies these strategies in order:
    1. Direct JSON parse
    2. Extract from markdown code blocks (```json ... ```)
    3. Fix common JSON errors (trailing commas, multiple commas)
    4. Substring extraction (find first { and last })
    5. Partial field-by-field extraction using regex

    Args:
        response_text: Raw text response from AI

    Returns:
        Tuple of (parsed_data, parse_errors)
        - parsed_data: Recovered dictionary or None if all strategies failed
        - parse_errors: List of error messages from each failed strategy

    Raises:
        json.JSONDecodeError: If all recovery strategies fail
    """
    original_response = response_text
    response_text = response_text.strip()
    parse_errors = []

    # Strategy 1: Extract JSON from markdown code blocks
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    elif response_text.startswith("```"):
        response_text = response_text[3:]

    if response_text.endswith("```"):
        response_text = response_text[:-3]

    response_text = response_text.strip()

    # Strategy 2: Fix common JSON errors
    # Fix trailing commas before closing braces/brackets (invalid in strict JSON)
    response_text = re.sub(r',(\s*[}\]])', r'\1', response_text)

    # Fix multiple consecutive commas
    response_text = re.sub(r',\s*,', ',', response_text)

    # Strategy 3: Try parsing with multiple approaches
    parsed_data = None

    # Approach 1: Direct parse
    try:
        parsed_data = json.loads(response_text)
        return parsed_data, []  # Success!
    except json.JSONDecodeError as e:
        parse_errors.append(f"Direct parse: {str(e)}")

    # Approach 2: Try to find JSON object within text
    try:
        # Find first { and last }
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_substring = response_text[start:end+1]
            # Fix trailing commas again
            json_substring = re.sub(r',(\s*[}\]])', r'\1', json_substring)
            parsed_data = json.loads(json_substring)
            return parsed_data, parse_errors  # Success!
    except json.JSONDecodeError as e:
        parse_errors.append(f"Substring extraction: {str(e)}")

    # Approach 3: Try to salvage partial data line by line
    # This is a last resort - try to extract individual field entries
    try:
        parsed_data = {}
        # Look for patterns like "field_name": { "reasoning": "..." }
        field_pattern = (
            r'"([^"]+)":\s*\{'
            r'[^}]*"reasoning":\s*"([^"]*)"'
            r'[^}]*\}'
        )
        matches = re.finditer(field_pattern, response_text, re.DOTALL)
        for match in matches:
            field_name = match.group(1)
            reasoning = match.group(2)
            parsed_data[field_name] = {
                "reasoning": reasoning,
            }
        if parsed_data:
            return parsed_data, parse_errors  # Partial success!
        else:
            raise ValueError("Could not extract any valid fields")
    except Exception as e:
        parse_errors.append(f"Partial extraction: {str(e)}")

    # All parsing failed
    print("=" * 80)
    print("ERROR: Failed to parse AI response after all attempts")
    print("=" * 80)
    print("ORIGINAL RESPONSE:")
    print(original_response[:1000])  # Print first 1000 chars
    print("=" * 80)
    print("PARSE ERRORS:")
    for err in parse_errors:
        print(f"  - {err}")
    print("=" * 80)

    raise json.JSONDecodeError(
        f"Failed to parse JSON after all recovery attempts. Errors: {'; '.join(parse_errors)}",
        original_response,
        0
    )


def validate_extraction_structure(
    data: Dict[str, Any],
    strict: bool = True
) -> Dict[str, Any]:
    """
    Validate that extraction data follows flat JSON rules.

    Rules:
    1. Each field must be a dictionary with a 'reasoning' key
    2. Any model-authored 'value' is stripped — find_passage tool result provides verbatim text
    3. Fields without 'candidate_source_quote' are dropped downstream by verification

    Args:
        data: Parsed JSON data from extraction
        strict: If True, reject nested values. If False, warn only.

    Returns:
        Validated data (with invalid fields removed if strict=True)
    """
    if not isinstance(data, dict):
        raise ValueError("Response must be a JSON object (dict)")

    validated_data = {}
    rejected_fields = []

    for field_name, field_data in data.items():
        # Check structure
        if not isinstance(field_data, dict):
            rejected_fields.append((field_name, "Not a dictionary"))
            continue

        # Strip any model-authored value — tool result provides verbatim text
        if "value" in field_data:
            stripped = field_data.pop("value")
            if isinstance(stripped, (dict, list)):
                print(f"⚠ [json_parser] Stripped nested value for '{field_name}' (model wrote a nested structure)")

        # Ensure reasoning exists (default if missing)
        if "reasoning" not in field_data:
            field_data["reasoning"] = "Extracted from research source"

        validated_data[field_name] = field_data

    # Report rejected fields
    if rejected_fields:
        print(f"\n{'='*60}")
        print(f"Flat JSON Validation: {len(rejected_fields)} field(s) rejected")
        print(f"{'='*60}")
        for field, reason in rejected_fields:
            print(f"  ✗ {field}: {reason}")
        print(f"{'='*60}\n")

    return validated_data


def parse_and_validate_extraction(
    response_text: str,
    strict: bool = True
) -> Dict[str, Any]:
    """
    Combined parsing + validation for extraction responses.

    This is the main entry point for processing AI extraction responses.
    It combines JSON recovery and structure validation in a single operation.

    Args:
        response_text: Raw text response from AI
        strict: If True, enforce strict flat JSON validation

    Returns:
        Validated dictionary with extracted data

    Raises:
        json.JSONDecodeError: If JSON parsing fails after all recovery attempts
        ValueError: If structure validation fails
    """
    # Step 1: Recover JSON from response
    parsed_data, _ = recover_json_from_response(response_text)

    # Step 2: Validate structure
    validated_data = validate_extraction_structure(parsed_data, strict=strict)

    return validated_data


def recover_json_array_from_response(response_text: str) -> List[Any]:
    """
    JSON recovery for AI responses that return arrays rather than objects.

    Applies the same strategies as recover_json_from_response but targets
    the outermost [...] array instead of {...} object.

    Args:
        response_text: Raw text response from AI

    Returns:
        Parsed list, or [] if all recovery strategies fail.
    """
    text = response_text.strip()

    # Strip markdown code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Fix trailing commas
    text = re.sub(r',(\s*[}\]])', r'\1', text)

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Find outermost array bounds
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1 and end > start:
        try:
            candidate = text[start:end + 1]
            candidate = re.sub(r',(\s*[}\]])', r'\1', candidate)
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


def is_flat_value(value: Any) -> bool:
    """
    Check if a value is flat (not nested).

    Args:
        value: Value to check

    Returns:
        True if value is flat (string, number, bool, None), False if nested
    """
    return not isinstance(value, (dict, list))
