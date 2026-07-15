# G.I.A.S — GuardIAS Intelligence Analyst System

<div align="center">

![GuardIAS](frontend/images/GuardIASleftlogowhite.png)

**AI-Powered Aquatic Invasive Species Research Platform**

[![Live demo](https://img.shields.io/badge/live%20demo-gias--tool.streamlit.app-FF4B4B.svg)](https://gias-tool.streamlit.app/)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/streamlit-1.50-FF4B4B.svg)](https://streamlit.io)
[![Haystack](https://img.shields.io/badge/haystack-2.18-009688.svg)](https://haystack.deepset.ai/)

*Part of the EU Horizon GuardIAS Project*

**▶ Try it live: [gias-tool.streamlit.app](https://gias-tool.streamlit.app/?gias_cid=96ffa394b7884444b79070f83eb11450/)**

</div>

---

## Overview

**G.I.A.S** (GuardIAS Intelligence Analyst System) turns invasive aquatic species research from a
multi-hour manual process into an automated workflow taking minutes. A user types a species name;
GIAS aggregates data from six biodiversity databases across all taxonomic synonyms, organises it
into a fixed topic model, lets the user deep-research individual papers, and renders a cited PDF
intelligence report. Every fact carries its source — provenance and human oversight are the core
design value.

The platform serves diverse stakeholders — from technical specialists to policy makers — without
requiring database expertise.

### What Problem Does It Solve?

Invasive species researchers typically spend hours manually:
- Searching multiple databases for species information
- Compiling data from disparate sources
- Finding relevant scientific literature
- Cross-referencing synonym name variants
- Synthesising information into coherent reports

**G.I.A.S automates this entire workflow** whilst ensuring every statement traces back to its
original source and keeping humans in control of data interpretation.

---

## The Five-Screen Journey

The frontend replaces Streamlit's native navigation with a custom "journey spine" (`custom_spine`
in `frontend/components.py`). The workflow:

1. **Home** — landing page; explains the workflow.
2. **Search** — type a species; the data-aggregation pipeline queries the six biodiversity
   databases in parallel across all synonyms, then AI-categorises the results.
3. **Knowledge Base** — categorised data as topic cards; every field shows its source chips and
   surfaces conflicts between databases.
4. **Deep Research** — the source-finding pipeline discovers papers; the extraction pipeline pulls
   verified, verbatim facts from approved PDFs.
5. **Report** — the report-generation pipeline filters topics, writes narrative prose, builds a
   distribution map, and renders a cited PDF.

---

## Key Features

### Multi-Database Integration
Simultaneously queries six authoritative biodiversity databases:
- **GBIF** (Global Biodiversity Information Facility) — taxonomy, occurrences, distributions
- **WoRMS/WRiMS** (World Register of Marine / Introduced Marine Species) — marine species authority, biological traits
- **IUCN Red List** — conservation status, population trends, habitat data
- **EASIN** (European Alien Species Information Network) — invasive species alerts, EU regulatory status
- **AquaNIS** (Aquatic Non-Indigenous Species Database) — introduction records, invasion pathways
- **CABI** — invasive species datasheets via SPARQL endpoint

### Synonym-Aware Querying
Automatically searches under all known scientific name variants for comprehensive coverage without
manual cross-referencing. The system validates species names using AI and iterates through all
synonyms when querying databases.

### AI-Powered Data Categorisation
Uses AI to understand contextual relationships between terminology across databases — recognising,
for example, that "native range" and "geographic origin" describe the same concept **whilst
preserving both original phrasings** with source attribution. The AI organises information into
**9 standardised topics** without altering source data.

### Interactive Dashboard (Knowledge Base)
Presents aggregated data in an accessible format for stakeholders with varying technical
backgrounds:
- Species overview with imagery and taxonomic classification
- The 9 research topics (see below)
- Source chips on every data point
- Conflict highlighting when databases disagree
- Static Plotly choropleth distribution maps (world + Europe)
- Modular field rendering that handles varied data structures automatically

### Deep Research Mode
Discovers and processes academic literature with human oversight:

**Finding sources:**
- Queries six academic and grey-literature sources in parallel: Semantic Scholar, Europe PMC,
  OpenAlex, DOAJ, Google Scholar, and Tavily
- Results deduplicated by DOI across all sources
- Users review and approve sources before any extraction

**Extracting information:**
- AI extracts **only explicitly stated facts** from approved sources
- Strict anti-hallucination protocols prevent adding external knowledge
- Extracted facts return verbatim quotes and link back to source paper and author(s)
- Extracted data merges into the dashboard with clear "Research" attribution

### Report Generation
Synthesises all gathered information into a comprehensive PDF species intelligence report:
- **PDF output** rendered from Jinja2 HTML templates via **WeasyPrint**
- Narrative prose written under a strict anti-hallucination prompt (formatter, not interpreter)
- **Four reference styles:** numbered `[1]`, APA 7th, Harvard, Vancouver superscript
- Includes species image/silhouette, EU distribution map, GuardIAS logo, and citations
- Inline PDF preview (`st.pdf`) and one-click download from the Report screen
- Covers both database and research-extracted data

---

## The 9 Research Topics

Defined once in `core/registries/topic_registry.py` (the single source of truth used by
aggregation, extraction, dashboard, and report):

1. **Taxonomic Identity**
2. **Biological Traits**
3. **Distribution & Status**
4. **Habitat & Ecology**
5. **Species Interactions**
6. **Impacts**
7. **Introduction & Spread Pathways**
8. **Management & Biosecurity**
9. **Detection & Monitoring**

---

## Architecture at a Glance

- **Stack:** Streamlit (UI) + Haystack (pipelines). No database — all state is JSON files under a
  session-isolated `cache/<session-id>/` tree.
- **LLM:** Mistral (via `mistral-haystack`). Every AI step is a small single-purpose agent built by
  a generator factory from `agents.json`. There is no OpenAI/Anthropic in the runtime.
- **Data flow:** `species name` → raw API JSON (`raw_api_data/`) → AI categorisation into the
  9-topic registry (`categorized_data/`) → optional research extraction (`extracted_data/`) →
  merge → report PDF.

---

## Installation

### Prerequisites

- Python 3.10+
- pip package manager
- Git
- System libraries for WeasyPrint and Plotly map export (Linux): `chromium`,
  `libpango-1.0-0`, `libpangocairo-1.0-0`, `libgdk-pixbuf-2.0-0`, `libffi-dev`
  (see `packages.txt` — installed automatically on Streamlit Community Cloud)

### Setup

**1. Clone**
```bash
git clone https://github.com/Samuel-VV-NL/GuardIAS.git
cd GuardIAS/GIAS
```

**2. Virtual environment**
```bash
# Linux/macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

**4. Configure API keys**

GIAS reads all keys from `.streamlit/secrets.toml`. The repo ships a template —
copy it and fill in your own keys to run your own instance:

```bash
# Linux/macOS
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Windows
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
```

Then open `.streamlit/secrets.toml` and paste your keys between the quotes. Leave
optional keys blank to skip that source — GIAS runs without them:

```toml
# Required — AI model (extraction + narrative generation)
MISTRAL_API_KEY = ""

# Required — grey-literature search / source finding
TAVILY_API_KEY = ""

# Optional — Google Scholar search via SerpAPI (skipped without it)
SERPAPI_KEY = ""

# Optional — IUCN Red List conservation status (higher rate limits)
IUCN_API_KEY = ""

# Optional — AquaNIS aquatic invasive species database
AQUANIS_API_KEY = ""

# Optional — contact email sent in User-Agent headers to API providers
# CONTACT_EMAIL = "your@email.com"
```

**Get API keys:**
- **Mistral AI** *(required)*: [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys/)
- **Tavily** *(required)*: [app.tavily.com](https://app.tavily.com/)
- **SerpAPI** *(optional — Google Scholar)*: [serpapi.com](https://serpapi.com/manage-api-key)
- **IUCN** *(optional)*: [api.iucnredlist.org](https://api.iucnredlist.org/)
- **AquaNIS** *(optional)*: institutional registration at [aquanis.org](https://www.aquanis.org/)

`secrets.toml` is git-ignored — your keys never get committed.

---

## Quick Start

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`. Or skip setup and use the hosted version:
**[gias-tool.streamlit.app](https://gias-tool.streamlit.app/)**.

### Basic Workflow

1. **Search** — type a scientific name (e.g. `Dreissena polymorpha`). All databases are queried
   simultaneously across every known name variant.
2. **Knowledge Base** — explore aggregated data across the 9 topics; check source chips and
   database conflicts.
3. **Deep Research** *(optional)* — discover additional papers, approve relevant ones, run AI
   extraction; verified facts merge into the dashboard.
4. **Report** — pick topics and a reference style, generate the PDF, preview inline, and download.

---

## Project Structure

Code is organised around four functional domains under `functionalities/`, shared infrastructure
in `core/`, and the Streamlit UI in `frontend/`.

```
GIAS/
├── app.py                          # Entry point: session lifecycle, CSS, nav, sidebar chrome
├── requirements.txt
├── packages.txt                    # System libs for Streamlit Cloud (chromium, pango, …)
├── assets/shell.css                # Single stylesheet (data-testid hooks — pinned to Streamlit 1.50)
│
├── functionalities/                # Four self-contained domains, each a Haystack pipeline
│   ├── data_aggregation/           # Multi-database species data collection
│   │   ├── pipeline.py             #   synonym-iterating aggregation pipeline
│   │   ├── api/                    #   6 database connectors (gbif, wrims, IUCN, easin, aquanis, cabi_sparql)
│   │   ├── agents/                 #   categorisation, name validation, analysis
│   │   ├── orchestration/          #   synonym iteration control
│   │   └── tools/                  #   standardisation + field mapping
│   │
│   ├── source_finding/             # Literature discovery
│   │   ├── pipeline.py
│   │   ├── api/                    #   6 sources (semantic_scholar, europe_pmc, openalex, doaj, google_scholar, tavily)
│   │   ├── agents/                 #   relevance filtering
│   │   └── paginated_fetch.py, pdf_fetcher.py
│   │
│   ├── extraction/                 # Research data extraction
│   │   ├── pipelines/              #   standard + custom-topic pipelines
│   │   ├── agents/                 #   extraction, verification, custom-topic, document analyser
│   │   ├── prompts/                #   per-topic + context prompt templates
│   │   ├── converters/             #   PDF → markdown
│   │   └── merge_engine.py         #   merge extractions into categorised data
│   │
│   └── report_generation/          # PDF report assembly
│       ├── pipeline.py
│       ├── narrative_generator.py  #   AI prose (anti-hallucination)
│       ├── category_filter.py, data_cleaner.py, distribution_extractor.py, map_renderer.py
│       └── report_renderer/        #   Jinja2 templates → WeasyPrint PDF (render_pdf, context_builder, phylopic)
│
├── core/                           # Shared infrastructure
│   ├── registries/                 # topic_registry.py (9 topics — single source of truth) + context_registry
│   ├── utils/                      # config_loader, session_context, cache_manager, species_name_utils, …
│   ├── cache_layer/                # raw / categorized / context JSON stores + cleanup
│   ├── services/                   # categorize_to_json, species_report_service
│   └── dashboard/                  # data retrieval, aggregation, conflict detection, overview_metrics
│
├── frontend/                       # Streamlit UI
│   ├── views/                      # The 5 nav screens: home, ingest (Search), dashboard, research, report
│   ├── components.py               # Sidebar chrome, journey spine, glyphs, credit
│   ├── pages/                      # Shared screen implementations (species_dashboard_v2, research/, …)
│   ├── ui_components/              # Reusable renderers (field_renderers, distribution_map, …)
│   ├── utils/                      # conflict/distribution/vernacular/language/country helpers
│   └── images/
│
├── cache/                          # Runtime, session-isolated
│   └── {session_id}/               #   raw_api_data / categorized_data / extracted_data / search_results
│
└── .streamlit/secrets.toml         # API keys (create this)
```

---

## Data Sources

### Biodiversity databases (Search)
| Source | Coverage | Data provided |
|--------|----------|---------------|
| **GBIF** | 2B+ occurrence records | Taxonomy, synonyms, vernacular names, distributions, occurrences, habitat |
| **WoRMS/WRiMS** | 250k+ marine species | Authoritative marine taxonomy, biological attributes, measurements, status |
| **IUCN Red List** | 150k+ assessed species | Conservation status, population trends, habitat, threats, actions |
| **EASIN** | European alien species registry | Invasive alerts, EU regulatory status, pathways, distributions |
| **AquaNIS** | Global aquatic NIS | Introduction events, establishment records, pathways, regional distributions |
| **CABI** | Global datasheets (SPARQL) | Invasive profiles, host ranges, impacts, management |

### Academic & grey literature (Deep Research)
Six sources queried in parallel: **Semantic Scholar**, **Europe PMC**, **OpenAlex**, **DOAJ**,
**Google Scholar** (capped per run to protect quota), and **Tavily** (grey literature, government
and institutional documents). Results are deduplicated by DOI and approved by the user before
extraction.

---

## Design Principles

- **Multi-stakeholder accessibility** — usable by specialists, biologists, and policy makers alike.
- **Complete traceability** — every statement traces back to its source, with author attribution
  for academic material.
- **Human-in-the-loop** — users approve research sources before extraction and control the final
  report.
- **Data integrity** — original source data is never modified; AI only organises and links related
  concepts.
- **Efficiency** — the research workflow is compressed from hours to minutes without sacrificing
  rigour.

---

## Roadmap

**Now**
- Six-database aggregation with synonym-aware iteration
- 9-topic categorisation with source attribution and conflict detection
- Deep-research literature discovery (6 sources) + verified PDF extraction
- PDF report generation (WeasyPrint) with four reference styles

**Planned**
- Risk-assessment analytical capabilities
- Management-recommendation synthesis
- Multi-species batch processing

---

## Contact

**GuardIAS Project** — [guardias.eu](https://guardias.eu/)

**Developer** — Samuel Vander Velpen
[LinkedIn](https://linkedin.com/in/samuel-vander-velpen-910b31138) ·
[GitHub Issues](https://github.com/Samuel-VV-NL/GuardIAS/issues)

**Acknowledgements** — with thanks to **Julian Maclaren** and **Cris Lovell-Smith** for their
contributions to this project.

---

<div align="center">

**Funded by the European Union**

![EU Funded](frontend/images/EN_FundedbytheEU_RGB_WHITE%20Outline.png)

</div>
</content>
</invoke>
