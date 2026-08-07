"""Pure-function provider/profile loading.

Port of `agentic_sdlc.py`'s `load_provider` (~124-230) and `merge_profile`
(~566-625), with one deliberate, required architectural deviation: the
legacy functions mutate module-level global lists (`LOADED_PROVIDERS`,
`PROFILE_SEARCH_PATH`, `EXTENSIONS_SEARCH_PATH`,
`AGENT_CATALOG_SEARCH_PATH`) as a side effect -- harmless for the legacy
CLI (one process per invocation), but wrong for this project's graph
factory, which needs to be reentrant and composable: multiple provider
loads, potentially concurrent, feeding different compiled graphs in the
same process (e.g. a future standalone service handling multiple tasks
at once).

So both functions here are pure: they take whatever "already loaded"
state they need as explicit arguments and return data, never mutating
shared module state. In particular, calling `load_provider` twice on the
same manifest with `already_loaded=()` both times succeeds both times --
duplicate-id detection only ever happens against whatever `already_loaded`
list *the caller* passes in, exactly mirroring what the legacy global-list
version would do only for a *single* process's one-shot accumulation, not
some ambient global truth.

`KERNEL_VERSION` mirrors the legacy script's own `VERSION` constant
(agentic_sdlc.py ~21) -- the "kernel" a provider's `kernel_compatibility`
range is checked against. Keep it equal to that constant by hand; nothing
enforces the two stay in sync automatically. They drifted once already
(`agentic_sdlc.py`'s `VERSION` stayed "0.3.0" through 9 tagged releases
that actually shipped new functionality -- see that constant's own
comment) without this mirror ever being touched, which happened not to
break this module's own tests only because they hardcode a `[0.3.0, 0.4.0)`
range that matched the stale value by coincidence, not because anything
here would have caught real drift.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KERNEL_VERSION = "0.13.0"

_VALID_AGENT_KINDS = {"author", "reviewer", "specialist"}
_VALID_AGENT_CAPABILITIES = {"author", "reviewer", "dispatch"}
_ALLOWED_MANIFEST_KEYS = {
    "schema_version",
    "id",
    "version",
    "kernel_compatibility",
    "agent_catalog",
    "profile_roots",
    "extension_roots",
    "dependencies",
    "dispatch_bindings",
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def fingerprint(value: Any) -> str:
    """Port of `agentic_sdlc.py`'s `fingerprint` (~505-507): a stable,
    key-sorted, whitespace-free JSON sha256 digest of `value`."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def semver_tuple(value: str) -> tuple[int, int, int]:
    """Port of `agentic_sdlc.py`'s `semver_tuple` (~84-88)."""
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", value)
    if not match:
        raise ValueError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_satisfies(version: str, minimum: str, maximum_exclusive: str) -> bool:
    """`minimum <= version < maximum_exclusive`, all compared as semver
    tuples. Port of the inline range check in `load_provider`
    (~139-146), pulled out into its own reusable predicate."""
    return semver_tuple(minimum) <= semver_tuple(version) < semver_tuple(maximum_exclusive)


def provider_resource(root: Path, value: Any, field_name: str, *, directory: bool) -> Path:
    """Port of `agentic_sdlc.py`'s `provider_resource` (~91-101): resolve
    a manifest-relative path and reject anything that escapes the
    manifest's own directory, or that doesn't exist as the expected file
    or directory kind."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"provider {field_name} must be a non-empty relative path")
    candidate = (root / value).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError(f"provider {field_name} escapes its manifest directory")
    if directory and not candidate.is_dir():
        raise ValueError(f"provider {field_name} directory does not exist: {value}")
    if not directory and not candidate.is_file():
        raise ValueError(f"provider {field_name} file does not exist: {value}")
    return candidate


@dataclass(frozen=True)
class LoadedProvider:
    id: str
    version: str
    manifest_sha256: str
    catalog_sha256: str
    dependencies: list[dict[str, Any]] = field(default_factory=list)
    agent_catalog: dict[str, dict[str, Any]] = field(default_factory=dict)
    profile_roots: list[Path] = field(default_factory=list)
    extension_roots: list[Path] = field(default_factory=list)


def _existing_profile_ids(already_loaded: list[LoadedProvider]) -> set[str]:
    return {
        path.name
        for provider in already_loaded
        for root in provider.profile_roots
        if root.is_dir()
        for path in root.iterdir()
        if path.is_dir() and (path / "profile.json").is_file()
    }


def _existing_extension_ids(already_loaded: list[LoadedProvider]) -> set[str]:
    return {
        path.name
        for provider in already_loaded
        for root in provider.extension_roots
        if root.is_dir()
        for path in root.iterdir()
        if path.is_dir() and (path / "extension.json").is_file()
    }


def load_provider(
    manifest_path: str | Path,
    already_loaded: list[LoadedProvider] = (),  # type: ignore[assignment]
) -> LoadedProvider:
    """Pure-function port of `agentic_sdlc.py`'s `load_provider`
    (~124-230). Validates the full provider-manifest pipeline (schema
    version, unknown keys, id format/uniqueness, kernel_compatibility
    semver range, dependency graph, agent catalog shape and
    separation-of-duties enforcement, profile/extension root resolution
    and duplicate-id rejection, per-profile/per-extension shape) and
    returns a `LoadedProvider` -- it never mutates any shared/global
    state. Duplicate-id checks (provider id, profile id, extension id)
    are evaluated only against `already_loaded`, which the caller
    controls explicitly; calling this twice on the same manifest with
    `already_loaded=()` both times succeeds both times.
    """
    already_loaded = list(already_loaded)
    path = Path(manifest_path).resolve()
    manifest = _load_json(path)

    if manifest.get("schema_version") != 1:
        raise ValueError(f"unsupported provider schema in {path}")

    unknown_manifest_keys = set(manifest) - _ALLOWED_MANIFEST_KEYS
    if unknown_manifest_keys:
        raise ValueError(f"provider manifest contains unknown fields: {sorted(unknown_manifest_keys)}")

    provider_id = manifest.get("id")
    provider_version = manifest.get("version")
    if not isinstance(provider_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", provider_id):
        raise ValueError(f"invalid provider id in {path}")

    loaded_ids = {item.id for item in already_loaded}
    if provider_id in loaded_ids:
        raise ValueError(f"duplicate provider id: {provider_id}")

    version = semver_tuple(str(provider_version))
    compatibility = manifest.get("kernel_compatibility")
    if not isinstance(compatibility, dict):
        raise ValueError(f"provider {provider_id} is missing kernel_compatibility")
    minimum = str(compatibility.get("minimum"))
    maximum_exclusive = str(compatibility.get("maximum_exclusive"))
    if not version_satisfies(KERNEL_VERSION, minimum, maximum_exclusive):
        raise ValueError(
            f"provider {provider_id} version {provider_version} is incompatible with kernel "
            f"{KERNEL_VERSION}; install a provider compatible with this kernel"
        )

    for dependency in manifest.get("dependencies", []):
        if not isinstance(dependency, dict) or not isinstance(dependency.get("id"), str):
            raise ValueError(f"provider {provider_id} has malformed dependency metadata")
        if dependency["id"] not in loaded_ids:
            raise ValueError(
                f"provider {provider_id} requires provider {dependency['id']} to be loaded first"
            )

    root = path.parent
    catalog_path = provider_resource(root, manifest.get("agent_catalog"), "agent_catalog", directory=False)
    catalog_data = _load_json(catalog_path)
    if catalog_data.get("schema_version") != 1 or not isinstance(catalog_data.get("agents"), dict):
        raise ValueError(f"provider {provider_id} agent catalog must contain an agents object")

    agents: dict[str, dict[str, Any]] = catalog_data["agents"]
    for agent_id, agent in agents.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(agent_id)) or not isinstance(agent, dict):
            raise ValueError(f"provider {provider_id} has an invalid agent id: {agent_id}")
        if agent.get("kind") not in _VALID_AGENT_KINDS:
            raise ValueError(f"provider {provider_id} agent {agent_id} has unknown kind")
        capabilities = agent.get("capabilities", [])
        if not isinstance(capabilities, list) or set(capabilities) - _VALID_AGENT_CAPABILITIES:
            raise ValueError(f"provider {provider_id} agent {agent_id} has unknown capabilities")
        # Load-time separation-of-duties enforcement: a reviewer-kind
        # agent may never carry any capability other than "reviewer"
        # (e.g. "author") -- this is the invariant the legacy test
        # `test_provider_rejects_reviewer_with_author_capability` pins.
        if agent.get("kind") == "reviewer" and set(capabilities) - {"reviewer"}:
            raise ValueError(f"provider {provider_id} reviewer {agent_id} must remain read-only")

        # Resolve/confine an optional rich-content `definition` path
        # relative to the provider root, mirroring the legacy
        # `load_agent_catalog()`'s merge-time resolution (~684-697), so
        # that by the time this catalog is handed to
        # `resolve_role_prompt`, any `definition` is already an
        # absolute, confirmed-safe path.
        definition = agent.get("definition")
        if isinstance(definition, str) and definition:
            resolved_definition = provider_resource(root, definition, f"agent {agent_id} definition", directory=False)
            agent = dict(agent)
            agent["definition"] = str(resolved_definition)
            agents[agent_id] = agent

    profile_roots = [
        provider_resource(root, item, "profile_roots", directory=True)
        for item in manifest.get("profile_roots", [])
    ]
    extension_roots = [
        provider_resource(root, item, "extension_roots", directory=True)
        for item in manifest.get("extension_roots", [])
    ]
    if not profile_roots:
        raise ValueError(f"provider {provider_id} must define at least one profile root")

    existing_profiles = _existing_profile_ids(already_loaded)
    supplied_profiles = {
        child.name
        for profile_root in profile_roots
        for child in profile_root.iterdir()
        if child.is_dir() and (child / "profile.json").is_file()
    }
    duplicate_profiles = existing_profiles.intersection(supplied_profiles)
    if duplicate_profiles:
        raise ValueError(f"provider {provider_id} duplicates profile ids: {sorted(duplicate_profiles)}")

    existing_extensions = _existing_extension_ids(already_loaded)
    supplied_extensions = {
        child.name
        for extension_root in extension_roots
        for child in extension_root.iterdir()
        if child.is_dir() and (child / "extension.json").is_file()
    }
    duplicate_extensions = existing_extensions.intersection(supplied_extensions)
    if duplicate_extensions:
        raise ValueError(f"provider {provider_id} duplicates extension ids: {sorted(duplicate_extensions)}")

    for profile_root in profile_roots:
        for profile_dir in profile_root.iterdir():
            profile_path = profile_dir / "profile.json"
            if not profile_path.is_file():
                continue
            profile = _load_json(profile_path)
            if (
                profile.get("id") != profile_dir.name
                or not isinstance(profile.get("version"), str)
                or not isinstance(profile.get("gate_bindings"), dict)
            ):
                raise ValueError(f"provider {provider_id} has malformed profile: {profile_path}")

    for extension_root in extension_roots:
        for extension_dir in extension_root.iterdir():
            extension_path = extension_dir / "extension.json"
            if not extension_path.is_file():
                continue
            extension = _load_json(extension_path)
            if (
                extension.get("schema_version") != 1
                or extension.get("id") != extension_dir.name
                or not isinstance(extension.get("version"), str)
            ):
                raise ValueError(f"provider {provider_id} has malformed extension: {extension_path}")

    manifest_digest = hashlib.sha256(path.read_bytes()).hexdigest()

    return LoadedProvider(
        id=provider_id,
        version=".".join(str(part) for part in version),
        manifest_sha256=f"sha256:{manifest_digest}",
        catalog_sha256=fingerprint(catalog_data),
        dependencies=list(manifest.get("dependencies", [])),
        agent_catalog=agents,
        profile_roots=profile_roots,
        extension_roots=extension_roots,
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def merge_profile(
    profile_id: str,
    profile_search_path: list[Path],
    agent_catalog: dict[str, Any],
    all_gates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure-function port of `agentic_sdlc.py`'s `merge_profile`
    (~566-625): resolves `profile_id` against `profile_search_path`,
    follows its `extends` chain (merging `agents`/`routing`/
    `gate_bindings` from parent into child -- the child's own
    `gate_bindings` entries override the parent's *per gate*, not merged
    field-by-field within a gate), and validates that every gate id,
    contribution slot, and agent id the merged result references is
    known, and that every `routing` route's referenced agents are known.

    Takes its search path / agent catalog / gate list as explicit
    arguments instead of reading module globals, so this function has no
    dependency on any prior `load_provider` call's side effects -- it is
    given everything it needs to do its job.
    """
    candidates = [
        root / profile_id / "profile.json"
        for root in profile_search_path
        if (root / profile_id / "profile.json").is_file()
    ]
    if not candidates:
        raise ValueError(f"unknown profile: {profile_id}")
    if len(candidates) > 1:
        raise ValueError(f"duplicate profile: {profile_id}")
    path = candidates[0]
    child = _load_json(path)
    if child.get("id") != profile_id or not isinstance(child.get("version"), str):
        raise ValueError(f"profile {profile_id} has malformed metadata; id and version are required")
    if not isinstance(child.get("gate_bindings"), dict):
        raise ValueError(f"profile {profile_id} must define gate_bindings")

    parent_id = child.get("extends")
    if not parent_id:
        result = dict(child)
    else:
        parent = merge_profile(str(parent_id), profile_search_path, agent_catalog, all_gates)
        result = dict(parent)
        result.update({key: value for key, value in child.items() if key not in {"agents", "routing", "gate_bindings"}})
        result["agents"] = _unique(list(parent.get("agents", [])) + list(child.get("agents", [])))
        result["routing"] = list(parent.get("routing", [])) + list(child.get("routing", []))
        merged_bindings = dict(parent.get("gate_bindings", {}))
        for gate_id, binding in child.get("gate_bindings", {}).items():
            merged_bindings[gate_id] = binding
        result["gate_bindings"] = merged_bindings

    result["id"] = profile_id
    result.setdefault("gate_bindings", {})

    known_gates = {gate["id"] for gate in all_gates}
    unknown_gates = set(result["gate_bindings"]) - known_gates
    if unknown_gates:
        raise ValueError(f"profile {profile_id} references unknown lifecycle gates: {sorted(unknown_gates)}")

    known_slots = {slot for gate in all_gates for slot in gate.get("required_contributions", [])}
    known_agents = set(agent_catalog)
    for binding in result["gate_bindings"].values():
        if not isinstance(binding, dict) or not isinstance(binding.get("contributions"), dict):
            raise ValueError(f"profile {profile_id} has malformed gate contribution binding")
        unknown_slots = set(binding.get("contributions", {})) - known_slots
        if unknown_slots:
            raise ValueError(f"profile {profile_id} references unknown contribution slots: {sorted(unknown_slots)}")
        for contribution in binding.get("contributions", {}).values():
            if not isinstance(contribution, dict) or any(
                not isinstance(contribution.get(field_name), list) for field_name in ("agents", "tasks", "artifacts")
            ):
                raise ValueError(f"profile {profile_id} has malformed contribution metadata")
        unknown_agents = {
            agent
            for contribution in binding.get("contributions", {}).values()
            for agent in contribution.get("agents", [])
        } - known_agents
        if unknown_agents:
            raise ValueError(f"profile {profile_id} references unknown agents: {sorted(unknown_agents)}")

    result["agents"] = _unique(
        list(result.get("agents", []))
        + [
            agent
            for binding in result["gate_bindings"].values()
            for contribution in binding.get("contributions", {}).values()
            for agent in contribution.get("agents", [])
        ]
    )

    for route in result.get("routing", []):
        referenced = set(route.get("agents", [])) | set(route.get("reviewers", [])) | set(route.get("support", []))
        unknown = referenced - known_agents
        if unknown:
            raise ValueError(f"profile {profile_id} route {route.get('id')} references unknown agents: {sorted(unknown)}")

    return result
