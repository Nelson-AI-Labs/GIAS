# Unified Extraction System

**Version 1.0.0** - Consolidated architecture combining Source Extraction Pipeline (SEP) and Custom Topic System (CTS)

## Overview

This module provides a unified extraction system for extracting structured data from research PDFs. It consolidates what were previously two separate systems (SEP and CTS) into a single coherent architecture with shared utilities and clear separation of concerns.

### The Problem (Before Consolidation)

- CTS and SEP maintained separate folder structures
- Duplicate implementations of core functionality (file I/O, prompt loading, validation)
- Changes to extraction logic required updates in multiple places
- Architectural confusion: separate systems or one system with two modes?

### The Solution (After Consolidation)

- Single `extraction/` module with shared infrastructure
- Eliminated duplicate code (output saving, prompt loading, JSON parsing)
- Clear separation: shared utilities vs. specialized components
- CTS is now truly a "side branch" (specialized mode) rather than a separate fork

---

## Architecture

```
extraction/
├── agents/              # All extraction agents
│   ├── data_extraction_agent.py         # SHARED: Core extraction agent
│   ├── verification_agent.py            # SEP-specific: Removes hallucinations
│   ├── verification_evaluator.py        # SEP-specific: Alternative impl
│   ├── custom_topic_interpreter.py      # CTS-specific: Interprets topics
│   ├── custom_prompt_generator.py       # CTS-specific: Generates prompts
│   └── custom_search_term_generator.py  # CTS-specific: Generates search terms
│
├── converters/          # PDF conversion
│   └── pdf_to_markdown.py               # SHARED: PDF → Markdown conversion
│
├── formatters/          # JSON formatting
│   └── json_formatter.py                # SHARED: JSON formatting utilities
│
├── prompts/             # All extraction prompts
│   ├── templates/                       # CTS: Prompt generation templates
│   ├── topics/                          # SEP: 13 topic prompts
│   └── contexts/                        # SEP: 3 context prompts
│
├── pipelines/           # Extraction pipeline orchestration
│   ├── standard_pipeline.py             # SEP: Standard topic extraction
│   └── custom_pipeline.py               # CTS: Custom topic extraction
│
├── utils/               # SHARED UTILITIES (the consolidation core)
│   ├── output_saver.py                  # Consolidated file I/O
│   ├── json_parser.py                   # JSON recovery + validation
│   ├── prompt_loader.py                 # Hierarchical prompt loading
│   ├── validation.py                    # Flat JSON validation (moved from CTS)
│   └── pipeline_executor.py             # Common error handling patterns
│
└── merge_engine.py      # Merges extractions into categorized data
```

---

## Shared vs. Specialized Components

### Shared Infrastructure (Used by Both SEP and CTS)

✅ **Correctly Shared:**
- `DataExtractionAgent` - Core extraction logic
- `PDFToMarkdownConverter` - Document conversion
- **Registries** (`core/registries/`):
  - `StandardTopicRegistry` - 13 predefined research topics (used by extraction, data_aggregation, frontend, report_generation)
  - `ContextPromptRegistry` - 3 always-run context prompts
- Cache utilities (`session_context.py`, `cache_manager.py`)
- **NEW:** Output saving (`output_saver.py`)
- **NEW:** JSON parsing/recovery (`json_parser.py`)
- **NEW:** Prompt loading (`prompt_loader.py`)
- **NEW:** Pipeline utilities (`pipeline_executor.py`)

### SEP-Specific Components

Only used by Standard Extraction Pipeline:
- `ExtractionVerificationAgent` - Removes hallucinated fields
- Predefined extraction prompts (13 topics + 3 contexts)

### CTS-Specific Components

Only used by Custom Topic System:
- `TopicInterpreterAgent` - Interprets custom topics into structured definitions
- `PromptGeneratorAgent` - Generates extraction prompts from interpretations
- `SearchTermGeneratorAgent` - Generates search terms for custom topics
- Prompt generation templates

---

## Key Design Patterns

### 1. Hierarchical Prompt Loading

**Order of precedence:**
1. **Memory cache** - Previously loaded prompts (fastest)
2. **Session cache** - Custom topic prompts (user-generated)
3. **Topic registry** - Standard anchor topics (13 predefined)
4. **Context registry** - Always-run context prompts (3 standard)

```python
from extraction.utils.prompt_loader import load_prompt_with_fallback

prompt, source = load_prompt_with_fallback(
    topic_key="habitat ecology",
    topic_registry=StandardTopicRegistry,
    context_registry=ContextPromptRegistry,
    prompts_directory="extraction/prompts/topics/",
    context_prompts_directory="extraction/prompts/contexts/",
    cache=my_cache
)
# source will be: "memory" | "session_cache" | "topic_registry" | "context_registry"
```

### 2. Consolidated Output Saving

**Single function handles all extraction types:**

```python
from extraction.utils.output_saver import save_extraction_output

result = save_extraction_output(
    extracted_data=data,
    universal_id="species_123",
    source_id="source_456",
    research_topic="habitat ecology",
    source_metadata=metadata,
    species_name="Dreissena polymorpha",
    extraction_type="topic",          # or "context"
    topic_type="anchor",               # optional: "custom", "anchor"
    pipeline_name="standard_pipeline"  # optional: for tracking
)
# Returns: {output_filepath, extraction_timestamp, fields_extracted}
```

**File naming:**
- Topics: `{source_id}_{topic_safe}_{timestamp}_extraction.json`
- Contexts: `context_{source_id}_{context_key}_{timestamp}_extraction.json`

### 3. Robust JSON Parsing

**Multi-strategy recovery:**

```python
from extraction.utils.json_parser import parse_and_validate_extraction

# Automatically tries:
# 1. Direct JSON parse
# 2. Extract from markdown blocks
# 3. Fix common errors (trailing commas, etc.)
# 4. Substring extraction
# 5. Partial field-by-field recovery

validated_data = parse_and_validate_extraction(
    response_text=ai_response,
    strict=True  # Enforce flat JSON structure
)
```

### 4. Flat JSON Validation

**"Photocopy machine" principle - extract only what's in the document:**

```json
{
  "field_name": {
    "value": "string only, no nested objects/arrays",
    "reasoning": "why this value was extracted"
  }
}
```

Validation enforces:
- Each field must have `value` and `reasoning`
- Values must be strings (not nested objects/arrays)
- Empty `{}` is valid when document has no relevant information

---

## Usage Examples

### Standard Topic Extraction (SEP)

```python
from extraction.pipelines.standard_pipeline import run_standard_extraction_pipeline

result = run_standard_extraction_pipeline(
    pdf_bytes=pdf_data,
    source_metadata={
        'id': 'source_123',
        'url': 'https://example.com/paper.pdf',
        'title': 'Research Paper Title',
        'domain': 'example.com'
    },
    species_name="Dreissena polymorpha",
    research_topic="habitat ecology",
    search_terms=["zebra mussel", "habitat"],
    universal_id="species_123",
    save_output=True
)

# Result structure:
# {
#   "extraction_status": "success" | "failed",
#   "extracted_data": {...},
#   "output_filepath": "/path/to/output.json",
#   "error_message": None | "error description",
#   "fields_extracted": 15
# }
```

### Custom Topic Extraction (CTS)

```python
from extraction.pipelines.custom_pipeline import run_custom_topic_extraction

# First, generate custom prompt (separate agent not shown here)
# Then extract data:

result = run_custom_topic_extraction(
    pdf_bytes=pdf_data,
    source_metadata=metadata,
    custom_topic="invasive potential",
    species_name="Dreissena polymorpha",
    search_terms=["invasive", "potential"],
    universal_id="species_123",
    save_output=True,
    strict_flat_json=True
)
```

### Using Shared Utilities Directly

```python
# Load prompts with fallback
from extraction.utils.prompt_loader import load_prompt_with_fallback

prompt, source = load_prompt_with_fallback(
    topic_key="morphological traits",
    topic_registry=StandardTopicRegistry,
    prompts_directory="extraction/prompts/topics/"
)

# Save extraction output
from extraction.utils.output_saver import save_extraction_output

result = save_extraction_output(
    extracted_data=my_data,
    universal_id="species_123",
    source_id="source_456",
    research_topic="habitat ecology",
    source_metadata=metadata,
    species_name="Dreissena polymorpha"
)

# Parse and validate AI response
from extraction.utils.json_parser import parse_and_validate_extraction

data = parse_and_validate_extraction(
    response_text=ai_response,
    strict=True
)
```

---

## Migration Notes

### Phase 1: Utilities Created ✅

New consolidated utilities:
- `extraction/utils/output_saver.py`
- `extraction/utils/json_parser.py`
- `extraction/utils/prompt_loader.py`
- `extraction/utils/pipeline_executor.py`

### Phase 2: Component Migration (Next)

Components to be moved:
- `components/SEP_components/*` → `extraction/agents/`, `extraction/converters/`, etc.
- `components/CTS_components/*` → `extraction/agents/custom_*`
- `core/topics/*` → `extraction/registries/`
- `pipelines/source_extraction_pipeline.py` → `extraction/pipelines/standard_pipeline.py`
- `pipelines/custom_topic_pipeline.py` → `extraction/pipelines/custom_pipeline.py`

### Phase 3: Update Internal Logic

Agents and pipelines will be updated to use consolidated utilities:
- Replace duplicate `_save_extraction_output()` with `utils.output_saver.save_extraction_output()`
- Replace `_parse_response()` with `utils.json_parser.parse_and_validate_extraction()`
- Replace `_load_prompt_for_topic()` with `utils.prompt_loader.load_prompt_with_fallback()`

### Phase 4: Update Imports Across Codebase

Files requiring import updates:
- Frontend UI (`frontend/pages/research/`)
- Core utilities (`core/cache_layer/`)
- Other pipelines

### Phase 5: Cleanup

Remove deprecated directories:
- `components/CTS_components/`
- `components/SEP_components/`
- `core/topics/` (if empty)

---

## Benefits of Consolidation

### Maintenance Reduction
- **Before:** 2 implementations of file I/O, prompt loading, validation
- **After:** 1 implementation each, shared by both systems

### Risk Reduction
- Output format changes → update in one place
- Validation rules → enforced consistently
- Prompt loading logic → guaranteed identical behavior

### Code Clarity
- Clear boundaries between shared and specialized components
- Better separation of concerns (JSON recovery ≠ validation)
- Easier for new developers to understand architecture

### Extensibility
- Future extraction pipelines can reuse shared utilities
- New output formats → add in one place
- Validation rules → evolve without touching multiple files

---

## Testing Strategy

See the full plan document for comprehensive testing strategy covering:
- Phase 1: Unit tests for new utilities
- Phase 2: Import verification and agent functionality
- Phase 3: Pipeline execution with new utilities
- Phase 4: End-to-end workflows
- Phase 5: Regression testing and performance checks

---

## Important Conventions

1. **Flat JSON only** for extraction output
2. **"Photocopy machine" principle** - extract only what's in the document
3. **Empty `{}` is valid** when document has no relevant information
4. **Context extractions get `context_` prefix** in filename
5. **One context extraction round per source** (3 prompts) + N topic extractions

---

## Contributing

When adding new features:
1. **Check for existing utilities first** - don't duplicate
2. **Use shared utilities** - output_saver, json_parser, prompt_loader
3. **Add to appropriate directory** - agents/, utils/, pipelines/, etc.
4. **Update this README** if adding new patterns or utilities
5. **Follow flat JSON convention** for all extraction outputs

---

## Version History

- **1.0.0** (2026-02-09): Initial unified extraction system
  - Consolidated duplicate code from SEP and CTS
  - Created shared utilities module
  - Established clear architectural boundaries
  - Phase 1 complete: Infrastructure ready for component migration
