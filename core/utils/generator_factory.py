# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
AI Generator Factory

Single entry point for creating AI generators across the entire codebase.

To change a model or temperature: edit the agents.json file next to the agents.
To add a new functionality: drop an agents.json alongside your agents — it's picked up automatically.

Config files:
  functionalities/extraction/agents.json
  functionalities/data_aggregation/agents.json
  functionalities/report_generation/agents.json
  functionalities/source_finding/agents.json
  core/config/agents.json
"""

import json
from pathlib import Path
from typing import Any

from haystack.utils import Secret
from haystack_integrations.components.generators.mistral import MistralChatGenerator

from core.utils.config_loader import get_api_key, get_project_root

_MISTRAL_API_KEY = get_api_key("MISTRAL_API_KEY")
_merged_config: dict | None = None


def _load_all_configs() -> dict:
    """
    Discover and merge all agents.json files in the project.
    Agent names must be unique across files — a duplicate raises immediately.
    """
    global _merged_config
    if _merged_config is not None:
        return _merged_config

    root = get_project_root()
    merged: dict = {}

    for config_path in sorted(p for p in root.rglob("agents.json") if ".claude" not in p.parts):
        with open(config_path, "r") as f:
            data = json.load(f)

        for agent_name, agent_cfg in data.get("agents", {}).items():
            if agent_name in merged:
                raise ValueError(
                    f"Duplicate agent name '{agent_name}' found in {config_path}. "
                    f"Agent names must be unique across all agents.json files."
                )
            merged[agent_name] = agent_cfg

    _merged_config = merged
    return _merged_config


def get_agent_config(agent_name: str) -> dict:
    """Return the raw config dict for a named agent from agents.json.

    Useful for reading agent-specific flags (e.g. coverage_check, max_tokens)
    that are stored in agents.json but not consumed by create_generator.

    Raises:
        KeyError: If agent_name is not found in any agents.json.
    """
    config = _load_all_configs()
    if agent_name not in config:
        known = ", ".join(sorted(config.keys()))
        raise KeyError(f"Unknown agent '{agent_name}'. Known agents: {known}")
    return config[agent_name]


def create_generator(agent_name: str) -> Any:
    """
    Create a fully configured Mistral generator for the named agent.

    Model and temperature are read from the agents.json file
    next to the agent's functionality folder.

    Args:
        agent_name: Key from any agents.json file (e.g. "data_extraction", "synonym_cleaner")

    Returns:
        MistralChatGenerator with model and temperature pre-set.

    Example:
        generator = create_generator("data_extraction")
        # → MistralChatGenerator(model="mistral-medium-latest", generation_kwargs={"temperature": 0.1})
    """
    config = _load_all_configs()

    if agent_name not in config:
        known = ", ".join(sorted(config.keys()))
        raise KeyError(f"Unknown agent '{agent_name}'. Known agents: {known}")

    agent_cfg = config[agent_name]
    model = agent_cfg["model"]
    generation_kwargs = {"temperature": agent_cfg["temperature"]}
    if "max_tokens" in agent_cfg:
        generation_kwargs["max_tokens"] = agent_cfg["max_tokens"]

    return MistralChatGenerator(
        api_key=Secret.from_token(_MISTRAL_API_KEY),
        model=model,
        generation_kwargs=generation_kwargs,
    )
