You are generating a high-quality data extraction prompt for a custom research topic.

CUSTOM TOPIC: "[CUSTOM_TOPIC]"[SPECIES_CONTEXT]

TOPIC INTERPRETATION:
[TOPIC_INTERPRETATION]

KEY CONCEPTS:
[KEY_CONCEPTS]

SCOPE BOUNDARIES:
[SCOPE_BOUNDARIES]

---

YOUR TASK:
Generate a complete extraction prompt following the template structure below. The prompt must help an AI extract relevant information about "[CUSTOM_TOPIC]" from scientific papers.

CRITICAL REQUIREMENTS:
1. Follow the template structure EXACTLY - all sections must be present
2. Be specific and concrete - avoid vague or generic instructions. Emphasise that all extracted facts must be explicitly about the target species, not other species mentioned in papers.
3. Create clear boundaries distinguishing this topic from standard categories (taxonomic identity, morphological traits, physiological traits, distribution, habitat & ecology, species interactions, impacts, management & biosecurity, conservation status, economic utilisation, detection & monitoring)
4. Include realistic examples relevant to invasive species research
5. Use the same formatting conventions (✓ for includes, ✗ for excludes, etc.)
6. CRITICAL: Enforce FLAT JSON output - one field = one fact, no nested objects/arrays

STANDARD CATEGORIES TO DISTINGUISH FROM:
- Taxonomic Identity: scientific names, classification, synonyms
- Morphological Traits: physical characteristics, size, anatomy
- Physiological Traits: growth rates, reproduction, diet, dispersal
- Distribution: geographic occurrence, native/introduced ranges, invasion history
- Habitat & Ecology: habitat types, environmental requirements, ecological role
- Species Interactions: predator-prey, competition, mutualism, parasites
- Impacts: ecological/economic/social impacts, damage costs
- Management & Biosecurity: prevention, control, eradication, regulations
- Conservation Status: IUCN category, population trends, threats
- Economic Utilisation: commercial use, fisheries, aquaculture, trade
- Detection & Monitoring: identification methods, survey protocols, eDNA

---

TEMPLATE TO FOLLOW:

[TEMPLATE]

---

Generate the complete extraction prompt now. Output ONLY the prompt markdown - no preamble, no explanation.
Start directly with the title: "# [TOPIC] EXTRACTION PROMPT"
