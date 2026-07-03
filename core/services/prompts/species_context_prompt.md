You are configuring a scientific data extraction system.

Target species: [SPECIES_NAME]

Give me two real species that are:
- Taxonomically related to [SPECIES_NAME] (same genus, family, or ecological guild)
- Clearly DIFFERENT from [SPECIES_NAME] — not synonyms, not the same species
- Actually exist

They will appear as "wrong species" examples in extraction prompts to show what NOT to extract.

Respond ONLY with valid JSON, exactly this format:
{
  "other_species_1": "Genus species",
  "other_species_2": "Genus species"
}
