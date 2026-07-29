# Changelog

This changelog tracks **consumer-visible** changes to what this suite ships:
new or changed `cadre` CLI subcommands and flags, new/changed provider and
profile artifact fields, and new backlog features landing. It does not
restate this repository's own internal commit history — see `git log` for
that. New adopters should start with the
[adopt-cadre quickstart](docs/adopt-cadre-quickstart.md) instead of this file.

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). This
repository's release convention (see `README.md`'s "Releasing" section) ties
git tags (`vMAJOR.MINOR.PATCH`) to a deliberate, reviewed version bump of
`plugins/cadre/.claude-plugin/plugin.json` /
`plugins/cadre/.codex-plugin/plugin.json`, checked with `cadre version
--check`/`--set`. The latest tagged release at the time of writing is
**v0.11.0**; the entries below have landed since then and have not yet been
bundled into a version-bumped, tagged release. They are grouped under
`[Unreleased]` rather than assigned invented version numbers.

## [Unreleased]

### Added

- **`cadre profile diff`** (idea #4): a new, read-only subcommand that
  compares a consuming project's copy of `provider.json` /
  `profiles/<id>/profile.json` against this checkout's current canonical
  versions and classifies each artifact as `current`, `stale-unmodified`,
  `diverged`, `copy-invalid`, or `provenance-undetermined`, naming every
  differing field in one pass. Matters to consumers because it turns "did our
  copy drift from upstream?" from a manual diff into a scriptable check —
  without ever re-syncing your project or reading/interpreting your
  project's `.agentic-sdlc/` gate-approval state. See
  [agents/RUNBOOK.md](agents/RUNBOOK.md) §16.1 and the
  [quickstart](docs/adopt-cadre-quickstart.md#6-check-for-drift-against-this-suites-canonical-profile-later).

- **Project-local routing overlay** (idea #6): a consuming project can now
  add `.agents/orchestration/routing-overlay.json` to add routes, risk
  rules, and team recipes, or widen an existing rule's matching keywords,
  without forking `orchestration/routing.yaml`. Every safety-relevant field
  on an existing base entry (`human_gate`, `reviewers`, `quality_gates`,
  `primary`, `support`) stays immutable; new entries are additive-only. Run
  `python3 agents/orchestration/src/routing_overlay.py --check` to validate,
  or `--out <path>` to materialize the effective merged configuration. See
  the [quickstart](docs/adopt-cadre-quickstart.md#5-add-a-project-local-routing-overlay-optional).

- **Declarative runner capability manifest** (idea #8): `agents/runner-capabilities.json`
  (validated by `agents/runner-capabilities.schema.json`) is now the single
  source of truth for per-runner (Claude Code, Codex, Cline) capability
  tiers, model-tier mappings, and structural divergence facts, generated
  into the packaged plugin instead of hand-duplicated across three
  generator files. Consumers reading `plugins/cadre/` output get the same
  data, now guaranteed consistent by construction. Validate with
  `python3 agents/orchestration/src/validate_runner_capabilities.py`.

- **`provenance` field on dispatch plans** (idea #7): `cadre select`'s
  emitted plan now optionally carries a `provenance` object — `sha256`
  content hashes of the exact `catalog.yaml`/`routing.yaml` bytes used, and
  best-effort `git_commit_sha`/`git_dirty_paths` for those two files — so a
  reviewer with independent repository access can verify exactly which
  suite-input content produced a given plan. **Additive and non-breaking**:
  `provenance` is optional in `selection.schema.json` (not in the schema's
  `required` array), excluded from the existing `dispatch_fingerprint`
  computation, and absent entirely on any code path that doesn't supply
  `catalog_path`/`routing_path` — plans generated before this field existed,
  and any caller not touching that path, keep validating unchanged. Recording
  provenance is never itself an approval.

- **`cadre profile diff` and the routing overlay build on two already-shipped
  features they depend on**: strict JSON Schema validation of
  `catalog.yaml`/`routing.yaml` (idea #10, `agents/catalog.schema.json`,
  `agents/orchestration/routing.schema.json`, run via
  `python3 agents/orchestration/src/schema_validate.py`) and the routing
  coverage/orphan linter, selection golden-corpus regression harness, and
  full migration of role metadata to `AGENT.md` YAML frontmatter (ideas
  #1-#3). The frontmatter migration (idea #3) is the more consequential
  change for consumers who parse role metadata directly: `agents/catalog.yaml`
  and `orchestration/routing.yaml`'s `knowledge_focus` block are now fully
  *generated* output (`cadre generate-role-metadata`, `--check` for drift
  detection) derived from each role's `AGENT.md` frontmatter — their
  on-disk shape and field values are unchanged (verified as a zero-drift
  migration across all 47 roles), so no consumer-facing action is required,
  but hand-editing either file directly no longer has any effect once it's
  regenerated.

- **pip/pipx-installable `cadre` distribution**: `pyproject.toml` now
  packages the CLI so `pipx install dist/cadre-*.whl` (built locally; not
  yet published to PyPI) puts a `cadre` console script directly on `PATH`
  with no repository checkout required at runtime, as an additional channel
  alongside the existing `./bin/cadre` checkout path (which keeps working
  identically). `cadre generate-plugin`, `cadre generate-authority-aides`,
  and `cadre version` remain checkout-only, since they read and write this
  repository's own generated artifacts; every other subcommand, including
  `cadre select` and `cadre sdlc`, works fully from the installed
  distribution. Optional `[yaml]`/`[mcp]` extras keep a bare `pip install
  cadre` dependency-light.

- **`dispatch_disposition` field on dispatch plans** (fixes #45): every
  `cadre select` plan now carries `dispatch_disposition: {status, reason}`,
  where `status` is `staffed` (a primary and/or reviewer role was selected),
  `advisory-only` (only `agents.support` was populated — e.g. via
  `routing.yaml`'s generic `change_intake` keywords or a default gate review
  agent — with no primary or reviewer matched), or `no-agents-selected`
  (nothing matched; `needs-triage`). Matters to consumers because a
  support-only selection used to be indistinguishable in the plan from a
  fully-staffed one, so an orchestrator had no structured signal before
  silently performing a destructive or persistent-environment action itself
  instead of dispatching or reporting why nothing was dispatched. The
  `run-agent-orchestration` skill now requires checking this field before
  dispatch and reporting its status in every final summary. **Additive and
  non-breaking**: a new required field in `selection.schema.json`, but every
  plan already always populated `agents.primary`/`reviewers`/`support`, so
  the field is deterministically derivable and always present.

### Fixed

- **pip wheel was missing `agents/runner-capabilities.json`**: `cadre
  generate-role-metadata --check` (an installed-must-work subcommand)
  crashed with a raw traceback from a pip/pipx install, because
  `pyproject.toml`'s wheel `force-include` list never vendored this
  manifest (only the sdist's `agents/**` wildcard covered it). Every other
  pip-installed subcommand was unaffected.

### Changed

- **Knowledge-store scope is now enforced, not just conventional, at the
  global-fallback config tier** (idea #9): when a `cadre knowledge` command
  resolves to the shared, cross-project store (no explicit `--config`, no
  project-local `.agents/knowledge-store/config.json` found), `search` and
  `context` now require exactly one of `--source <value>` or the new
  `--all-sources` opt-in flag, and `ingest` now requires an explicit
  `--source` instead of silently defaulting to the generic `"chat-export"`
  identity. **This is a breaking change only for scripts that invoke
  `cadre knowledge search`/`context`/`ingest` against the shared global
  store without `--source`** — they will now fail closed with a clear error
  instead of silently retrieving/ingesting across every project on the
  machine. Project-local stores and an explicit `--config` are unaffected;
  `--source` remains fully optional there. `cadre select`'s own
  knowledge-retrieval path already always supplied an explicit `--source`
  and needed no changes.

## Earlier history

Releases before this changelog existed are not individually itemized here.
See `git log` and each tagged `vMAJOR.MINOR.PATCH` release's GitHub Release
notes (published automatically by `.github/workflows/release.yml` once a
version-bump PR merges) for that history, starting from v0.3.0 (the first tag
following this repository's current versioning scheme).
