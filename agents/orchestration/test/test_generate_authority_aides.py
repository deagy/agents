"""Unit tests for the authority-aide AGENT.md generator.

Exercises load_aides()'s error branches and main()'s plain-generate (write)
path directly, since agents/orchestration/test/test_repository_health.py's
drift-guard test only ever runs --check against the already-correct,
committed aides.yaml/AGENT.md pair and so never touches this code.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import generate_authority_aides as gaa  # noqa: E402
from routing import parse_keyed_entries  # noqa: E402


class ParseKeyedEntriesTests(unittest.TestCase):
    """The shared primitive behind both catalog.yaml's and aides.yaml's
    parsers (load_aides() above uses it via parse_keyed_entries)."""

    def test_duplicate_id_raises(self) -> None:
        content = "  role-a:\n    field: one\n  role-a:\n    field: two\n"
        with self.assertRaisesRegex(ValueError, "duplicate id 'role-a'"):
            parse_keyed_entries(content, ("field",))

    def test_unlisted_fields_are_ignored(self) -> None:
        content = "  role-a:\n    field: kept\n    other: dropped\n"
        self.assertEqual({"role-a": {"field": "kept"}}, parse_keyed_entries(content, ("field",)))


class LoadAidesTests(unittest.TestCase):
    def _write(self, directory: Path, content: str) -> Path:
        path = directory / "aides.yaml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_field_order_within_an_entry_does_not_matter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n"
                "  engineering-lead-aide:\n"
                "    gates: [2, 6]\n"
                "    title: Engineering Lead\n",
            )
            aides = gaa.load_aides(path)
            self.assertEqual(
                [{"id": "engineering-lead-aide", "title": "Engineering Lead", "gates": [2, 6]}], aides
            )

    def test_inline_comment_on_a_field_is_stripped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n"
                "  engineering-lead-aide:\n"
                "    title: Engineering Lead  # primary approver\n"
                "    gates: [2, 6]\n",
            )
            aides = gaa.load_aides(path)
            self.assertEqual("Engineering Lead", aides[0]["title"])

    def test_hash_with_no_preceding_whitespace_is_not_treated_as_a_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n  engineering-lead-aide:\n    title: C# Lead\n    gates: [2, 6]\n",
            )
            aides = gaa.load_aides(path)
            self.assertEqual("C# Lead", aides[0]["title"])

    def test_duplicate_id_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n"
                "  engineering-lead-aide:\n"
                "    title: Engineering Lead\n"
                "    gates: [2, 6]\n"
                "  engineering-lead-aide:\n"
                "    title: Duplicate\n"
                "    gates: [9]\n",
            )
            with self.assertRaisesRegex(ValueError, "duplicate id"):
                gaa.load_aides(path)

    def test_missing_field_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory), "aides:\n  engineering-lead-aide:\n    gates: [2, 6]\n"
            )
            with self.assertRaisesRegex(ValueError, "missing required field"):
                gaa.load_aides(path)

    def test_empty_gates_list_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n  engineering-lead-aide:\n    title: Engineering Lead\n    gates: []\n",
            )
            with self.assertRaisesRegex(ValueError, "empty gates list"):
                gaa.load_aides(path)

    def test_block_style_gates_list_raises_a_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n"
                "  engineering-lead-aide:\n"
                "    title: Engineering Lead\n"
                "    gates:\n"
                "      - 2\n"
                "      - 6\n",
            )
            with self.assertRaisesRegex(ValueError, "flow-style list"):
                gaa.load_aides(path)

    def test_non_integer_gate_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n  engineering-lead-aide:\n    title: Engineering Lead\n    gates: [two]\n",
            )
            with self.assertRaisesRegex(ValueError, "non-integer gate"):
                gaa.load_aides(path)

    def test_duplicate_gate_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n  engineering-lead-aide:\n    title: Engineering Lead\n    gates: [2, 2]\n",
            )
            with self.assertRaisesRegex(ValueError, "duplicate gate"):
                gaa.load_aides(path)

    def test_non_ascii_title_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write(
                Path(directory),
                "aides:\n  ops-lead-aide:\n    title: Ops Léad\n    gates: [3]\n",
            )
            aides = gaa.load_aides(path)
            self.assertEqual("Ops Léad", aides[0]["title"])
            rendered = gaa.render("# {title}\n\n{gate_phrase}\n{gate_list}\n", aides[0])
            self.assertIn("Ops Léad", rendered)


class GatePhraseAndListTests(unittest.TestCase):
    def test_gate_phrase_single_gate(self) -> None:
        self.assertEqual("gate G5", gaa.gate_phrase([5]))

    def test_gate_phrase_two_gates(self) -> None:
        self.assertEqual("gates G2 and G6", gaa.gate_phrase([2, 6]))

    def test_gate_phrase_three_or_more_gates_uses_oxford_comma(self) -> None:
        self.assertEqual("gates G1, G2, and G6", gaa.gate_phrase([1, 2, 6]))

    def test_gate_list_single_gate(self) -> None:
        self.assertEqual("G5", gaa.gate_list([5]))

    def test_gate_list_two_gates(self) -> None:
        self.assertEqual("G2, G6", gaa.gate_list([2, 6]))

    def test_gate_list_three_or_more_gates(self) -> None:
        self.assertEqual("G1, G2, G6", gaa.gate_list([1, 2, 6]))


class ValidateGatesAgainstKernelContractTests(unittest.TestCase):
    _AIDES = [
        {"id": "engineering-lead-aide", "title": "Engineering Lead", "gates": [2, 6]},
        {"id": "release-authority-aide", "title": "Release Authority", "gates": [9]},
    ]

    def test_standalone_mode_skips_validation(self) -> None:
        with mock.patch.object(gaa, "try_lifecycle_contract", return_value=None):
            gaa.validate_gates_against_kernel_contract(self._AIDES)  # must not raise

    def test_passes_when_every_gate_is_in_the_live_contract(self) -> None:
        contract = {"gates": [{"id": f"G{n}"} for n in range(1, 11)]}
        with mock.patch.object(gaa, "try_lifecycle_contract", return_value=contract):
            gaa.validate_gates_against_kernel_contract(self._AIDES)  # must not raise

    def test_raises_when_an_aide_references_a_gate_missing_from_the_live_contract(self) -> None:
        contract = {"gates": [{"id": "G1"}, {"id": "G2"}]}
        with mock.patch.object(gaa, "try_lifecycle_contract", return_value=contract):
            with self.assertRaisesRegex(ValueError, r"engineering-lead-aide.*G6"):
                gaa.validate_gates_against_kernel_contract(self._AIDES)


class RenderTests(unittest.TestCase):
    def test_unbound_placeholder_raises_attributed_value_error(self) -> None:
        aide = {"id": "engineering-lead-aide", "title": "Engineering Lead", "gates": [2, 6]}
        with self.assertRaisesRegex(
            ValueError, r"failed to render aide 'engineering-lead-aide'"
        ):
            gaa.render("# {title}\n\n{unknown_field}\n", aide)


class MainWritePathTests(unittest.TestCase):
    def _isolated_authority_root(self, directory: Path) -> None:
        (directory / "aides.yaml").write_text(
            "aides:\n"
            "  engineering-lead-aide:\n"
            "    title: Engineering Lead\n"
            "    gates: [2, 6]\n",
            encoding="utf-8",
        )
        (directory / "_template.md.tmpl").write_text("# {title}\n\ngates: {gate_list}\n", encoding="utf-8")

    def test_plain_generate_creates_missing_role_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._isolated_authority_root(root)
            with mock.patch.object(gaa, "AUTHORITY_ROOT", root), mock.patch.object(
                gaa, "DATA_PATH", root / "aides.yaml"
            ), mock.patch.object(gaa, "TEMPLATE_PATH", root / "_template.md.tmpl"), mock.patch.object(
                sys, "argv", ["generate_authority_aides.py"]
            ):
                self.assertEqual(0, gaa.main())
            generated = root / "engineering-lead-aide" / "AGENT.md"
            self.assertTrue(generated.is_file())
            self.assertIn(gaa.GENERATED_MARKER, generated.read_text(encoding="utf-8"))

    def test_plain_generate_removes_orphaned_role_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._isolated_authority_root(root)
            orphan = root / "retired-role-aide" / "AGENT.md"
            orphan.parent.mkdir(parents=True)
            orphan.write_text("stale", encoding="utf-8")
            with mock.patch.object(gaa, "AUTHORITY_ROOT", root), mock.patch.object(
                gaa, "DATA_PATH", root / "aides.yaml"
            ), mock.patch.object(gaa, "TEMPLATE_PATH", root / "_template.md.tmpl"), mock.patch.object(
                sys, "argv", ["generate_authority_aides.py"]
            ):
                self.assertEqual(0, gaa.main())
            self.assertFalse(orphan.parent.exists())

    def test_plain_generate_does_not_crash_when_orphan_directory_has_extra_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._isolated_authority_root(root)
            orphan = root / "retired-role-aide" / "AGENT.md"
            orphan.parent.mkdir(parents=True)
            orphan.write_text("stale", encoding="utf-8")
            (orphan.parent / "extra.txt").write_text("leftover", encoding="utf-8")
            with mock.patch.object(gaa, "AUTHORITY_ROOT", root), mock.patch.object(
                gaa, "DATA_PATH", root / "aides.yaml"
            ), mock.patch.object(gaa, "TEMPLATE_PATH", root / "_template.md.tmpl"), mock.patch.object(
                sys, "argv", ["generate_authority_aides.py"]
            ):
                self.assertEqual(0, gaa.main())
            self.assertTrue(orphan.parent.exists(), "non-empty orphan directory should be left in place")
            self.assertTrue((orphan.parent / "extra.txt").is_file())
            self.assertFalse(orphan.exists(), "the stale AGENT.md itself should still be removed")

    def test_check_reports_orphaned_role_directory_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._isolated_authority_root(root)
            orphan = root / "retired-role-aide" / "AGENT.md"
            orphan.parent.mkdir(parents=True)
            orphan.write_text("stale", encoding="utf-8")
            with mock.patch.object(gaa, "AUTHORITY_ROOT", root), mock.patch.object(
                gaa, "DATA_PATH", root / "aides.yaml"
            ), mock.patch.object(gaa, "TEMPLATE_PATH", root / "_template.md.tmpl"), mock.patch.object(
                gaa, "REPOSITORY_ROOT", root
            ), mock.patch.object(sys, "argv", ["generate_authority_aides.py", "--check"]):
                self.assertEqual(1, gaa.main())
            self.assertTrue(orphan.is_file(), "check mode must not modify the tree")


if __name__ == "__main__":
    unittest.main()
