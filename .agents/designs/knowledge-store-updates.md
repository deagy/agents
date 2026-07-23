# Design: Knowledge Store and Orchestrator Improvements

## 1. WAL Checkpoint Strategy
Problem: WAL files grow unbounded under sustained load (CI sessions). No automatic cleanup.
Solution: Add checkpoint(db, mode='TRUNCATE') to database.py. Call it in complete_run() when chunk_count exceeds threshold (default: 1000 chunks). Also add CLI subcommand agents knowledge checkpoint.

## 2. Knowledge Staleness TTL
Problem: Retrieved knowledge is stale indefinitely. No config-level expiration.
Solution: Add optional embedding.max_age_seconds in config.py schema validation. Filter by ingestion time in search_store(). Default to null (no expiry). Validate that it is a positive integer if provided.

## 3. Schema Migration Versioning
Problem: No migration path for future schema changes. CREATE TABLE IF NOT EXISTS silently ignores adds/removes.
Solution: Add __migrations__ table on first open_store(). Check version, run incremental scripts. Start at version 1 (initial).

## 4. Expand glob_to_regex()
Problem: No character class [a-z] or brace a,b support in routing globs.
Solution: Add character class parsing and optional brace expansion pass before main loop.

## 5. Retrieval Rate Limiting Batching
Problem: 34 agents x 20 results = 680 requests per task. No batching or limits.
Solution: Add max_concurrent_retrievals to config. Document serialization in orchestrator skill. Add rate_limit_seconds to embedding config.

## 6. Classification Hierarchy Documentation
Problem: Assumption that classification is hierarchical exists implicitly. Need explicit non-hierarchical table.
Solution: Add explicit matching table to knowledge-use-policy.md.
