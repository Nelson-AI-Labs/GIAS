# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Extraction Agents

All agents for the extraction system:

Shared Agents:
- data_extraction_agent: Core extraction agent (used by both SEP and CTS)

SEP-Specific Agents:
- verification_agent: Removes hallucinated fields from extractions

CTS-Specific Agents:
- custom_topic_interpreter: Interprets custom topics into structured definitions
- custom_prompt_generator: Generates extraction prompts from interpretations
- custom_search_term_generator: Generates search terms for custom topics
"""


__all__ = []
