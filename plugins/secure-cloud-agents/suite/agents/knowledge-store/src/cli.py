#!/usr/bin/env python3
"""Command-line interface for the vectorized knowledge store."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from config import load_config
from database import open_store, store_stats
from service import build_agent_context, ingest_file, search_store, stable_query_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="Local agent knowledge store")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_config(command: argparse.ArgumentParser) -> None:
        command.add_argument("--config")

    init = subparsers.add_parser("init")
    add_config(init)
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--input", required=True)
    ingest.add_argument("--source", default="chat-export")
    ingest.add_argument("--classification")
    add_config(ingest)
    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--classification", required=True)
    search.add_argument("--top")
    search.add_argument("--source")
    add_config(search)
    context = subparsers.add_parser("context")
    context.add_argument("--agent", required=True)
    context.add_argument("--task-id", required=True, dest="task_id")
    context.add_argument("--query", required=True)
    context.add_argument("--classification", required=True)
    context.add_argument("--top")
    context.add_argument("--source")
    add_config(context)
    stats = subparsers.add_parser("stats")
    add_config(stats)
    return parser


def run(arguments: list[str] | None = None) -> dict[str, Any]:
    options = vars(_parser().parse_args(arguments))
    command = options.pop("command")
    config = load_config(options.pop("config", None))
    db = open_store(config["database"])
    try:
        if command == "init":
            return {"status": "initialized", "database": config["database"]}
        if command == "ingest":
            options["classification"] = options.get("classification") or config["ingestion"]["default_classification"]
            return ingest_file(db, config, options)
        if command == "search":
            query = options.pop("query")
            results = search_store(db, config, query, options)
            return {"query_id": stable_query_id(query), "results": results}
        if command == "context":
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
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        sys.stderr.write(f"error: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
