#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors
"""
Synonym Cleaner Agent

Filters a raw list of synonym strings returned from taxonomic databases (GBIF, WoRMS),
keeping only valid latin binomial names and removing:
- Author annotations (e.g. "Cambarus clarkii Girard, 1852")
- Parenthesized author strings (e.g. "Procambarus clarkii (Girard, 1852)")
- Botanical authorship incl. "ex" / multiple authors (e.g. "... Gillies ex Hook. & Arn.")
- Database codes (e.g. "BOLD:8502", "urn:lsid:...")
- Any string that is not a recognizable scientific name

Deterministic — no AI/LLM. Each name is parsed by regex so valid binomials are never
silently lost, which an LLM-based cleaner can do when it chokes on messy botanical
author strings and returns an empty list.
"""

import re
from typing import Dict, List, Any
from haystack import component

# Leading binomial: capitalized genus, optional (Subgenus), lowercase species epithet.
# Anything after (author/year) is ignored and dropped.
_BINOMIAL_RE = re.compile(r"^([A-Z][a-z-]+)\s+(?:\(([A-Z][a-z-]+)\)\s+)?([a-z-]+)\b")


@component
class SynonymCleanerAgent:
    """
    Filters raw synonym strings from taxonomic databases, keeping only valid
    latin binomial names and stripping author annotations.
    """

    @component.output_types(cleaned_synonyms=List[str])
    def run(self, raw_synonyms: List[str]) -> Dict[str, Any]:
        """
        Filter and clean a list of raw synonym strings.

        Args:
            raw_synonyms: Raw strings from GBIF/WoRMS synonym endpoints

        Returns:
            Dict with cleaned_synonyms: valid latin binomial names with author strings stripped.
        """
        cleaned: List[str] = []
        for raw in raw_synonyms:
            name = self._clean_one(raw)
            if name:
                cleaned.append(name)

        print(f"  Synonym cleaner: {len(raw_synonyms)} in → {len(cleaned)} out")
        return {"cleaned_synonyms": cleaned}

    @staticmethod
    def _clean_one(raw: str) -> str:
        """Return the cleaned 'Genus species' (or 'Genus (Subgenus) species'), or '' to discard."""
        if not raw:
            return ""
        candidate = raw.strip()
        # Discard database codes / lsids (BOLD:..., urn:lsid:...)
        if ":" in candidate:
            return ""

        match = _BINOMIAL_RE.match(candidate)
        if not match:
            return ""

        genus, subgenus, species = match.groups()
        if subgenus:
            return f"{genus} ({subgenus}) {species}"
        return f"{genus} {species}"


# ============================================================================
# TEST EXECUTION BLOCK
# ============================================================================

if __name__ == "__main__":
    test_input = [
        "Cambarus clarkii",
        "Cambarus clarkii Girard, 1852",
        "Procambarus (Scapulicambarus) clarkii",
        "Procambarus clarkii (Girard, 1852)",
        "Astacus clarkii",
        "BOLD:8502345",
        "urn:lsid:marinespecies.org:taxname:12345",
        # Botanical authorship — a tricky case for LLM-based cleaning
        "Enydria aquatica Vell.",
        "Myriophyllum brasiliense Cambess.",
        "Myriophyllum mattogrossense Hoehne",
        "Myriophyllum proserpinacoides Gillies",
        "Myriophyllum proserpinacoides Gillies ex Hook. & Arn.",
    ]

    print("Input:")
    for name in test_input:
        print(f"  {name}")

    agent = SynonymCleanerAgent()
    result = agent.run(raw_synonyms=test_input)["cleaned_synonyms"]

    print("\nCleaned output:")
    for name in result:
        print(f"  {name}")
