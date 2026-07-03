# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Defensive argument coercion for Mistral tool-call dispatch.

Haystack 2.18 + mistral-haystack 0.3.x occasionally delivers tc.arguments as a
malformed dict whose first key is the literal character '{'.  This is a streaming
chunk-aggregation bug upstream: the JSON string '{"query":"...","field_name":"..."}'
arrives split across SSE chunks and the SDK zips characters of the key-string with
the remaining parsed values, producing {'{': 'query', 'value': '...', ...}.

coerce_tool_args() validates and recovers tool-call args before **kwargs splat so
one bad tool call skips gracefully instead of crashing the entire paper extraction.
"""

import json
import warnings
from typing import Optional, Any

_ALLOWED = frozenset(("query", "field_name", "reasoning", "value"))
_REQUIRED = frozenset(("query", "field_name", "reasoning"))


def coerce_tool_args(tc: Any) -> Optional[dict]:
    """
    Validate and recover a Mistral tool-call's arguments dict before **kwargs splat.

    Returns a clean dict containing only allowed keys, or None if unrecoverable.
    Prints a WARNING on any anomaly so the raw shape appears in terminal logs.

    Args:
        tc: A Haystack ToolCall object (tc.arguments is either a dict or str).

    Returns:
        Clean dict with keys in {query, field_name, reasoning, value}, or None.
    """
    args = tc.arguments

    # --- Case 1: None ---
    if args is None:
        warnings.warn(
            f"[coerce_tool_args] tc.arguments is None — skipping tool call. "
            f"tool_call repr: {tc!r}",
            stacklevel=2,
        )
        return None

    # --- Case 2: string — attempt JSON parse ---
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as exc:
            warnings.warn(
                f"[coerce_tool_args] tc.arguments is a non-JSON string — skipping. "
                f"Error: {exc}. Raw: {args[:200]!r}",
                stacklevel=2,
            )
            return None

    if not isinstance(args, dict):
        warnings.warn(
            f"[coerce_tool_args] tc.arguments is neither dict nor str (got {type(args).__name__}) "
            f"— skipping. Raw: {args!r}",
            stacklevel=2,
        )
        return None

    # --- Case 3: dict — apply recovery heuristics then whitelist ---

    # Known Haystack 2.18 / mistral-haystack 0.3.x streaming bug:
    # arguments arrives as {'{': 'query', 'value': '...', 'field_name': '...', 'reasoning': '...'}
    # The literal '{' key is the opening brace of the JSON string, and its value 'query' is the
    # first key name. The remaining key-value pairs are correct. Recover by dropping '{' and
    # promoting any intact 'query' value if present, or constructing a warning-only skip.
    if "{" in args and args["{"] == "query":
        raw_repr = repr(args)
        remaining = {k: v for k, v in args.items() if k != "{"}

        if "query" in remaining:
            # Stray '{' key but query survived intact — just drop '{'.
            warnings.warn(
                f"[coerce_tool_args] Dropped stray '{{' key (Haystack streaming bug). "
                f"Raw: {raw_repr}",
                stacklevel=2,
            )
            args = remaining
        elif remaining.get("value"):
            # Streaming bug shifts params: query text lands in 'value'.
            # Promote 'value' → 'query'; original 'value' (concise answer) is lost.
            recovered_query = remaining.pop("value")
            args = {"query": recovered_query, **remaining, "value": ""}
            warnings.warn(
                f"[coerce_tool_args] Promoted 'value' → 'query' (Haystack streaming bug). "
                f"Raw: {raw_repr} → Recovered: {args!r}",
                stacklevel=2,
            )
        else:
            warnings.warn(
                f"[coerce_tool_args] Malformed tool-call args — unrecoverable (no query or value). "
                f"Raw: {raw_repr}",
                stacklevel=2,
            )
            return None

    # Whitelist: drop any key not in _ALLOWED
    unknown = set(args.keys()) - _ALLOWED
    if unknown:
        warnings.warn(
            f"[coerce_tool_args] Dropping unknown kwargs {unknown!r} from tool-call args.",
            stacklevel=2,
        )
    clean = {k: v for k, v in args.items() if k in _ALLOWED}

    # Required-key check
    missing = _REQUIRED - clean.keys()
    if missing:
        warnings.warn(
            f"[coerce_tool_args] Required keys {missing!r} absent after coercion — skipping. "
            f"Cleaned args: {clean!r}",
            stacklevel=2,
        )
        return None

    return clean
