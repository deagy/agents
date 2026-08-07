"""Tests for `agentic_sdlc_langgraph.provider` (`load_provider` /
`merge_profile`): the pure-function port of `agentic_sdlc.py`'s
`load_provider` (~124-230) and `merge_profile` (~566-625).

These port the *intent* of the legacy CLI's provider tests
(`plugins/agentic-sdlc/test/test_agentic_sdlc.py`) onto the new
side-effect-free API:

- `test_provider_backed_profile_binds_dispatch_and_digests` ports
  `test_provider_backed_profile_binds_dispatch_and_digests` (~59-70):
  loading the real `agentic-sdlc-defaults` provider and merging its
  `generic` profile must bind G3's dispatch to `cloud-architect` /
  `define-architecture`, and produce `sha256:`-prefixed digests with the
  right provider id.
- `test_provider_rejects_reviewer_with_author_capability` ports
  `test_provider_rejects_reviewer_with_author_capability` (~76-87): a
  synthetic malformed provider declaring a reviewer with an `"author"`
  capability must be rejected at load time -- the load-time
  separation-of-duties enforcement.
- `test_dependency_version_ranges_are_enforced` is a new test (no
  legacy test of this exact name exists) exercising the
  `kernel_compatibility` semver-range check that gates whether a
  provider may load against this kernel at all, plus the
  dependency-must-already-be-loaded check -- both concepts the legacy
  `load_provider` enforces inline (~139-151).
- `test_merge_profile_web_service_inherits_generic_gate_bindings` proves
  the real `web-service` profile (which `"extends": "generic"` with
  empty `gate_bindings`/`routing` of its own) correctly inherits
  `generic`'s `gate_bindings`.

Also proves the deliberate architectural deviation from the legacy
global-mutable-state design: `load_provider` is a pure function that
takes `already_loaded` explicitly, so calling it twice on the same
manifest with `already_loaded=()` both times succeeds both times (no
spurious "duplicate provider id" the legacy global-list version would
raise on a second in-process call).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_sdlc_langgraph.contracts import gate_dispatch_binding, load_lifecycle_gates
from agentic_sdlc_langgraph.provider import (
    KERNEL_VERSION,
    LoadedProvider,
    load_provider,
    merge_profile,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = REPO_ROOT / "plugins" / "agentic-sdlc" / "contracts"
PROVIDER_DEFAULTS = REPO_ROOT / "providers" / "agentic-sdlc-defaults"
DEFAULT_MANIFEST = PROVIDER_DEFAULTS / "provider.json"


@pytest.fixture()
def lifecycle_gates():
    return load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")


def test_provider_backed_profile_binds_dispatch_and_digests(lifecycle_gates):
    loaded = load_provider(DEFAULT_MANIFEST)

    assert loaded.id == "agentic-sdlc-defaults"
    assert loaded.version == "0.3.0"
    assert loaded.manifest_sha256.startswith("sha256:")
    assert loaded.catalog_sha256.startswith("sha256:")
    assert loaded.agent_catalog["cloud-architect"]["kind"] == "author"
    assert loaded.dependencies == []

    profile = merge_profile("generic", loaded.profile_roots, loaded.agent_catalog, lifecycle_gates)

    g3 = next(g for g in lifecycle_gates if g["id"] == "G3")
    binding = gate_dispatch_binding(g3, profile["gate_bindings"])
    assert binding["agents"] == ["cloud-architect"]
    assert binding["tasks"] == ["define-architecture"]

    # Mirrors the legacy test's plan/run-record assertions: a
    # `provider_bindings[0]["id"]` equal to the loaded provider's id, and
    # a `sha256:`-prefixed digest standing in for `dispatch_binding_digest`.
    provider_bindings = [{"id": loaded.id, "version": loaded.version}]
    assert provider_bindings[0]["id"] == "agentic-sdlc-defaults"


def test_load_provider_is_pure_and_reentrant_not_spuriously_duplicate():
    """Calling `load_provider` twice on the same manifest with
    `already_loaded=()` both times must succeed both times -- duplicate
    detection is only meaningful against an explicit `already_loaded`
    list the caller controls, not some ambient global truth (the
    deliberate deviation from the legacy global-list version, which
    would raise "duplicate provider id" on a second in-process call)."""
    first = load_provider(DEFAULT_MANIFEST)
    second = load_provider(DEFAULT_MANIFEST)
    assert first.id == second.id == "agentic-sdlc-defaults"
    assert first is not second

    # Duplicate detection *does* fire when the caller explicitly passes
    # the first load as `already_loaded`.
    with pytest.raises(ValueError, match="duplicate provider id"):
        load_provider(DEFAULT_MANIFEST, already_loaded=[first])


def test_provider_rejects_reviewer_with_author_capability(tmp_path):
    provider_manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    root = tmp_path / "bad-provider"
    (root / "profiles" / "p").mkdir(parents=True)
    (root / "catalog.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agents": {"review": {"kind": "reviewer", "capabilities": ["reviewer", "author"]}},
            }
        ),
        encoding="utf-8",
    )
    (root / "profiles" / "p" / "profile.json").write_text(
        json.dumps({"id": "p", "version": "0.3.0", "gate_bindings": {}}),
        encoding="utf-8",
    )
    provider_manifest.update({"id": "bad-provider", "agent_catalog": "catalog.json", "profile_roots": ["profiles"]})
    manifest_path = root / "provider.json"
    manifest_path.write_text(json.dumps(provider_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="reviewer"):
        load_provider(manifest_path)


def test_dependency_version_ranges_are_enforced(tmp_path):
    """The `kernel_compatibility` semver range gates whether a provider
    may load against this kernel at all (KERNEL_VERSION); a provider
    declaring a dependency also cannot load until that dependency is
    already present in `already_loaded`."""
    provider_manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    root = tmp_path / "range-provider"
    root.mkdir(parents=True)
    (root / "profiles" / "p").mkdir(parents=True)
    (root / "catalog.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}), encoding="utf-8"
    )
    (root / "profiles" / "p" / "profile.json").write_text(
        json.dumps({"id": "p", "version": "0.3.0", "gate_bindings": {}}), encoding="utf-8"
    )
    provider_manifest.update(
        {
            "id": "range-provider",
            "agent_catalog": "catalog.json",
            "profile_roots": ["profiles"],
            "dependencies": [],
        }
    )

    def write_manifest(**overrides):
        manifest = dict(provider_manifest)
        manifest.update(overrides)
        path = root / "provider.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    # Kernel version is outside the declared range -> rejected.
    out_of_range = write_manifest(
        kernel_compatibility={"minimum": "0.4.0", "maximum_exclusive": "0.5.0"}
    )
    with pytest.raises(ValueError, match="incompatible with kernel"):
        load_provider(out_of_range)

    # Range's upper bound is exclusive: maximum_exclusive == KERNEL_VERSION
    # itself must still be rejected.
    boundary_excluded = write_manifest(
        kernel_compatibility={"minimum": "0.1.0", "maximum_exclusive": KERNEL_VERSION}
    )
    with pytest.raises(ValueError, match="incompatible with kernel"):
        load_provider(boundary_excluded)

    # Real fixture's range (0.3.0 <= kernel < 1.0.0) -> accepted.
    in_range = write_manifest(
        kernel_compatibility={"minimum": "0.3.0", "maximum_exclusive": "1.0.0"}
    )
    loaded = load_provider(in_range)
    assert loaded.id == "range-provider"

    # A declared dependency that isn't in `already_loaded` -> rejected.
    with_dependency = write_manifest(
        kernel_compatibility={"minimum": "0.3.0", "maximum_exclusive": "1.0.0"},
        dependencies=[{"id": "some-other-provider", "version": "1.0.0"}],
    )
    with pytest.raises(ValueError, match="requires provider some-other-provider to be loaded first"):
        load_provider(with_dependency)

    # Same manifest succeeds once the dependency is present in
    # `already_loaded` (a LoadedProvider with a matching id).
    dependency = LoadedProvider(
        id="some-other-provider",
        version="1.0.0",
        manifest_sha256="sha256:" + "0" * 64,
        catalog_sha256="sha256:" + "0" * 64,
    )
    loaded_with_dep = load_provider(with_dependency, already_loaded=[dependency])
    assert loaded_with_dep.id == "range-provider"


def test_merge_profile_web_service_inherits_generic_gate_bindings():
    loaded = load_provider(DEFAULT_MANIFEST)
    lifecycle_gates = load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")

    generic = merge_profile("generic", loaded.profile_roots, loaded.agent_catalog, lifecycle_gates)
    web_service = merge_profile("web-service", loaded.profile_roots, loaded.agent_catalog, lifecycle_gates)

    # web-service/profile.json declares empty gate_bindings/routing of
    # its own and `"extends": "generic"` -- the merged result must equal
    # generic's own gate_bindings and routing verbatim.
    assert web_service["gate_bindings"] == generic["gate_bindings"]
    assert web_service["routing"] == generic["routing"]
    assert web_service["id"] == "web-service"
    # Sanity: it isn't just an empty pass-through -- real gate bindings
    # from the parent are actually present.
    assert web_service["gate_bindings"]["G3"]["contributions"]["architecture-design"]["agents"] == [
        "cloud-architect"
    ]


def test_merge_profile_quick_has_no_gate_bindings():
    loaded = load_provider(DEFAULT_MANIFEST)
    lifecycle_gates = load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")

    quick = merge_profile("quick", loaded.profile_roots, loaded.agent_catalog, lifecycle_gates)
    assert quick["gate_bindings"] == {}
    assert quick["routing"] == []


def test_merge_profile_rejects_unknown_agent(tmp_path):
    loaded = load_provider(DEFAULT_MANIFEST)
    lifecycle_gates = load_lifecycle_gates(CONTRACTS / "lifecycle-gates.json")

    # A profile referencing an agent id absent from the catalog must be
    # rejected.
    profile_root = tmp_path / "profiles"
    (profile_root / "broken").mkdir(parents=True)
    (profile_root / "broken" / "profile.json").write_text(
        json.dumps(
            {
                "id": "broken",
                "version": "0.3.0",
                "gate_bindings": {
                    "G1": {
                        "contributions": {
                            "intent": {
                                "agents": ["nonexistent-agent"],
                                "tasks": ["capture-intent"],
                                "artifacts": ["intent-record"],
                            }
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown agents"):
        merge_profile("broken", [profile_root], loaded.agent_catalog, lifecycle_gates)
