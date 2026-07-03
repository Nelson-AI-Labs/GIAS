#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Species Name Utilities
Functions for standardizing and validating scientific species names.
"""
import re

def standardize_species_name(species_name: str) -> str:
    """
    Standardize a scientific species name to proper taxonomic format.

    Rules:
    - Genus: First letter capitalized, rest lowercase
    - Species: All lowercase
    - Handle subspecies and varieties properly
    - Remove extra whitespace

    Args:
        species_name: Raw species name input

    Returns:
        Standardized species name in proper format

    Examples:
        'APALONE SPINIFERA' -> 'Apalone spinifera'
        'apalone spinifera' -> 'Apalone spinifera'
        'Apalone Spinifera' -> 'Apalone spinifera'
        'Apalone   spinifera' -> 'Apalone spinifera'
    """
    if not species_name or not species_name.strip():
        return species_name

    # Remove extra whitespace and split into parts
    parts = species_name.strip().split()

    if len(parts) == 0:
        return species_name

    standardized_parts = []

    for i, part in enumerate(parts):
        if i == 0:
            # First part (genus) - capitalize first letter, rest lowercase
            standardized_parts.append(part.capitalize())
        else:
            # All other parts (species, subspecies, etc.) - all lowercase
            standardized_parts.append(part.lower())

    return ' '.join(standardized_parts)


def validate_binomial_format(species_name: str) -> bool:
    """
    Check if a species name follows basic binomial nomenclature format.

    Args:
        species_name: Species name to validate

    Returns:
        True if name appears to be in valid binomial format
    """
    parts = species_name.strip().split()

    # Must have at least genus and species (2 parts)
    if len(parts) < 2:
        return False

    # Each part should contain only letters (no numbers or special chars)
    for part in parts:
        if not part.isalpha():
            return False

    return True


def get_species_name_variations(species_name: str) -> list:
    """
    Generate common variations of a species name for fallback searches.

    Args:
        species_name: Base species name

    Returns:
        List of name variations to try
    """
    standardized = standardize_species_name(species_name)
    variations = [standardized]

    # Add original if different
    if species_name.strip() != standardized:
        variations.append(species_name.strip())

    # Add all lowercase version
    all_lower = species_name.strip().lower()
    if all_lower not in variations:
        variations.append(all_lower)

    # Add all uppercase version
    all_upper = species_name.strip().upper()
    if all_upper not in variations:
        variations.append(all_upper)

    return variations


def update_streamlit_input_with_standardized_name(raw_input: str):
    """
    Standardize species name and update Streamlit session state to show corrected version in input field.
    This runs BEFORE any pipeline to correct user input immediately.

    Args:
        raw_input: Whatever the user typed in the input field

    Returns:
        standardized_name: The corrected species name
    """
    standardized_name = standardize_species_name(raw_input)

    try:
        import streamlit as st
        if hasattr(st, 'session_state'):
            # Force update the input field to show standardized name
            st.session_state.user_input_corrected = standardized_name
            print(f"Input corrected: '{raw_input}' → '{standardized_name}'")
    except Exception as e:
        print(f"Could not update input field: {e}")

    return standardized_name


def get_binomial_name(full_string):
    """
    Extracts the first two words (Genus species) using a regex pattern.
    Pattern: Starts with a Capitalized word, followed by a lowercase word.
    """
    match = re.match(r'^([A-Z][a-z]+ [a-z\-]+)', full_string)
    if match:
        return match.group(1)

    # Fallback: If the regex doesn't match, return the first two words split by space
    return " ".join(full_string.split()[:2])


def get_author_string(full_string: str) -> str:
    """
    Extracts the authorship string from a full scientific name.
    Returns everything after the binomial (Genus species), stripped of leading whitespace.

    Examples:
        'Apalone spinifera (Lesueur, 1827)' -> '(Lesueur, 1827)'
        'Lepomis gibbosus (Linnaeus, 1758)'  -> '(Linnaeus, 1758)'
        'Apalone spinifera'                  -> ''
    """
    match = re.match(r'^([A-Z][a-z]+ [a-z\-]+)\s*(.*)', full_string)
    if match:
        return match.group(2).strip()
    return ''