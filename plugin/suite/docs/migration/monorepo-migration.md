<!-- GENERATED FILE: edit the canonical source and regenerate; do not edit this copy. -->

# Monorepo migration and install-UX rework

A record of why this repository absorbed three others, what was decided along
the way, and what is still open. Written after the fact; the phases it
describes are complete.

## Why

Installing this system meant touching three to four GitHub repositories with
no installer and nothing published anywhere — roughly 18–20 discrete manual
actions. The measured cause was duplication, not distribution.

Of `deagy/cadre-lifecycle`'s 500 tracked files, **~340 were generated copies
of `deagy/cadre` content**: `suite/` (175), `agents/` (71), `codex-agents/`
(71), `skills/` (17), plus `agent-catalog.json`, `bin/cadre`, `provider.json`,
`profiles/`, and `extensions/`. `deagy/cadre-profile-secure-cloud` was a
two-file repository whose `profile.json` was **byte-identical** to the copy
already in `cadre`.

An entire coordination layer existed only to keep those copies honest, and
all of it was deletable:

| Machinery | Purpose |
| --- | --- |
| `cadre-ref.txt` | pinned which `cadre` revision the copies came from |
| `drift-check.yml` | weekly: had someone hand-edited a generated file? |
| `regenerate.yml` | on `cadre` tag: regenerate and open a PR |
| `notify-lifecycle.yml` | `repository_dispatch` to trigger the above |
| `apply_regeneration.py` | applied the regenerated diff selectively |
| "regenerate into a scratch dir, `diff -rq`, apply all but README" | the manual procedure |
| three byte-identical `bootstrap_sdlc.py` copies | one per lifecycle plugin |
| `cross-repo-integration` CI job | checked out two repos, `sed`ed hardcoded `/home/deagy/sdk/*` paths, and ran a **committed 0-byte file** — green while testing nothing |

## What changed

| Was | Is |
| --- | --- |
| `deagy/cadre` | `roster/`, `bin/`, `provider/`, `docs/`, `packaging/`, `cadre_cli/` |
| `deagy/agentic-sdlc` | `kernel/`, `engine/`, `docs/kernel/`, `providers/` |
| `deagy/cadre-lifecycle` | `plugin/` |
| `deagy/cadre-profile-secure-cloud` | nothing — already present, byte-identical |

The three upstreams are archived. `deagy/cadre`'s pre-merge history is
preserved on the `archive/pre-monorepo` branch.

## Decisions, including the ones reversed

**Keep the kernel boundary, enforce it differently.** `kernel/` owns G1–G10
gate schemas, run-record validation, and gate-authority semantics; `roster/`
owns roles, routing, and policy. Two repositories cannot import each other's
internals — one tree can, and nothing would have stopped `roster/` from doing
`from agentic_sdlc import validate_repository` and quietly taking over gate
evaluation. `roster/orchestration/test/test_kernel_boundary.py` is the
replacement: it permits exactly two couplings, shelling out to the kernel CLI
and reading `kernel/contracts/*.json` as data. Verified against a planted
violation.

**Generated content is committed — a reversal.** The plan said it would not
be. A GitHub-sourced marketplace serves the repository tree, so an
uncommitted distribution installs a plugin with no roles in it. This is not
the old arrangement returning: source and output now live in one commit and
the `generated-content` CI job regenerates and diffs in the same run, so
drift cannot outlive a pull request.

**No meta-plugin.** Lifecycle governance stays opt-in;
`/plugin install cadre@cadre-team` remains the one command.

**Nothing published to PyPI.** Both names are squatted —
`pip install agentic-sdlc` installs an unrelated third-party project that
looks plausible. Renaming was considered and rejected as a fourth version
line with no distinct audience. Release artifacts with checksums solve the
actual problem; `SECURITY.md` documents the collision.

**Component-prefixed tags.** The monorepo inherited 25 bare `v*` tags
(`v0.1.1`–`v0.16.0`, `v1`–`v7`). An unprefixed `v<version>` scheme collides
from `v0.11.0` on — and would have failed *silently*, matching the release
workflow's already-tagged check and reporting "nothing to do". Tags are now
`plugin-v*` and `kernel-v*`.

## What the merge exposed

Bugs that had shipped, found only because merging forced everything to be
rebuilt and re-run:

- **`bootstrap_sdlc.py` could never have worked from an installed plugin.**
  It resolved `provider.json` via `parents[3]`, but the lifecycle plugins are
  packaged from subdirectories that never contained that file. Every plugin
  user hit "missing provider manifest", at any path.
- **43 of 71 committed `cline-agents` files** were ported from an older
  revision, and five shared-policy paths had no substitution rule — including
  `workspace-isolation.md`, embedded verbatim into every wrapper. Nothing
  re-ported them because the distribution lived in another repository.
- **Declaring `"hooks": "./hooks/hooks.json"` prevents the hook loading**
  (`Duplicate hooks file detected`); the standard path loads automatically.
  This silently disabled the `cadre-lifecycle` v0.11.0 migration notice — the
  entire point of that release — and its own test asserted the condition
  backwards.
- **Four skills had unparseable YAML frontmatter** (a `description`
  containing `": "` ends a plain scalar), so they loaded with no name and no
  description, effectively undiscoverable.
- **`uv sync --locked` was already failing** in `agentic-sdlc` before the
  migration, so its CI had been red on lockfile drift independently.

## Install UX, before and after

| Audience | Was | Is |
| --- | --- | --- |
| Claude Code user | add marketplace at a tag stale in 3 documents, then install | two slash commands, no tag |
| Any runner | 18–20 actions across 3–4 repos | one `curl … \| sh` |
| Enterprise | undocumented | one managed-settings file |
| Repo adopter | clone, symlink, build a wheel, clone the kernel | `cadre` plus one guided command |

The kernel install specifically: from *"clone a repo, have pipx, run a
relative-path script that cannot work from your install location, maybe
restart your shell, re-run"* to one consented `/cadre-install-kernel`.

**Consent was preserved deliberately.** The `SessionStart` hook only detects
and reports; it never installs. A plugin fetching and executing code from the
network before the human has asked for anything is a supply-chain objection,
not a convenience.

## Still open

- `install.ps1` is **untested** — no PowerShell was available. Treat the
  first real Windows run as the test.
- The LangGraph engine is checkout-only by construction: `runtime.py` reads
  the kernel's contracts at a repo-relative path, so an installed copy would
  import and then fail at graph-build time. `release.yml` covers the plugin
  and the kernel only, which is correct — but `engine/pyproject.toml` carries
  a version that implies a release line it does not have.
- The plugin distribution has no SBOM or provenance attestation. It
  publishes no archive to attest — a marketplace installs from the repository
  tree — so deciding what to sign is an open question, not just unfinished
  work. The kernel release carries both.
- `required_approving_review_count` is `0`, so this repository's own central
  invariant — no one approves their own work — is not enforced for its
  releases.

## Related

- [Installing Cadre](../INSTALL.md)
- [Enterprise deployment](../enterprise.md)
- [`plugin/README.md`](https://github.com/deagy/cadre/blob/main/plugin/README.md)
  for what is generated versus hand-authored
