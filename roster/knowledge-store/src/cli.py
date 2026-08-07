#!/usr/bin/env python3
"""Command-line interface for the vectorized knowledge store."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from config import TIER_GLOBAL_FALLBACK, load_config
from database import open_store, store_stats
from service import build_agent_context, ingest_file, search_store, stable_query_id
from settings import SettingsError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Local agent knowledge store")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_config(command: argparse.ArgumentParser) -> None:
        command.add_argument("--config")

    init = subparsers.add_parser("init")
    add_config(init)
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--input", required=True)
    # No default here: the shared global-fallback tier requires an explicit,
    # caller-supplied --source (KS-FR-10); the "chat-export" default is
    # still applied, but only for project-local/explicit-config tiers, in
    # _enforce_ingest_scope below (KS-FR-11).
    ingest.add_argument("--source")
    ingest.add_argument("--classification")
    add_config(ingest)
    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--classification", required=True)
    search.add_argument("--top")
    search.add_argument("--source")
    search.add_argument("--all-sources", action="store_true")
    add_config(search)
    context = subparsers.add_parser("context")
    context.add_argument("--agent", required=True)
    context.add_argument("--task-id", required=True, dest="task_id")
    context.add_argument("--query", required=True)
    context.add_argument("--classification", required=True)
    context.add_argument("--top")
    context.add_argument("--source")
    context.add_argument("--all-sources", action="store_true")
    add_config(context)
    stats = subparsers.add_parser("stats")
    add_config(stats)
    return parser


def _enforce_retrieval_scope(tier: str, options: dict[str, Any]) -> None:
    """Gate `search`/`context` at the shared global-fallback tier only (KS-FR-4..9).

    Project-local and explicit-`--config` tiers already isolate by database
    or explicit caller choice, so no new requirement is imposed on them
    (KS-FR-7). This check runs before any embedding call or database query
    (KS-NFR-3).
    """
    if tier != TIER_GLOBAL_FALLBACK:
        return
    source = options.get("source")
    all_sources = options.get("all_sources")
    if source and all_sources:
        raise ValueError(
            "Ambiguous scope: pass either --source <project-identifier> or "
            "--all-sources against the shared global knowledge store, not both."
        )
    if not source and not all_sources:
        raise ValueError(
            "A project scope is required against the shared global knowledge store: "
            "pass --source <project-identifier> to scope this query, or --all-sources "
            "to explicitly opt into cross-project retrieval."
        )


def _enforce_ingest_scope(tier: str, options: dict[str, Any]) -> None:
    """Gate `ingest` at the shared global-fallback tier only (KS-FR-10..12)."""
    if options.get("source"):
        return
    if tier == TIER_GLOBAL_FALLBACK:
        raise ValueError(
            "A project scope is required to ingest into the shared global knowledge "
            "store: pass --source <project-identifier> identifying the ingesting project."
        )
    options["source"] = "chat-export"


def run(arguments: list[str] | None = None) -> dict[str, Any]:
    options = vars(_parser().parse_args(arguments))
    command = options.pop("command")
    config, tier = load_config(options.pop("config", None), return_tier=True)
    db = open_store(config["database"])
    try:
        if command == "init":
            return {"status": "initialized", "database": config["database"]}
        if command == "ingest":
            _enforce_ingest_scope(tier, options)
            options["classification"] = options.get("classification") or config["ingestion"]["default_classification"]
            return ingest_file(db, config, options)
        if command == "search":
            _enforce_retrieval_scope(tier, options)
            options.pop("all_sources", None)
            query = options.pop("query")
            results = search_store(db, config, query, options)
            return {"query_id": stable_query_id(query), "results": results}
        if command == "context":
            _enforce_retrieval_scope(tier, options)
            options.pop("all_sources", None)
            return build_agent_context(db, config, options.pop("query"), options)
        if command == "stats":
            return store_stats(db)
        raise ValueError(f"Unknown command: {command}")
    finally:
        db.close()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="strict", newline="\n")
    try:
        result = run()
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, SettingsError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
