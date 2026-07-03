# Document Topic Relevance Analysis Prompt

You are analyzing a research document's structure to identify relevant extraction topics.

Your goal is to determine which research topics are covered in this document based ONLY on the provided document information (which may include table of contents, abstract, keywords, and/or section headings).

---

## Document Information:

```
{toc_text}
```

---

## Available Topics for Extraction:

{topic_definitions}

---

## Your Task:

For **each topic** listed above, determine its relevance to this document based **ONLY** on the provided document information above.

### What You May Receive:

- **TABLE OF CONTENTS** - Section structure from PDF metadata (most reliable)
- **ABSTRACT** - Summary of the paper's content and scope
- **KEYWORDS** - Author-selected terms describing the paper's focus
- **SECTION HEADINGS** - Headings extracted from the document text

Use ALL available signals to score topics. Keywords and abstract content are strong indicators.

### Scoring Guidelines:

- **0.9-1.0**: Topic is explicitly named in TOC section, keywords, or is a primary focus in the abstract
  - Example: Keywords include "morphology" → morphological_traits scores 0.9

- **0.7-0.8**: Strong indication - topic clearly mentioned in abstract or has a dedicated section
  - Example: Abstract mentions "body size and shell shape" → morphological_traits scores 0.75

- **0.5-0.6**: Moderate relevance - topic implied by keywords, abstract context, or related sections
  - Example: Abstract discusses "adaptation to new environments" → habitat_ecology scores 0.55

- **0.3-0.4**: Weak relevance - tangential mention possible
  - Example: Abstract focuses on genetics but mentions "field observations" → behavioral_traits scores 0.35

- **0.0-0.2**: No relevance - no signals indicate this topic is covered
  - Example: No mention of economics anywhere → economic_utilisation scores 0.0

### Critical Rules:

1. **Base scores ONLY on provided information** - Do NOT use your training data or general knowledge about the species
2. **Be conservative** - Only assign high scores (>0.7) if the topic is explicitly mentioned
3. **Score ALL topics** - Even if a topic scores 0.0, include it in your response
4. **Provide reasoning** - Cite specific sections, keywords, or abstract phrases that justify your score

---

## Output Format:

Return ONLY valid JSON in this exact format:

```json
{{
  "topic_key_1": {{
    "score": 0.85,
    "reasoning": "Section 3.1 'Morphological Features' directly covers this topic"
  }},
  "topic_key_2": {{
    "score": 0.6,
    "reasoning": "Section 4 'Distribution Patterns' suggests some distribution data"
  }},
  "topic_key_3": {{
    "score": 0.0,
    "reasoning": "No sections in TOC relate to this topic"
  }}
}}
```

---

## CRITICAL FORMATTING REQUIREMENTS:

- Return **ONLY** the JSON object (no explanatory text before or after)
- Use double quotes for all keys and string values
- Ensure all braces are properly closed
- No trailing commas
- Score must be a number between 0.0 and 1.0
- Include reasoning for every topic

---

**YOUR JSON RESPONSE:**
