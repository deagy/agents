"""Configuration loading and validation for the knowledge store."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


DEFAULTS: dict[str, Any] = {
    "database": "./data/knowledge.db",
    "embedding": {
        "provider": "hashing",
        "model": "feature-hash-v1",
        "dimensions": 384,
        "base_url": None,
        "api_key_env": "KNOWLEDGE_EMBEDDING_API_KEY",
        "batch_size": 32,
        "timeout_seconds": 30,
    },
    "chunking": {"max_characters": 2400, "overlap_characters": 240},
    "ingestion": {"default_classification": "internal", "redact_secrets": True},
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _positive_integer(value: Any, name: str, minimum: int = 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")


def default_config_path() -> Path:
    """Resolve the implicit config location: KNOWLEDGE_STORE_HOME, else ~/.agents/knowledge-store.

    This is a single store shared across every project on the machine, by design —
    see agents/knowledge-store/SECURITY.md for the source-based partitioning this
    requires of callers.
    """
    home = os.environ.get("KNOWLEDGE_STORE_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".agents" / "knowledge-store"
    return base / "config.json"


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load config, failing closed when an explicit path does not exist."""
    if config_path:
        selected = Path(config_path).resolve()
        if not selected.is_file():
            raise FileNotFoundError(f"Explicit config file does not exist: {selected}")
    else:
        selected = default_config_path()

    supplied: dict[str, Any] = {}
    if selected.is_file():
        with selected.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("Configuration root must be a JSON object")
        supplied = loaded

    config = _merge(DEFAULTS, supplied)
    for section in ("embedding", "chunking", "ingestion"):
        if not isinstance(config.get(section), dict):
            raise ValueError(f"{section} must be a JSON object")
    if not isinstance(config.get("database"), str) or not config["database"].strip():
        raise ValueError("database must be a non-empty string")
    base_directory = selected.parent
    database = Path(config["database"])
    config["database"] = str((base_directory / database).resolve() if not database.is_absolute() else database.resolve())

    embedding = config["embedding"]
    if embedding["provider"] not in {"hashing", "openai-compatible"}:
        raise ValueError(f"Unsupported embedding provider: {embedding['provider']}")
    _positive_integer(embedding["dimensions"], "embedding.dimensions", 32)
    _positive_integer(embedding["batch_size"], "embedding.batch_size")
    timeout = embedding.get("timeout_seconds", 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > 300:
        raise ValueError("embedding.timeout_seconds must be greater than 0 and at most 300")
    if not isinstance(embedding.get("model"), str) or not embedding["model"].strip():
        raise ValueError("embedding.model must be a non-empty string")

    chunking = config["chunking"]
    _positive_integer(chunking["max_characters"], "chunking.max_characters")
    if isinstance(chunking["overlap_characters"], bool) or not isinstance(chunking["overlap_characters"], int) or chunking["overlap_characters"] < 0:
        raise ValueError("chunking.overlap_characters must be a non-negative integer")
    if chunking["overlap_characters"] >= chunking["max_characters"]:
        raise ValueError("chunk overlap must be smaller than max_characters")
    return config
