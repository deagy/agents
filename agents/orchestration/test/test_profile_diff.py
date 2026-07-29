"""Tests for `agents/orchestration/src/profile_diff.py` (`cadre profile
diff`), covering requirements.md's AC-1..AC-9
(`agents/orchestration/runs/cadre-idea-4-profile-diff-2026-07-29/
requirements.md`, INTENT-CADRE-BACKLOG-4 / REQ-CADRE-BACKLOG-4).

Fixture-based, one dedicated case per classification state plus the
multi-field single-pass, read-only, and boundary-safety acceptance
criteria. Uses `tempfile.TemporaryDirectory` fixtures rather than files
committed under `agents/orchestration/test/fixtures/` because most cases
here need small, purpose-built variants of `provider.json`/`profile.json`
content rather than shared static fixtures.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = ROOT.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import profile_diff  # noqa: E402

CURRENT_PROVIDER_PATH = REPOSITORY_ROOT / "plugins" / "cadre" / "provider.json"
CURRENT_PROFILE_PATH = REPOSITORY_ROOT / "plugins" / "cadre" / "profiles" / "secure-cloud" / "profile.json"


def _load_current() -> tuple[dict, dict]:
    provider = json.loads(CURRENT_PROVIDER_PATH.read_text(encoding="utf-8"))
    profile = json.loads(CURRENT_PROFILE_PATH.read_text(encoding="utf-8"))
    return provider, profile


class ProfileDiffFixture:
    """Writes provider.json/profile.json COPY (and optionally ORIGINAL)
    content into a temporary directory and runs `profile_diff.run()` against
    this repository's real current provider/profile artifacts as CURRENT.
    """

    def __init__(self) -> None:
        self.tempdir = TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def close(self) -> None:
        self.tempdir.cleanup()

    def write(self, name: str, content) -> Path:
        path = self.root / name
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(json.dumps(content), encoding="utf-8")
        return path

    def run(self, copy_provider, copy_profile, original_provider=None, original_profile=None):
        copy_provider_path = self.write("copy_provider.json", copy_provider)
        copy_profile_path = self.write("copy_profile.json", copy_profile)
        original_provider_path = (
            self.write("original_provider.json", original_provider) if original_provider is not None else None
        )
        original_profile_path = (
            self.write("original_profile.json", original_profile) if original_profile is not None else None
        )
        return profile_diff.run(
            copy_provider_path,
            copy_profile_path,
            CURRENT_PROVIDER_PATH,
            CURRENT_PROFILE_PATH,
            original_provider_path,
            original_profile_path,
        )


class ProfileDiffClassificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.current_provider, self.current_profile = _load_current()
        self.fixture = ProfileDiffFixture()
        self.addCleanup(self.fixture.close)

    # AC-1
    def test_current_baseline_reports_current_with_zero_findings(self) -> None:
        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=self.current_profile,
            original_provider=self.current_provider,
            original_profile=self.current_profile,
        )
        self.assertEqual("current", results["provider"].state)
        self.assertEqual("current", results["profile"].state)
        self.assertEqual([], results["provider"].findings)
        self.assertEqual([], results["profile"].findings)

    # AC-2
    def test_stale_unmodified_names_changed_fields_current_vs_original(self) -> None:
        original_profile = copy.deepcopy(self.current_profile)
        original_profile["kernel_compatibility_note"] = "unused-in-profile"  # no-op sentinel, ignored below
        del original_profile["kernel_compatibility_note"]
        original_profile["agents"] = [a for a in original_profile["agents"] if a != "technical-writer"]

        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=original_profile,  # COPY == ORIGINAL exactly
            original_provider=self.current_provider,
            original_profile=original_profile,
        )
        profile_result = results["profile"]
        self.assertEqual("stale-unmodified", profile_result.state)
        self.assertEqual("current-vs-original", profile_result.compared_as)
        self.assertTrue(profile_result.findings, "expected at least one field-level finding")
        finding = next(f for f in profile_result.findings if f.path == "agents[]")
        self.assertEqual("added", finding.kind)
        self.assertEqual("technical-writer", finding.new)
        self.assertEqual("current", results["provider"].state)

    # AC-3
    def test_diverged_at_current_version_reports_copy_vs_original_only(self) -> None:
        diverged_profile = copy.deepcopy(self.current_profile)
        for route in diverged_profile["routing"]:
            if route["id"] == "frontend":
                route["reviewers"] = [*route["reviewers"], "security-reviewer"]

        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=diverged_profile,
            original_provider=self.current_provider,
            original_profile=self.current_profile,  # ORIGINAL == CURRENT
        )
        profile_result = results["profile"]
        self.assertEqual("diverged", profile_result.state)
        self.assertEqual("original-vs-copy", profile_result.compared_as)
        self.assertFalse(profile_result.original_differs_from_current)
        finding = next(f for f in profile_result.findings if f.path == 'routing[].id="frontend".reviewers[]')
        self.assertEqual("added", finding.kind)
        self.assertEqual("security-reviewer", finding.new)

    # AC-4
    def test_diverged_and_behind_notes_original_differs_from_current(self) -> None:
        original_profile = copy.deepcopy(self.current_profile)
        original_profile["agents"] = [a for a in original_profile["agents"] if a != "technical-writer"]

        diverged_copy = copy.deepcopy(original_profile)
        for route in diverged_copy["routing"]:
            if route["id"] == "frontend":
                route["reviewers"] = [*route["reviewers"], "security-reviewer"]

        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=diverged_copy,
            original_provider=self.current_provider,
            original_profile=original_profile,
        )
        profile_result = results["profile"]
        self.assertEqual("diverged", profile_result.state)
        self.assertTrue(profile_result.original_differs_from_current)
        # COPY-vs-ORIGINAL findings only surface the locally-made edit, not
        # the suite's own since-superseded change (per PD-FR-11).
        paths = {f.path for f in profile_result.findings}
        self.assertIn('routing[].id="frontend".reviewers[]', paths)
        self.assertNotIn("agents[]", paths)

    # AC-5
    def test_copy_invalid_malformed_json(self) -> None:
        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile="{ not valid json",
            original_provider=self.current_provider,
            original_profile=self.current_profile,
        )
        self.assertEqual("copy-invalid", results["profile"].state)
        self.assertEqual([], results["profile"].findings)
        self.assertIn("malformed JSON", results["profile"].reason or "")

    def test_copy_invalid_missing_required_field(self) -> None:
        broken_profile = copy.deepcopy(self.current_profile)
        del broken_profile["id"]
        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=broken_profile,
            original_provider=self.current_provider,
            original_profile=self.current_profile,
        )
        self.assertEqual("copy-invalid", results["profile"].state)
        self.assertIn("id", results["profile"].reason or "")

    # AC-6
    def test_provenance_undetermined_when_no_original_supplied(self) -> None:
        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=self.current_profile,
        )
        self.assertEqual("provenance-undetermined", results["profile"].state)
        self.assertEqual("provenance-undetermined", results["provider"].state)
        self.assertEqual([], results["profile"].findings)

    def test_provenance_undetermined_does_not_default_to_current_or_copy(self) -> None:
        """A COPY that exactly matches CURRENT must still report
        provenance-undetermined (not silently reported as `current`) when no
        ORIGINAL is resolvable -- PD-FR-5's priority order checks
        provenance-undetermined before current.
        """
        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=self.current_profile,
        )
        self.assertNotEqual("current", results["profile"].state)
        self.assertNotEqual("current", results["provider"].state)

    def test_provenance_undetermined_when_original_file_missing(self) -> None:
        missing_path = self.fixture.root / "does_not_exist.json"
        results = profile_diff.run(
            self.fixture.write("copy_provider.json", self.current_provider),
            self.fixture.write("copy_profile.json", self.current_profile),
            CURRENT_PROVIDER_PATH,
            CURRENT_PROFILE_PATH,
            missing_path,
            missing_path,
        )
        self.assertEqual("provenance-undetermined", results["profile"].state)
        self.assertIn("could not be located", results["profile"].reason or "")

    # AC-7
    def test_multi_field_single_pass_reporting(self) -> None:
        original_profile = copy.deepcopy(self.current_profile)
        diverged_copy = copy.deepcopy(self.current_profile)
        diverged_copy["agents"] = [a for a in diverged_copy["agents"] if a != "technical-writer"]
        diverged_copy["agents"].append("brand-new-role")
        for route in diverged_copy["routing"]:
            if route["id"] == "frontend":
                route["reviewers"] = [*route["reviewers"], "security-reviewer"]
            if route["id"] == "backend":
                route["gates"] = [g for g in route["gates"] if g != "G4"]

        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=diverged_copy,
            original_provider=self.current_provider,
            original_profile=original_profile,
        )
        profile_result = results["profile"]
        self.assertEqual("diverged", profile_result.state)
        paths = {f.path for f in profile_result.findings}
        self.assertIn("agents[]", paths)
        self.assertIn('routing[].id="frontend".reviewers[]', paths)
        self.assertIn('routing[].id="backend".gates[]', paths)
        self.assertGreaterEqual(len(profile_result.findings), 4)

    def test_reordered_list_with_no_semantic_change_classifies_as_current(self) -> None:
        # Regression: classify_artifact's equality check for `current`/
        # `stale-unmodified` is derived from diff_values (order-insensitive
        # for id-keyed/set-like list fields), not a blanket `==`. A purely
        # reordered `agents[]` list must classify as `current` with zero
        # findings, never `diverged` (or `stale-unmodified`) with an empty
        # findings list -- a state with no evidence to act on.
        reordered_profile = copy.deepcopy(self.current_profile)
        reordered_profile["agents"] = list(reversed(reordered_profile["agents"]))
        self.assertNotEqual(
            self.current_profile["agents"], reordered_profile["agents"], "fixture must actually reorder"
        )

        results = self.fixture.run(
            copy_provider=self.current_provider,
            copy_profile=reordered_profile,
            original_provider=self.current_provider,
            original_profile=self.current_profile,
        )
        profile_result = results["profile"]
        self.assertEqual("current", profile_result.state)
        self.assertEqual([], profile_result.findings)

    def test_diff_values_reports_every_difference_not_just_first(self) -> None:
        old = {"a": 1, "b": 2, "c": {"d": 3}}
        new = {"a": 9, "b": 2, "c": {"d": 4}}
        findings = profile_diff.diff_values(old, new, "")
        paths = {f.path for f in findings}
        self.assertEqual({"a", "c.d"}, paths)


class ProfileDiffReadOnlyTests(unittest.TestCase):
    """AC-8: running the tool leaves every input file byte-for-byte
    unchanged, across every classification state.
    """

    def setUp(self) -> None:
        self.current_provider, self.current_profile = _load_current()
        self.fixture = ProfileDiffFixture()
        self.addCleanup(self.fixture.close)

    def _snapshot(self) -> dict[str, bytes]:
        return {str(p): p.read_bytes() for p in self.fixture.root.iterdir()}

    def test_no_mutation_across_all_states(self) -> None:
        broken_profile = copy.deepcopy(self.current_profile)
        del broken_profile["id"]
        diverged_profile = copy.deepcopy(self.current_profile)
        diverged_profile["agents"].append("brand-new-role")

        cases = [
            dict(copy_provider=self.current_provider, copy_profile=self.current_profile),  # provenance-undetermined
            dict(
                copy_provider=self.current_provider,
                copy_profile=self.current_profile,
                original_provider=self.current_provider,
                original_profile=self.current_profile,
            ),  # current
            dict(
                copy_provider=self.current_provider,
                copy_profile=diverged_profile,
                original_provider=self.current_provider,
                original_profile=self.current_profile,
            ),  # diverged
            dict(
                copy_provider=self.current_provider,
                copy_profile=broken_profile,
                original_provider=self.current_provider,
                original_profile=self.current_profile,
            ),  # copy-invalid
        ]

        current_provider_before = CURRENT_PROVIDER_PATH.read_bytes()
        current_profile_before = CURRENT_PROFILE_PATH.read_bytes()

        for case in cases:
            with self.subTest(case=case.get("copy_profile", {}).get("id") if isinstance(case.get("copy_profile"), dict) else None):
                fixture = ProfileDiffFixture()
                try:
                    fixture.run(**case)
                    before = self._file_bytes(fixture.root)
                    fixture.run(**case)
                    after = self._file_bytes(fixture.root)
                    self.assertEqual(before, after, "profile_diff.run() must never mutate its input files")
                finally:
                    fixture.close()

        self.assertEqual(current_provider_before, CURRENT_PROVIDER_PATH.read_bytes())
        self.assertEqual(current_profile_before, CURRENT_PROFILE_PATH.read_bytes())

    @staticmethod
    def _file_bytes(root: Path) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}

    def test_stale_unmodified_state_also_leaves_files_untouched(self) -> None:
        original_profile = copy.deepcopy(self.current_profile)
        original_profile["agents"] = [a for a in original_profile["agents"] if a != "technical-writer"]

        before = None
        fixture = ProfileDiffFixture()
        try:
            fixture.run(
                copy_provider=self.current_provider,
                copy_profile=original_profile,
                original_provider=self.current_provider,
                original_profile=original_profile,
            )
            before = self._file_bytes(fixture.root)
            fixture.run(
                copy_provider=self.current_provider,
                copy_profile=original_profile,
                original_provider=self.current_provider,
                original_profile=original_profile,
            )
            after = self._file_bytes(fixture.root)
            self.assertEqual(before, after)
        finally:
            fixture.close()


class ProfileDiffBoundarySafetyTests(unittest.TestCase):
    """AC-9: the implementation must never read any consuming-project field
    beyond the caller-supplied provider/profile COPY and ORIGINAL, must
    never claim/imply gate-approval or authorization status, and must never
    offer any write/re-sync code path (PD-FR-13..PD-FR-17).
    """

    def test_module_never_opens_a_path_it_was_not_explicitly_given(self) -> None:
        """`run()`'s only filesystem-touching calls are the four resolved
        artifact paths passed in by the caller -- confirmed by source
        inspection of the exact functions `run()` calls, since a code-level
        contract like "never reach into .agentic-sdlc/ on your own" can't be
        fully proven by any single dynamic test.
        """
        source = Path(profile_diff.__file__).read_text(encoding="utf-8")
        # Prose in module/function docstrings legitimately discusses "gate
        # state" and ".agentic-sdlc" to explain the boundary this module
        # must not cross (PD-FR-15) -- what must never appear is *code* that
        # constructs a path under that name (a real filesystem access) or
        # reads a gate-shaped field/key out of a loaded JSON object.
        for forbidden_path_construction in ('/ ".agentic-sdlc"', "/ '.agentic-sdlc'", 'Path(".agentic-sdlc")'):
            self.assertNotIn(forbidden_path_construction, source)
        for forbidden_field_access in ('["gate', '.get("gate', "['gate", ".get('gate"):
            self.assertNotIn(forbidden_field_access, source)

    def test_module_has_no_write_capable_filesystem_calls(self) -> None:
        source = Path(profile_diff.__file__).read_text(encoding="utf-8")
        for forbidden in ("write_text(", "write_bytes(", "os.remove", "shutil.copy", "shutil.move", "unlink("):
            self.assertNotIn(forbidden, source, f"profile_diff.py must never call {forbidden}")

    def test_report_output_never_claims_approval_or_pass_language(self) -> None:
        forbidden_phrases = ("gate cleared", "approved", "compliant", "authorization granted")
        current_provider, current_profile = _load_current()
        fixture = ProfileDiffFixture()
        try:
            results = fixture.run(
                copy_provider=current_provider,
                copy_profile=current_profile,
                original_provider=current_provider,
                original_profile=current_profile,
            )
        finally:
            fixture.close()
        self.assertEqual("current", results["profile"].state)
        rendered = "\n".join(profile_diff._render_artifact("profile", results["profile"]))
        lowered = (rendered + profile_diff.DISCLAIMER).lower()
        for phrase in forbidden_phrases:
            self.assertNotIn(phrase, lowered)
        self.assertNotIn("pass", rendered.lower())
        self.assertNotIn(" ok\n", (rendered + "\n").lower())

    def test_disclaimer_present_in_json_output(self) -> None:
        current_provider, current_profile = _load_current()
        fixture = ProfileDiffFixture()
        try:
            results = fixture.run(
                copy_provider=current_provider,
                copy_profile=current_profile,
                original_provider=current_provider,
                original_profile=current_profile,
            )
        finally:
            fixture.close()
        payload = profile_diff._to_jsonable(results)
        self.assertIn("disclaimer", payload)
        self.assertIn("not an approval", payload["disclaimer"].lower())


class ProfileDiffCliTests(unittest.TestCase):
    def test_current_state_exit_code_zero(self) -> None:
        current_provider, current_profile = _load_current()
        fixture = ProfileDiffFixture()
        self.addCleanup(fixture.close)
        copy_provider_path = fixture.write("copy_provider.json", current_provider)
        copy_profile_path = fixture.write("copy_profile.json", current_profile)
        original_provider_path = fixture.write("original_provider.json", current_provider)
        original_profile_path = fixture.write("original_profile.json", current_profile)

        exit_code = profile_diff.main(
            [
                "diff",
                "--copy-provider",
                str(copy_provider_path),
                "--copy-profile",
                str(copy_profile_path),
                "--original-provider",
                str(original_provider_path),
                "--original-profile",
                str(original_profile_path),
            ]
        )
        self.assertEqual(0, exit_code)

    def test_non_current_state_exit_code_nonzero(self) -> None:
        current_provider, current_profile = _load_current()
        fixture = ProfileDiffFixture()
        self.addCleanup(fixture.close)
        copy_provider_path = fixture.write("copy_provider.json", current_provider)
        copy_profile_path = fixture.write("copy_profile.json", current_profile)

        exit_code = profile_diff.main(
            [
                "diff",
                "--copy-provider",
                str(copy_provider_path),
                "--copy-profile",
                str(copy_profile_path),
            ]
        )
        self.assertEqual(1, exit_code)

    def test_default_current_paths_auto_detected(self) -> None:
        defaults = profile_diff.find_default_current_paths("secure-cloud")
        self.assertIsNotNone(defaults)
        provider_path, profile_path = defaults
        self.assertTrue(provider_path.is_file())
        self.assertTrue(profile_path.is_file())
        self.assertEqual(CURRENT_PROVIDER_PATH.resolve(), provider_path.resolve())
        self.assertEqual(CURRENT_PROFILE_PATH.resolve(), profile_path.resolve())


if __name__ == "__main__":
    unittest.main()
