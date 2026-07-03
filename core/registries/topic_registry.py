# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Standard Topic Registry
========================

Centralized registry for all standard research topics.
Single source of truth for topic names, descriptions, and extraction guidance.

CRITICAL: Categories are MUTUALLY EXCLUSIVE with hard boundaries.
Each piece of information belongs to EXACTLY ONE category.
"""

from typing import Dict, List, Optional, Any


class TopicDefinition:
    """
    Definition for a single research topic with strict boundaries.
    """

    def __init__(
        self,
        key: str,
        display_name: str,
        short_description: str,
        detailed_description: str,
        key_concepts: List[str],
        strict_criteria: str,
        exclusion_rules: str,
        prompt_file: str,
        search_terms: List[str],
        dashboard_card: Optional[str] = None,
        priority_tier: str = "ecology_support"
    ):
        """
        Initialize a topic definition.

        Args:
            key: Internal identifier (underscore format, e.g., 'habitat_ecology')
            display_name: User-facing name (e.g., 'Habitat & Ecology')
            short_description: Brief comma-separated description for tooltips and categorization
            detailed_description: Full explanation of what this topic covers
            key_concepts: List of main concepts/keywords for this topic
            strict_criteria: ONLY information meeting ALL these criteria belongs here
            exclusion_rules: Absolute exclusions with priority rules for edge cases
            prompt_file: Filename of extraction prompt (e.g., 'habitat_ecology_prompt.md')
            search_terms: List of generic search terms (will be combined with species name by Tavily)
            dashboard_card: Optional dashboard card key if different from topic key
            priority_tier: 'management_core' for topics directly answering management questions;
                           'ecology_support' for background ecology topics (default)
        """
        self.key = key
        self.display_name = display_name
        self.short_description = short_description
        self.detailed_description = detailed_description
        self.key_concepts = key_concepts
        self.strict_criteria = strict_criteria
        self.exclusion_rules = exclusion_rules
        self.prompt_file = prompt_file
        self.search_terms = search_terms
        self.dashboard_card = dashboard_card or key
        self.priority_tier = priority_tier

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format."""
        return {
            'key': self.key,
            'display_name': self.display_name,
            'short_description': self.short_description,
            'detailed_description': self.detailed_description,
            'key_concepts': self.key_concepts,
            'strict_criteria': self.strict_criteria,
            'exclusion_rules': self.exclusion_rules,
            'prompt_file': self.prompt_file,
            'search_terms': self.search_terms,
            'dashboard_card': self.dashboard_card,
            'priority_tier': self.priority_tier
        }


class StandardTopicRegistry:
    """
    Registry of all standard research topics with STRICT mutual exclusivity.
    
    CATEGORISATION PRIORITY ORDER (when information could fit multiple categories):
    1. Taxonomic Identity - scientific names/classification ONLY
    2. Biological Traits - organism-level biology, morphology, physiology, behaviour ONLY
    3. Distribution & Status - geographic occurrence, establishment status, formal listings ONLY
    4. Habitat & Ecology - ecosystem-level habitat conditions and niche ONLY
    5. Species Interactions - named organism-to-organism interactions ONLY
    6. Impacts - population/ecosystem/socioeconomic consequences ONLY
    7. Introduction & Spread Pathways - vectors and mechanisms of movement ONLY
    8. Management & Biosecurity - deliberate control/prevention interventions ONLY
    9. Detection & Monitoring - identification and surveillance methods ONLY
    """

    TOPICS = {
        'taxonomic_identity': TopicDefinition(
            key='taxonomic_identity',
            display_name='Taxonomic Identity',
            short_description='Scientific names, taxonomic classification, synonyms, common names, taxonomic authority, phylogenetic placement',
            detailed_description='Taxonomic classification, nomenclature, and naming of the organism across the full taxonomic hierarchy — species, genus, family, order, class, phylum. Covers scientific names, all known synonyms, vernacular names across languages, taxonomic authority, and phylogenetic placement. Correct naming underpins every downstream workflow: database queries, literature retrieval, regulatory compliance, and field identification. Diagnostic keys distinguishing the target species from similar native species, nomenclature as it appears in regulatory instruments (EU Regulation 1143/2014, national legislation), and documentation of cryptic species complexes are especially valuable. All stated taxonomic information about the species should be captured regardless of the paper\'s disciplinary framing.',
            key_concepts=[
                'Scientific name (species, genus, family, order, class, phylum)',
                'Taxonomic authority and authorship',
                'Accepted synonyms and nomenclatural history',
                'Common and vernacular names by language/region',
                'Taxonomic rank and hierarchical classification'
            ],
            strict_criteria='Information about what the organism is called or how it is formally classified in the taxonomic tree. MUST relate to naming, classification hierarchy, or nomenclatural synonymy.',
            exclusion_rules='Exclude: physical descriptions, evolutionary relationships used for ecological inference, habitat where type specimen was collected, morphological features, phylogenetic analysis used to infer ecology or behaviour.',
            prompt_file='taxonomic_identity_prompt.md',
            search_terms=[
                '"invasive" "diagnostic key" species identification field',
                '"invasive" "cryptic species" misidentification monitoring',
                '"EU Regulation 1143" species listing taxonomy nomenclature',
                '"invasive" lookalike native species confusion identification',
                '"invasive" hybridisation native species genetic identity',
                '"invasive" synonyms vernacular names taxonomy',
            ],
            dashboard_card='taxonomic_identity',
            priority_tier='ecology_management_relevant'
        ),

        'biological_traits': TopicDefinition(
            key='biological_traits',
            display_name='Biological Traits',
            short_description='Morphology, physiology, life history, reproduction, growth, diet, behaviour, locomotion',
            detailed_description='Organism-level biological characteristics: morphology, physiology, life history, reproduction, growth, diet, behaviour, and adaptability. Includes basic biology — body size, appearance, life stages, colouration, breeding conditions, diet composition, activity patterns — as well as traits relevant to invasion ecology: thermal and salinity tolerance ranges, reproductive rate and fecundity, dispersal capacity, phenotypic plasticity, and life history strategy. Information from any source (aquaculture, genetics, laboratory experiments, field ecology) contributes if it describes an individual-level biological property of the species. Quantified measurements (temperature ranges, fecundity values, growth rates) are especially valuable as they feed into risk assessment and species distribution models. All stated biological facts about the species should be captured regardless of the paper\'s disciplinary framing.',
            key_concepts=[
                'Body size, morphology, and diagnostic physical features',
                'Growth rates, longevity, and developmental timing',
                'Reproductive strategy, fecundity, and maturation age',
                'Diet, trophic level, and feeding behaviour',
                'Locomotion, dispersal ability, and movement behaviour',
                'Behavioural plasticity and adaptability',
                'Life history strategy (r/K selection traits)',
                'Asexual or parthenogenetic reproduction capacity'
            ],
            strict_criteria='Information about the organism itself at the individual level: what it looks like, how it grows, how it reproduces, what it eats, and how it behaves. MUST describe characteristics of the organism, not its interactions with other species or its effects on ecosystems.',
            exclusion_rules='Exclude: environmental tolerances (temperature, salinity, pH, dissolved oxygen) — those belong in habitat_ecology. Exclude: named interactions with specific other species (species_interactions), documented ecosystem-level consequences (impacts), geographic locations where the organism occurs (distribution_and_status), methods used to detect it (detection_monitoring).',
            prompt_file='biological_traits_prompt.md',
            search_terms=[
                '"invasive" "growth rate" reproduction life history establishment',
                '"invasive" "dispersal" propagule fragment clonal vegetative',
                '"invasive" "phenotypic plasticity" adaptability generalist',
                '"invasive" morphology anatomy body size measurement',
                '"biological invasion" traits establishment life history success',
                '"invasive species" behavior activity movement foraging',
                '"invasive" physiology metabolic fecundity reproductive output',
            ],
            dashboard_card='biological_traits',
            priority_tier='ecology_management_relevant'
        ),

        'distribution_and_status': TopicDefinition(
            key='distribution_and_status',
            display_name='Distribution & Status',
            short_description='Native range, invaded range, establishment status per region, first detection dates, spread chronology, invasion history, IUCN status',
            detailed_description='Geographic occurrence of the species: native range and origin, introduced and invaded regions, establishment status per location, first detection dates, invasion spread chronology, and formal conservation or regulatory listings. Covers all forms of occurrence documentation — range maps, museum records, field surveys, genetic sampling localities, occurrence databases, aquaculture escape reports, and incidental catches — as well as IUCN status and regulatory listing under national or international instruments (EU Regulation 1143/2014, national invasive species lists). Spread rate data, invasion front documentation, and regulatory listings linked to management obligations are especially valuable for prioritisation and early response. Any paper that states where and when the species has been found contributes distribution data.',
            key_concepts=[
                'Native geographic range and origin',
                'Current invaded or introduced range by region/country',
                'Establishment status (established, intercepted, eradicated, suspected)',
                'First detection dates per location',
                'Invasion spread chronology and rates',
                'Occurrence coordinates and georeferenced records',
                'IUCN Red List status (in native range)',
                'Regulatory listing status (EU IAS Regulation, national lists)',
                'Population trends in native vs invaded range'
            ],
            strict_criteria='Information about WHERE the organism occurs geographically, WHEN it was detected or established there, and its formal listing or conservation status. MUST include place names, regions, coordinates, dates of detection, or formal status designations.',
            exclusion_rules='Exclude: HOW it arrived (introduction_pathways), WHAT habitat conditions it requires (habitat_ecology), WHAT ecological damage it causes (impacts), HOW to find it (detection_monitoring). Introduction vectors and mechanisms go to introduction_pathways, not here. Only WHERE, WHEN, and formal STATUS belong here.',
            prompt_file='distribution_and_status_prompt.md',
            search_terms=[
                '"invasive" "spread rate" range expansion management intervention',
                '"invasive" "range expansion" management priority monitoring',
                '"invasive" "invasion front" early detection management',
                '"eradication" confirmed outcome aquatic invasive spread status',
                '"EU Regulation 1143" listing management obligation aquatic species',
                '"invasive" "established population" range management status',
                '"invasive" "first detection" rapid response region chronology',
                '"nonindigenous" occurrence database aquatic invasive records',
            ],
            dashboard_card='distribution_and_status',
            priority_tier='ecology_management_relevant'
        ),

        'habitat_ecology': TopicDefinition(
            key='habitat_ecology',
            display_name='Habitat & Ecology',
            short_description='Habitat types, ecosystem preferences, abiotic requirements, water quality parameters, depth range, substrate, seasonal patterns, niche characteristics',
            detailed_description='Environmental conditions and habitat associations of the species: aquatic habitat types, substrate preferences, water quality parameters (pH, dissolved oxygen, turbidity, nutrient levels), depth ranges, salinity regime, thermal regime, seasonal habitat use, and ecological niche breadth. Information from any source — field ecology, aquaculture husbandry, experimental physiology, environmental monitoring — contributes if it describes the external environment the species inhabits or tolerates. Quantified environmental tolerance limits (temperature, salinity, pH, dissolved oxygen ranges) are especially valuable as they feed into species distribution models and invasion risk mapping. All stated habitat and environmental information about the species should be captured.',
            key_concepts=[
                'Aquatic habitat types (lakes, rivers, estuaries, marine, brackish)',
                'Substrate preferences (sandy, muddy, rocky, vegetated)',
                'Water quality parameters (pH range, dissolved oxygen, turbidity, nutrient levels)',
                'Depth range and vertical distribution',
                'Salinity regime (freshwater, brackish, marine, euryhaline)',
                'Seasonal habitat use and phenological patterns',
                'Thermal regime and temperature range of occupied habitats',
                'Ecological niche and habitat generalism vs specialism',
                'Habitat modification caused by species presence'
            ],
            strict_criteria='Information about the types of environments or ecosystem conditions where the organism is found or documented to occur. MUST describe the external environment, not the organism\'s internal biology. Habitat descriptions from field studies and occurrence records belong here.',
            exclusion_rules='Exclude: the organism\'s internal physiological tolerances (biological_traits), named interactions with specific other species (species_interactions), geographic locations and coordinates (distribution_and_status), ecosystem-level impacts of the invasion (impacts). "Found in shallow littoral zones" = habitat_ecology. "Tolerates 5-35°C" = biological_traits.',
            prompt_file='habitat_ecology_prompt.md',
            search_terms=[
                '"invasive" "habitat suitability" species distribution model risk',
                '"invasive" "species distribution model" aquatic establishment potential',
                '"invasive" "environmental tolerance" establishment spread potential',
                '"invasive" "invasion risk" habitat vulnerability ecosystem management',
                '"invasive" "climate change" range expansion thermal habitat',
                '"invasive" "biotic resistance" native community habitat',
                '"invasive" "climate projection" future distribution range shift',
                '"invasive" "MaxEnt" OR "Maxent" species distribution model future',
                '"invasive" "RCP" OR "SSP" climate scenario future range aquatic',
                '"invasive" "future distribution" climate warming spread potential',
            ],
            dashboard_card='habitat_ecology',
            priority_tier='ecology_management_relevant'
        ),

        'species_interactions': TopicDefinition(
            key='species_interactions',
            display_name='Species Interactions',
            short_description='Predator-prey relationships, competition with native species, parasites, disease vectors, mutualism, facilitation, biotic resistance',
            detailed_description='Ecological interactions between the species and other organisms: predator-prey relationships, competition with native and other invasive species, parasites, pathogens, disease transmission, mutualistic relationships, hybridisation, and facilitation of other species. Covers interactions documented in any context — laboratory feeding trials, aquaculture pest and disease observations, field ecology studies, genetic introgression research. Named species interactions (identifying the interacting organism) are most informative. Evidence of natural enemies (predators, parasites, pathogens) that could inform biological control, competitive displacement of named native species, and hybridisation with protected species is especially valuable for management planning. All documented organism-to-organism interactions should be captured.',
            key_concepts=[
                'Prey species consumed (with named species where possible)',
                'Known predators in native and invaded range',
                'Native species it directly competes with',
                'Parasites and pathogens hosted or transmitted',
                'Disease vector status',
                'Mutualistic relationships (e.g. cleaning stations, seed dispersal equivalents)',
                'Facilitation of other invasive species (invasional meltdown)',
                'Biotic resistance from native community',
                'Hybridisation with native species'
            ],
            strict_criteria='Information about direct, named organism-to-organism interactions. MUST name the interacting species or taxonomic group. Generic statements like "preys on native fish" without naming species belong in impacts. Named interactions like "preys on Salmo trutta" belong here.',
            exclusion_rules='Exclude: ecosystem-level consequences that emerge from interactions (impacts), the organism\'s diet at a general trophic level (biological_traits), habitat modification (habitat_ecology). The line is: named species interaction = species_interactions; documented population or ecosystem consequence = impacts.',
            prompt_file='species_interactions_prompt.md',
            search_terms=[
                '"invasive" "biological control" predator natural enemy effectiveness',
                '"invasive" "enemy release" biotic resistance control implications',
                '"invasive" "biotic resistance" native community control',
                '"invasive" "competition" displacement native species management',
                '"invasive" "parasite" pathogen biocontrol potential',
                '"invasive" "hybridisation" native species genetic pollution',
                '"invasive" "trophic cascade" management implications',
            ],
            dashboard_card='species_interactions',
            priority_tier='ecology_management_relevant'
        ),

        'impacts': TopicDefinition(
            key='impacts',
            display_name='Impacts',
            short_description='Ecological impacts on native biodiversity and ecosystems, socioeconomic impacts on fisheries, aquaculture, infrastructure, human health, and ecosystem services',
            detailed_description='Quantified consequences of aquatic invasive species on ecosystems and human welfare, with emphasis on impact data that supports management decisions. Prioritises: economic cost quantification (InvaCost-compatible data), cost-benefit analyses of management versus no-management scenarios, impact assessments used in EICAT or similar classifications, fishery and aquaculture production loss data, and infrastructure biofouling cost estimates. Impact data is most management-useful when it is quantified, jurisdiction-specific, peer-reviewed, or used in a systematic review to justify a management intervention.',
            key_concepts=[
                'Native species population declines attributed to invasion',
                'Biodiversity loss and community composition change',
                'Trophic cascade and food web disruption',
                'Habitat alteration (e.g. turbidity increase, macrophyte removal, sediment change)',
                'Fishery production losses or changes',
                'Aquaculture damage and closure',
                'Biofouling of infrastructure (pipes, vessels, intake systems)',
                'Water supply and treatment disruption',
                'Human health impacts (toxins, parasites, allergens)',
                'Tourism and recreation impacts',
                'Ecosystem service disruption or provision',
                'Quantified economic costs where available'
            ],
            strict_criteria='Documented consequences of the invasion at the population, community, ecosystem, or socioeconomic level. MUST describe an effect or outcome attributable to the species\' presence. Predictions and modelled future impacts are included if clearly labelled.',
            exclusion_rules='Exclude: direct organism-to-organism interactions (species_interactions), the introduction route (introduction_pathways), control measures (management_biosecurity), methods used to detect population effects (detection_monitoring). The distinction: named species interaction = species_interactions; population-level or ecosystem-level consequence = impacts.',
            prompt_file='impacts_prompt.md',
            search_terms=[
                '"invasive" "economic cost" aquatic species quantified',
                '"invasive" "cost-benefit" management intervention aquatic',
                '"invasive" "impact assessment" aquatic quantified management',
                '"invasive" "fisheries" damage aquatic economic loss',
                '"invasive" "aquaculture" damage aquatic economic loss',
                '"invasive" "ecological impact" aquatic "management implications"',
                '"InvaCost" aquatic invasive economic cost',
                '"invasion debt" aquatic invasive economic',
                '"EICAT" classification aquatic invasive impact score',
                '"SEICAT" socioeconomic impact aquatic invasive classification',
                '"invasive" "socioeconomic impact" classification score assessment',
            ],
            dashboard_card='impacts',
            priority_tier='management_core'
        ),

        'introduction_pathways': TopicDefinition(
            key='introduction_pathways',
            display_name='Introduction & Spread Pathways',
            short_description='Primary introduction vectors, secondary spread mechanisms, ballast water, hull fouling, aquaculture escape, ornamental trade, live bait, canal connections, human-assisted dispersal',
            detailed_description='Pathway analysis for aquatic invasive species, with emphasis on information useful for prevention and biosecurity. Prioritises management-applicable pathway studies: ballast water management (BWM Convention compliance and effectiveness), biofouling management standards (IMO), propagule pressure quantification used in risk assessments, and pathway risk analyses that inform inspection or screening priorities. A paper is management-applicable if its pathway data feeds into a prevention strategy, risk-based inspection framework, or regulatory measure — not if it merely describes how a species arrived historically.',
            key_concepts=[
                'Ballast water discharge',
                'Hull fouling and biofouling on vessels',
                'Aquaculture escape and intentional stocking',
                'Ornamental and aquarium trade release',
                'Live bait and fishing gear transport',
                'Canal and waterway connections between basins',
                'Recreational boating and equipment transport',
                'Natural dispersal assisted by hydrological connectivity',
                'Food trade and live seafood markets',
                'Propagule pressure and introduction frequency'
            ],
            strict_criteria='Information about the MECHANISM or VECTOR of movement, not the destination or timing of arrival. MUST describe how the organism moved, not where it ended up. Pathway = the route and means of transport.',
            exclusion_rules='Exclude: where the species spread to (distribution_and_status), when it arrived at a location (distribution_and_status), the ecological consequences of its arrival (impacts), efforts to prevent spread (management_biosecurity). Pathway/vector YES, destination and timing NO.',
            prompt_file='introduction_pathways_prompt.md',
            search_terms=[
                '"ballast water management" convention compliance effectiveness',
                '"pathway management" aquatic invasive biosecurity',
                '"pathway analysis" aquatic invasive biosecurity prevention',
                '"propagule pressure" aquatic invasive establishment prevention',
                '"biofouling" hull fouling management vessel shipping invasive',
                '"aquarium trade" invasive pathway risk introduction',
                '"ornamental trade" invasive pathway risk introduction',
                '"biosecurity" pathway prevention regulation aquatic invasive',
            ],
            dashboard_card='introduction_pathways',
            priority_tier='management_core'
        ),

        'management_biosecurity': TopicDefinition(
            key='management_biosecurity',
            display_name='Management & Biosecurity',
            short_description='Control methods, eradication programmes, prevention measures, biosecurity protocols, regulations, rapid response, management effectiveness and outcomes',
            detailed_description='Deliberate interventions to prevent, control, or eradicate aquatic invasive species. This topic prioritises literature that answers management questions: what control methods worked, at what scale, at what cost, and with what outcomes. Key paper types: field-scale intervention outcome studies, eradication programme assessments (with success metrics), cost-benefit analyses, rapid response case studies, systematic reviews of control effectiveness, and EU IAS Regulation (1143/2014) compliance documentation. A paper is management-applicable if a biosecurity officer or resource manager could directly act on its findings.',
            key_concepts=[
                'Physical removal and mechanical control',
                'Chemical control (molluscicides, piscicides, herbicides, biocides)',
                'Biological control agents and natural enemies',
                'Physical barriers and exclusion structures',
                'Environmental modification and habitat manipulation',
                'Prevention and border biosecurity measures',
                'Early detection and rapid response protocols',
                'Eradication programmes and outcomes',
                'Regulations, trade restrictions, and listing status actions',
                'Biosecurity decontamination procedures',
                'Management effectiveness evidence and cost data',
                'Stakeholder engagement and public reporting schemes'
            ],
            strict_criteria='Information about deliberate interventions or regulatory actions to prevent, detect, control, or eradicate the species. MUST describe an action taken or a regulation/protocol in place. Evidence of management success or failure belongs here.',
            exclusion_rules='Exclude: how the species spreads naturally (introduction_pathways), the ecological impacts being managed (impacts), natural biological control factors not deliberately applied (species_interactions), conservation of native species populations (not the invasive). Management of invasive populations YES; natural regulation of invasive populations NO.',
            prompt_file='management_biosecurity_prompt.md',
            search_terms=[
                '"management effectiveness" aquatic invasive control eradication',
                '"systematic review" invasive control management aquatic',
                '"meta-analysis" invasive control management aquatic',
                '"rapid response" aquatic invasive eradication case study',
                '"cost-benefit" aquatic invasive control management',
                '"cost-effectiveness" aquatic invasive control management',
                '"feasibility" eradication containment aquatic invasive',
                '"management implications" aquatic invasive intervention',
                '"biosecurity protocol" aquatic pathway decontamination',
                '"EU Regulation 1143" invasive alien species management',
            ],
            dashboard_card='management_biosecurity',
            priority_tier='management_core'
        ),

        'detection_monitoring': TopicDefinition(
            key='detection_monitoring',
            display_name='Detection & Monitoring',
            short_description='Identification methods, morphological keys, eDNA detection, surveillance protocols, population monitoring, citizen science reporting, early warning systems',
            detailed_description='Field-applicable methods for detecting and monitoring aquatic invasive species. This topic prioritises protocol-level and evaluation papers: eDNA detection methodology with validated sensitivity/specificity data, surveillance design frameworks (site prioritisation, sampling frequency, trigger thresholds), early detection systems with documented effectiveness, and citizen science programme assessments. A paper is management-applicable if it describes a method that could be implemented in a monitoring programme — not just a detection event that generated a distribution record.',
            key_concepts=[
                'Visual identification and diagnostic morphological features',
                'Taxonomic keys and identification guides',
                'Environmental DNA (eDNA) detection methods',
                'Metabarcoding and molecular identification',
                'Water sampling and plankton tow protocols',
                'Trapping and netting survey methods',
                'Acoustic and remote sensing detection',
                'Citizen science and public reporting platforms',
                'Population abundance and density monitoring',
                'Surveillance design and site prioritisation',
                'Early warning and alert systems'
            ],
            strict_criteria='Information about HOW to find, identify, or monitor the species. MUST describe a method, tool, protocol, or system for detection or surveillance. Includes both field methods and laboratory techniques.',
            exclusion_rules='Exclude: geographic occurrence records generated by monitoring (distribution_and_status), ecological consequences detected through monitoring (impacts), management actions triggered by detection (management_biosecurity). The monitoring method itself belongs here; what the monitoring found goes elsewhere.',
            prompt_file='detection_monitoring_prompt.md',
            search_terms=[
                '"eDNA" aquatic invasive detection protocol sensitivity',
                '"environmental DNA" aquatic invasive detection protocol sensitivity',
                '"surveillance protocol" aquatic invasive monitoring design',
                '"monitoring design" aquatic invasive surveillance sampling',
                '"early detection" rapid response aquatic invasive effectiveness',
                '"detection sensitivity" aquatic invasive monitoring',
                '"detection probability" aquatic invasive monitoring',
                '"horizon scanning" aquatic invasive species risk',
                '"citizen science" aquatic invasive monitoring effectiveness',
            ],
            dashboard_card='detection_monitoring',
            priority_tier='management_core'
        ),
    }

    # Highlight colours per topic — used by the PDF preview annotator and the UI legend.
    # Stored as hex strings for CSS/Streamlit and converted to (r, g, b) 0-1 tuples for PyMuPDF.
    TOPIC_COLORS: Dict[str, str] = {
        'taxonomic_identity':      '#B8E0F7',  # light blue
        'biological_traits':       '#C8F0D0',  # light green
        'distribution_and_status': '#FFE4B5',  # light orange
        'habitat_ecology':         '#D4F0C0',  # sage green
        'species_interactions':    '#FFD6E7',  # light pink
        'impacts':                 '#FFB3B3',  # light red
        'introduction_pathways':   '#E8D5F5',  # light purple
        'management_biosecurity':  '#FFF3B0',  # light yellow
        'detection_monitoring':    '#D0E8FF',  # light teal
    }

    @classmethod
    def get_topic_color_hex(cls, topic_key: str) -> str:
        """Return hex colour string for a topic key, or a neutral grey fallback."""
        return cls.TOPIC_COLORS.get(topic_key, '#E0E0E0')

    @classmethod
    def get_topic_color_rgb(cls, topic_key: str) -> tuple:
        """Return (r, g, b) tuple in 0-1 range for PyMuPDF highlight annotation."""
        hex_color = cls.get_topic_color_hex(topic_key).lstrip('#')
        r, g, b = (int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b)

    # System categories for backend use
    SYSTEM_CATEGORIES = {
        'data_metadata': 'Source URLs, database IDs, data quality indicators, timestamps, geographic scope metadata, image URLs, citation information',
        'needs_review': 'Data requiring human review due to: mixed content spanning multiple categories, ambiguous categorisation, unclear source information, or insufficient context to determine correct category'
    }

    @classmethod
    def get_all_topic_keys(cls) -> List[str]:
        """Get list of all topic keys (underscore format)."""
        return list(cls.TOPICS.keys())

    @classmethod
    def get_all_display_names(cls) -> List[str]:
        """Get list of all display names (user-facing format)."""
        return [topic.display_name for topic in cls.TOPICS.values()]

    @classmethod
    def get_topic(cls, key: str) -> Optional[TopicDefinition]:
        """
        Get a topic definition by key.

        Args:
            key: Topic key (underscore format, e.g., 'habitat_ecology')

        Returns:
            TopicDefinition or None if not found
        """
        return cls.TOPICS.get(key)

    @classmethod
    def get_topic_by_display_name(cls, display_name: str) -> Optional[TopicDefinition]:
        """
        Get a topic definition by display name.

        Args:
            display_name: Display name (e.g., 'Habitat & Ecology')

        Returns:
            TopicDefinition or None if not found
        """
        for topic in cls.TOPICS.values():
            if topic.display_name == display_name:
                return topic
        return None

    @classmethod
    def get_short_descriptions(cls) -> Dict[str, str]:
        """
        Get short descriptions for all topics (for UI tooltips and categorisation).

        Returns:
            Dict mapping topic key to short description
        """
        return {key: topic.short_description for key, topic in cls.TOPICS.items()}

    @classmethod
    def get_strict_criteria(cls) -> Dict[str, str]:
        """
        Get strict classification criteria for all topics (for AI categorisation).

        Returns:
            Dict mapping topic key to strict criteria
        """
        return {key: topic.strict_criteria for key, topic in cls.TOPICS.items()}

    @classmethod
    def get_exclusion_rules(cls) -> Dict[str, str]:
        """
        Get exclusion rules for all topics (for AI categorisation).

        Returns:
            Dict mapping topic key to exclusion rules
        """
        return {key: topic.exclusion_rules for key, topic in cls.TOPICS.items()}

    @classmethod
    def get_prompt_file_mapping(cls) -> Dict[str, str]:
        """
        Get mapping of topic keys to prompt filenames.

        Returns:
            Dict mapping topic key to prompt filename
        """
        return {key: topic.prompt_file for key, topic in cls.TOPICS.items()}

    @classmethod
    def get_dashboard_card_mapping(cls) -> Dict[str, str]:
        """
        Get mapping of topic keys to dashboard card keys.

        Returns:
            Dict mapping topic key to dashboard card key
        """
        return {key: topic.dashboard_card for key, topic in cls.TOPICS.items()}

    @classmethod
    def get_valid_categories(cls, include_system_categories: bool = True) -> List[str]:
        """
        Get list of all valid category keys for validation.

        Args:
            include_system_categories: Whether to include data_metadata and needs_review

        Returns:
            List of valid category keys
        """
        categories = cls.get_all_topic_keys()
        if include_system_categories:
            categories.extend(cls.SYSTEM_CATEGORIES.keys())
        return categories

    @classmethod
    def normalize_topic_name(cls, name: str) -> Optional[str]:
        """
        Normalise a topic name to its standard key format.

        Handles various formats:
        - Display format: "Habitat & Ecology" → "habitat_ecology"
        - Space format: "habitat & ecology" → "habitat_ecology"
        - Underscore format: "habitat_ecology" → "habitat_ecology"

        Args:
            name: Topic name in any format

        Returns:
            Standardised key or None if not recognised
        """
        if not name:
            return None

        # Already in correct format
        if name in cls.TOPICS:
            return name

        # Try exact display name match
        topic = cls.get_topic_by_display_name(name)
        if topic:
            return topic.key

        # Try case-insensitive underscore conversion
        normalized = name.lower().strip().replace(' ', '_').replace('&', '').replace('__', '_')
        if normalized in cls.TOPICS:
            return normalized

        return None

    @classmethod
    def get_full_schema(cls) -> Dict[str, Any]:
        """
        Get complete schema including all topics and system categories.

        Returns:
            Dict with all categories and their descriptions
        """
        schema = cls.get_short_descriptions()
        schema.update(cls.SYSTEM_CATEGORIES)
        return schema

    @classmethod
    def get_search_terms(cls, topic_key: str) -> Optional[List[str]]:
        """
        Get predefined search terms for a topic.

        Args:
            topic_key: Topic key (underscore format, e.g., 'habitat_ecology')

        Returns:
            List of search terms or None if topic not found
        """
        topic = cls.get_topic(topic_key)
        return topic.search_terms if topic else None

    @classmethod
    def get_categorisation_guide(cls) -> str:
        """
        Get a formatted guide for AI categorisation with priority rules.

        Returns:
            String containing categorisation rules and examples
        """
        guide = """CATEGORISATION RULES - STRICT MUTUAL EXCLUSIVITY

Each piece of information goes to EXACTLY ONE category.
Apply the FIRST category that matches based on priority order.

PRIORITY ORDER:
1. Taxonomic Identity - scientific names/classification ONLY
2. Biological Traits - organism-level biology, morphology, physiology, behaviour ONLY
3. Distribution & Status - geographic occurrence, establishment status, formal listings ONLY
4. Habitat & Ecology - ecosystem-level habitat conditions and niche ONLY
5. Species Interactions - named organism-to-organism interactions ONLY
6. Impacts - population/ecosystem/socioeconomic consequences ONLY
7. Introduction & Spread Pathways - vectors and mechanisms of movement ONLY
8. Management & Biosecurity - deliberate control/prevention interventions ONLY
9. Detection & Monitoring - identification and surveillance methods ONLY

EXAMPLES OF CORRECT CATEGORISATION:

"Found in New Zealand since 2015" → Distribution & Status (location + when)
"IUCN: Least Concern" → Distribution & Status (formal conservation listing)
"EU IAS Regulation concern species" → Distribution & Status (regulatory listing status)
"Has red and white stripes" → Biological Traits (morphology)
"Grows 2cm per year" → Biological Traits (growth rate)
"Egg production: 10,000 per female" → Biological Traits (reproductive rate/fecundity)
"Tolerates temperatures 5-25°C" → Habitat & Ecology (abiotic environmental condition)
"Found in shallow littoral zones with sandy substrate" → Habitat & Ecology (ecosystem habitat description)
"Competes with Mytilus galloprovincialis" → Species Interactions (named organism interaction)
"Preys on Salmo trutta" → Species Interactions (named prey species)
"Reduced mussel populations by 40%" → Impacts (documented population consequence)
"Causes €2M annual fishery losses" → Impacts (quantified socioeconomic consequence)
"Spread via ballast water" → Introduction & Spread Pathways (introduction mechanism)
"Introduced through aquarium trade" → Introduction & Spread Pathways (introduction vector)
"Controlled using copper-based biocides" → Management & Biosecurity (control method)
"Banned for import under EU regulations" → Management & Biosecurity (regulation)
"Can be identified using COI gene primers" → Detection & Monitoring (identification method)

EDGE CASES:

"Temperature tolerance: -2 to 30°C" → Habitat & Ecology (abiotic environmental condition)
"Recorded in rivers with temperature 15-20°C" → Habitat & Ecology (environmental conditions of occupied habitat)
"Displaces native barnacles through competition" → Impacts (population consequence), NOT Species Interactions
"Listed as Prohibited Organism" → Management & Biosecurity (regulation)
"Hitchhikes on ship hulls" → Introduction & Spread Pathways (transport mechanism)
"Population declining in native range" → Distribution & Status (population trend + native range context)
"""
        return guide