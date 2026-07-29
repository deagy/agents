#!/usr/bin/env python3
"""Report drift between a consuming project's copy of this suite's provider
profile (`provider.json` / `profiles/<id>/profile.json`) and this suite's
own current release of those same two artifacts.

This is a **read-only, information-only** report. It never writes to, nor
attempts to re-sync or remediate, anything belonging to a consuming
project, and it never reads or interprets that project's `.agentic-sdlc/`
gate-approval, human-authority, or risk-acceptance state -- only the
project-supplied provider/profile copy itself and (optionally) a
caller-supplied snapshot of the provider/profile content that copy was
originally captured from ("ORIGINAL"). See
`agents/orchestration/runs/cadre-idea-4-profile-diff-2026-07-29/
requirements.md` (PD-FR-13..PD-FR-17) for the boundary rules this module
implements, and `CLAUDE.md`'s "Two-repo boundary" section for why: this
suite supplies release artifacts and comparison logic only, never authority
over another project's lifecycle records.

Three inputs feed the comparison, per artifact (`provider.json` and
`profile.json` are compared independently):

- CURRENT -- this suite's own current release content. Defaults to the
  nearest `provider.json` found by walking up from this file's own
  location (matches both a source checkout's `plugins/cadre/provider.json`
  and a packaged plugin install's top-level `provider.json` without
  needing separate packaging-specific wiring), or may be overridden
  explicitly.
- COPY -- the consuming project's currently-present copy. Always supplied
  explicitly by the caller (`--copy-provider` / `--copy-profile`); this
  module never guesses at, or interprets the shape of, a project's
  `.agentic-sdlc/` layout to find it (PD-FR-17).
- ORIGINAL -- the provider/profile content COPY was captured from,
  identified by whatever version-lock reference the caller's own project
  keeps (format and location are that project's / the separate
  `deagy/agentic-sdlc` kernel's concern, not this module's -- see
  `requirements.md` OD-2/G-2). Supplied explicitly and optionally
  (`--original-provider` / `--original-profile`); if omitted, or the
  supplied file cannot be read/parsed, the artifact is reported as
  `provenance-undetermined` rather than silently defaulting ORIGINAL to
  CURRENT or COPY (PD-FR-3).

Classification (first match wins, per requirements.md PD-FR-5):

    1. copy-invalid            -- COPY fails basic structural validation
    2. provenance-undetermined -- ORIGINAL could not be resolved
    3. current                 -- COPY == CURRENT
    4. stale-unmodified        -- COPY == ORIGINAL, ORIGINAL != CURRENT
    5. diverged                -- COPY != ORIGINAL (regardless of ORIGINAL
                                   vs. CURRENT)

Run:

    cadre profile diff --copy-provider path/to/provider.json \\
                        --copy-profile path/to/profile.json \\
                        [--original-provider PATH] [--original-profile PATH] \\
                        [--profile-id secure-cloud] [--json]

Exit code 0 means every compared artifact is `current`; any other resolved
state (including `copy-invalid` and `provenance-undetermined`) exits 1.
Per PD-FR-16, a `current` result and its exit code are drift information
only -- never treat either as an approval, gate-pass, or compliance signal.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DISCLAIMER = (
    "This report is drift information only. It is not an approval, gate-pass, "
    "or compliance signal, and it does not read or reflect this project's "
    "lifecycle/gate-approval state; see the consuming project's own "
    ".agentic-sdlc/ records and deagy/agentic-sdlc tooling for that."
)

PROVIDER_REQUIRED_FIELDS = ("id", "version")
PROFILE_REQUIRED_FIELDS = ("id", "version", "agents")

@dataclass
class Finding:
    path: str
    kind: str  # "changed" | "added" | "removed"
    old: Any = None
    new: Any = None

    def render(self) -> str:
        if self.kind == "added":
            return f"  - {self.path} : added {self.new!r}"
        if self.kind == "removed":
            return f"  - {self.path} : removed {self.old!r}"
        return f"  - {self.path} : {self.old!r} -> {self.new!r}"


@dataclass
class ArtifactResult:
    artifact: str  # "provider" | "profile"
    state: str
    findings: list[Finding] = field(default_factory=list)
    reason: str | None = None
    original_differs_from_current: bool | None = None
    compared_as: str | None = None  # "current-vs-original" | "original-vs-copy" | None


# ---------------------------------------------------------------------------
# Field-level diffing (PD-FR-10, PD-FR-12)
# ---------------------------------------------------------------------------


def _all_dicts_with_id(items: list[Any]) -> bool:
    return bool(items) and all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in items)


def _all_hashable(items: list[Any]) -> bool:
    try:
        set(items)
    except TypeError:
        return False
    return True


def diff_values(old: Any, new: Any, path: str) -> list[Finding]:
    """Recursive, exhaustive (not first-match) structural diff. Returns one
    Finding per differing leaf/list-membership/dict-key, named by an
    approximate JSON-path-like field path (PD-FR-10's own examples:
    `kernel_compatibility.maximum_exclusive`, `agents[]`,
    `routing[].id="frontend".reviewers[]`).
    """
    findings: list[Finding] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            sub_path = f"{path}.{key}" if path else key
            if key not in old:
                findings.append(Finding(sub_path, "added", new=new[key]))
            elif key not in new:
                findings.append(Finding(sub_path, "removed", old=old[key]))
            else:
                findings.extend(diff_values(old[key], new[key], sub_path))
        return findings
    if isinstance(old, list) and isinstance(new, list):
        return _diff_lists(old, new, path)
    if old != new:
        findings.append(Finding(path, "changed", old=old, new=new))
    return findings


def _diff_lists(old: list[Any], new: list[Any], path: str) -> list[Finding]:
    findings: list[Finding] = []
    if (_all_dicts_with_id(old) or not old) and (_all_dicts_with_id(new) or not new):
        old_by_id = {item["id"]: item for item in old}
        new_by_id = {item["id"]: item for item in new}
        for item_id in sorted(set(old_by_id) | set(new_by_id)):
            item_path = f'{path}[].id="{item_id}"'
            if item_id not in old_by_id:
                findings.append(Finding(item_path, "added", new=new_by_id[item_id]))
            elif item_id not in new_by_id:
                findings.append(Finding(item_path, "removed", old=old_by_id[item_id]))
            else:
                findings.extend(diff_values(old_by_id[item_id], new_by_id[item_id], item_path))
        return findings
    if _all_hashable(old) and _all_hashable(new):
        old_set, new_set = set(old), set(new)
        list_path = f"{path}[]"
        for value in sorted(new_set - old_set, key=repr):
            findings.append(Finding(list_path, "added", new=value))
        for value in sorted(old_set - new_set, key=repr):
            findings.append(Finding(list_path, "removed", old=value))
        return findings
    # Fallback for lists this tool can't key or hash cleanly (e.g. lists
    # containing further nested lists) -- positional comparison.
    for index in range(max(len(old), len(new))):
        item_path = f"{path}[{index}]"
        if index >= len(old):
            findings.append(Finding(item_path, "added", new=new[index]))
        elif index >= len(new):
            findings.append(Finding(item_path, "removed", old=old[index]))
        else:
            findings.extend(diff_values(old[index], new[index], item_path))
    return findings


# ---------------------------------------------------------------------------
# Loading and structural validation (PD-FR-4)
# ---------------------------------------------------------------------------


def load_required_artifact(path: Path, label: str) -> dict[str, Any]:
    """Load an artifact this tool cannot proceed without (CURRENT, or a
    caller-supplied COPY path). Missing/unreadable/invalid content here is a
    CLI usage error (the caller pointed at a bad path), not a classification
    state -- classification states are about the *content* of a
    successfully-read COPY (PD-FR-4), not about whether the caller supplied
    a resolvable path at all.
    """
    if not path.is_file():
        raise SystemExit(f"cadre profile diff: {label} not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(f"cadre profile diff: {label} is not valid JSON ({path}): {error}") from error
    if not isinstance(data, dict):
        raise SystemExit(f"cadre profile diff: {label} must be a JSON object ({path})")
    return data


def load_optional_artifact(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    """Load ORIGINAL. Any failure (no path given, missing file, invalid
    JSON, non-object content) is reported back as an unresolved reason
    string rather than raised -- an unresolved ORIGINAL is an expected,
    reportable condition (PD-FR-3), not a hard CLI error.
    """
    if path is None:
        return None, "no version-lock/original-snapshot reference was supplied"
    if not path.is_file():
        return None, f"the referenced original snapshot could not be located: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return None, f"the referenced original snapshot is not valid JSON ({path}): {error}"
    if not isinstance(data, dict):
        return None, f"the referenced original snapshot is not a JSON object ({path})"
    return data, None


def validate_copy(raw_text: str, required_fields: tuple[str, ...]) -> tuple[dict[str, Any] | None, str | None]:
    """PD-FR-4: COPY validity is checked independently of ORIGINAL/CURRENT
    resolution, and reported as `copy-invalid` rather than `diverged` when it
    fails. Returns (parsed_copy_or_None, invalid_reason_or_None).
    """
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        return None, f"malformed JSON: {error}"
    if not isinstance(data, dict):
        return None, "copy is not a JSON object"
    missing = [name for name in required_fields if name not in data]
    if missing:
        return None, f"missing required field(s): {', '.join(missing)}"
    return data, None


# ---------------------------------------------------------------------------
# Classification (PD-FR-5..PD-FR-9, PD-FR-11)
# ---------------------------------------------------------------------------


def classify_artifact(
    artifact: str,
    copy_text: str,
    current: dict[str, Any],
    original: dict[str, Any] | None,
    original_unresolved_reason: str | None,
    required_fields: tuple[str, ...],
) -> ArtifactResult:
    copy, invalid_reason = validate_copy(copy_text, required_fields)
    if copy is None:
        # State 1 (PD-FR-5): checked first -- a structurally invalid copy
        # cannot be meaningfully field-compared at all (AC-5).
        return ArtifactResult(artifact=artifact, state="copy-invalid", reason=invalid_reason)

    if original is None:
        # State 2 (PD-FR-5, PD-FR-3): without ORIGINAL, stale-unmodified
        # cannot be distinguished from diverged (AC-6).
        return ArtifactResult(artifact=artifact, state="provenance-undetermined", reason=original_unresolved_reason)

    # Equality for classification is deliberately derived from `diff_values`
    # itself (empty findings == equal), not a blanket `==` -- `diff_values`/
    # `_diff_lists` treat certain list fields (e.g. `agents[]`, `routing[]`)
    # as order-insensitive membership/keyed-by-id comparisons per PD-FR-10.
    # Using a separately order-sensitive `==` here could classify a purely
    # reordered (semantically unchanged) list as `diverged`/`stale-unmodified`
    # while the findings list came up empty -- a state with no evidence to
    # act on. Deriving equality from the same function that produces the
    # findings makes that divergence structurally impossible.
    current_vs_copy = diff_values(current, copy, "")
    if not current_vs_copy:
        # State 3 (PD-FR-6): defined purely by COPY-vs-CURRENT equality,
        # regardless of whether COPY also happens to equal ORIGINAL.
        return ArtifactResult(artifact=artifact, state="current")

    original_vs_copy = diff_values(original, copy, "")
    if not original_vs_copy:
        # State 4 (PD-FR-7): COPY == ORIGINAL, and ORIGINAL != CURRENT is
        # implied here (if ORIGINAL == CURRENT, COPY == CURRENT would already
        # have matched above). Findings are framed CURRENT-vs-ORIGINAL --
        # what re-syncing would change (PD-FR-11).
        findings = diff_values(original, current, "")
        return ArtifactResult(
            artifact=artifact, state="stale-unmodified", findings=findings, compared_as="current-vs-original"
        )

    # State 5 (PD-FR-8): COPY differs from both CURRENT and ORIGINAL.
    # Findings are framed ORIGINAL-vs-COPY -- what was locally changed
    # (PD-FR-11) -- plus a separate note on whether ORIGINAL also differs
    # from CURRENT (PD-FR-8's sub-case, PD-FR-11).
    return ArtifactResult(
        artifact=artifact,
        state="diverged",
        findings=original_vs_copy,
        original_differs_from_current=bool(diff_values(original, current, "")),
        compared_as="original-vs-copy",
    )


# ---------------------------------------------------------------------------
# Default CURRENT resolution
# ---------------------------------------------------------------------------


def _is_cadre_provider(path: Path) -> bool:
    """Guard against `find_default_current_paths`'s walk-up landing on a
    coincidentally-named `provider.json` belonging to something other than
    this suite (plausible in a multi-plugin install directory or nested-
    worktree layout) -- confirm the file's own declared `id` before treating
    it as CURRENT, rather than silently accepting whatever is found first.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("id") == "cadre"


def find_default_current_paths(profile_id: str) -> tuple[Path, Path] | None:
    """Locate this suite's own current provider.json/profile.json by walking
    up from this file's own location, so the same default works whether
    this module is running from a source checkout
    (`<repo>/plugins/cadre/provider.json`) or from inside an already-
    packaged plugin install (`<plugin_root>/provider.json`,
    `<plugin_root>/profiles/<id>/profile.json`) without separate
    packaging-specific wiring. Returns None if neither shape is found.

    Each candidate `provider.json` is content-verified (`_is_cadre_provider`)
    before being accepted, so an unrelated same-named file at a closer
    ancestor is skipped rather than silently mistaken for CURRENT.
    """
    for ancestor in Path(__file__).resolve().parents:
        packaged_provider = ancestor / "provider.json"
        if packaged_provider.is_file() and _is_cadre_provider(packaged_provider):
            return packaged_provider, ancestor / "profiles" / profile_id / "profile.json"
        checkout_provider = ancestor / "plugins" / "cadre" / "provider.json"
        if checkout_provider.is_file() and _is_cadre_provider(checkout_provider):
            return checkout_provider, ancestor / "plugins" / "cadre" / "profiles" / profile_id / "profile.json"
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(
    copy_provider_path: Path,
    copy_profile_path: Path,
    current_provider_path: Path,
    current_profile_path: Path,
    original_provider_path: Path | None,
    original_profile_path: Path | None,
) -> dict[str, ArtifactResult]:
    """Compute both artifacts' results. Read-only: every path here is only
    ever opened for reading (PD-FR-13) -- never written, deleted, or
    modified.
    """
    current_provider = load_required_artifact(current_provider_path, "current provider.json")
    current_profile = load_required_artifact(current_profile_path, "current profile.json")

    copy_provider_text = _read_required_text(copy_provider_path, "--copy-provider")
    copy_profile_text = _read_required_text(copy_profile_path, "--copy-profile")

    original_provider, original_provider_reason = load_optional_artifact(original_provider_path)
    original_profile, original_profile_reason = load_optional_artifact(original_profile_path)

    return {
        "provider": classify_artifact(
            "provider",
            copy_provider_text,
            current_provider,
            original_provider,
            original_provider_reason,
            PROVIDER_REQUIRED_FIELDS,
        ),
        "profile": classify_artifact(
            "profile",
            copy_profile_text,
            current_profile,
            original_profile,
            original_profile_reason,
            PROFILE_REQUIRED_FIELDS,
        ),
    }


def _read_required_text(path: Path, flag: str) -> str:
    if not path.is_file():
        raise SystemExit(f"cadre profile diff: {flag} not found: {path}")
    return path.read_text(encoding="utf-8")


def _render_artifact(name: str, result: ArtifactResult) -> list[str]:
    filename = "provider.json" if name == "provider" else "profile.json"
    lines = [f"{filename}: {result.state}"]
    if result.reason:
        lines.append(f"  reason: {result.reason}")
    if result.compared_as == "current-vs-original":
        lines.append("  compared as: CURRENT vs ORIGINAL (what re-syncing this copy would change)")
    elif result.compared_as == "original-vs-copy":
        note = "  compared as: ORIGINAL vs COPY (what was locally changed since capture)"
        if result.original_differs_from_current:
            note += "; this suite's CURRENT release has also changed since ORIGINAL was captured"
        else:
            note += "; ORIGINAL still matches this suite's CURRENT release"
        lines.append(note)
    if result.state == "current":
        lines.append("  (copy matches this suite's current release; no findings)")
    for finding in result.findings:
        lines.append(finding.render())
    return lines


def _to_jsonable(results: dict[str, ArtifactResult]) -> dict[str, Any]:
    payload: dict[str, Any] = {"disclaimer": DISCLAIMER, "artifacts": {}}
    for name, result in results.items():
        payload["artifacts"][name] = {
            "state": result.state,
            "reason": result.reason,
            "compared_as": result.compared_as,
            "original_differs_from_current": result.original_differs_from_current,
            "findings": [
                {"path": finding.path, "kind": finding.kind, "old": finding.old, "new": finding.new}
                for finding in result.findings
            ],
        }
    payload["overall"] = "current" if all(r.state == "current" for r in results.values()) else "drift"
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cadre profile diff",
        description=(
            "Read-only comparison of a consuming project's copied provider/profile "
            "material against this suite's current release. Never writes to the "
            "consuming project and never reads/reports its lifecycle gate state."
        ),
    )
    parser.add_argument("mode", choices=["diff"], help="only 'diff' is currently supported")
    parser.add_argument("--copy-provider", required=True, type=Path, help="path to the project's copied provider.json")
    parser.add_argument("--copy-profile", required=True, type=Path, help="path to the project's copied profile.json")
    parser.add_argument(
        "--original-provider",
        type=Path,
        default=None,
        help="path to the provider.json snapshot COPY was originally captured from, if kept",
    )
    parser.add_argument(
        "--original-profile",
        type=Path,
        default=None,
        help="path to the profile.json snapshot COPY was originally captured from, if kept",
    )
    parser.add_argument(
        "--current-provider",
        type=Path,
        default=None,
        help="override this suite's current provider.json (default: auto-detected)",
    )
    parser.add_argument(
        "--current-profile",
        type=Path,
        default=None,
        help="override this suite's current profile.json (default: auto-detected from --profile-id)",
    )
    parser.add_argument(
        "--profile-id",
        default="secure-cloud",
        help="profile id used to resolve the default --current-profile path (default: secure-cloud)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable JSON instead of text")
    args = parser.parse_args(argv)

    if args.current_provider is not None and args.current_profile is not None:
        current_provider_path, current_profile_path = args.current_provider, args.current_profile
    else:
        defaults = find_default_current_paths(args.profile_id)
        if defaults is None:
            raise SystemExit(
                "cadre profile diff: could not auto-detect this suite's current provider.json/profile.json; "
                "pass --current-provider and --current-profile explicitly"
            )
        current_provider_path = args.current_provider or defaults[0]
        current_profile_path = args.current_profile or defaults[1]

    results = run(
        args.copy_provider,
        args.copy_profile,
        current_provider_path,
        current_profile_path,
        args.original_provider,
        args.original_profile,
    )

    if args.as_json:
        print(json.dumps(_to_jsonable(results), indent=2, sort_keys=True, default=str))
    else:
        print("cadre profile diff report")
        print(DISCLAIMER)
        print()
        for name in ("provider", "profile"):
            for line in _render_artifact(name, results[name]):
                print(line)
            print()
        overall_drift = any(result.state != "current" for result in results.values())
        if overall_drift:
            print("Overall: drift detected in at least one artifact above; no action has been taken or implied.")
        else:
            print("Overall: no drift detected; not an approval or compliance signal.")

    return 0 if all(result.state == "current" for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
