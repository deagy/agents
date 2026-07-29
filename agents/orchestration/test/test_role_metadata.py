"""Unit tests for role_metadata.py and generate_role_metadata.py.

Every role's AGENT.md now carries `---`-delimited frontmatter, and
agents/catalog.yaml / agents/orchestration/routing.yaml are purely generated
output derived from it -- never an input for role metadata. The single most
important test here is test_generator_is_identity_on_current_repository: run
the generator against a full copy of the real repository tree and assert
agents/catalog.yaml and agents/orchestration/routing.yaml come back
byte-identical. Everything else uses small synthetic, frontmatter-only
fixtures.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = ROOT.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import generate_role_metadata as grm  # noqa: E402
import role_metadata as rm  # noqa: E402

HEADER_TEMPLATE = "version: 1\nagents:\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _routing_text(knowledge_focus: dict[str, str], extra: dict | None = None) -> str:
    payload = {"version": 1, "ignored_gates": [], "routes": [], "risk_rules": []}
    if extra:
        payload.update(extra)
    payload["knowledge_focus"] = knowledge_focus
    return json.dumps(payload, indent=2) + "\n"


def _catalog_text(entries: dict[str, dict[str, str]]) -> str:
    lines = [HEADER_TEMPLATE]
    for role_id, record in entries.items():
        lines.append(f"  {role_id}:\n")
        for field in grm.CATALOG_FIELD_ORDER:
            lines.append(f"    {field}: {record[field]}\n")
    return "".join(lines)


def _record(definition: str, **overrides: str) -> dict[str, str]:
    """A catalog.yaml-shaped record (used only to build the fixture's
    *expected/rendered* catalog.yaml content, never as generator input).
    """
    record = {
        "definition": definition,
        "phase": "build",
        "capability": "code_author",
        "model": "sonnet",
        "codex_model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
    }
    record.update(overrides)
    return record


def _write_migrated_role(
    agents_root: Path, relative_dir: str, role_id: str, knowledge_focus: str, **overrides: str
) -> str:
    """Write a migrated (frontmatter) `AGENT.md` for `role_id` under
    `agents_root/relative_dir/`. Returns the definition path (relative to
    `agents_root`).
    """
    fields = {
        "id": role_id,
        "phase": "build",
        "capability": "code_author",
        "model": "sonnet",
        "codex_model": "gpt-5.6-terra",
        "reasoning_effort": "medium",
        "knowledge_focus": knowledge_focus,
    }
    fields.update(overrides)
    frontmatter = rm.render_frontmatter(fields)
    _write(agents_root / relative_dir / "AGENT.md", frontmatter + f"\n# {role_id}\n\nMigrated role.\n")
    return f"{relative_dir}/AGENT.md"


def _build_two_role_fixture(root: Path) -> None:
    """role-a and role-b are both migrated (frontmatter) roles; catalog.yaml
    and routing.yaml are written to already match what the generator would
    derive from that frontmatter, so `--check` fixtures start clean.
    """
    agents_root = root / "agents"
    definition_a = _write_migrated_role(agents_root, "domain/role-a", "role-a", "role-a knowledge focus")
    definition_b = _write_migrated_role(agents_root, "domain/role-b", "role-b", "role-b knowledge focus")

    catalog_entries = {"role-a": _record(definition_a), "role-b": _record(definition_b)}
    knowledge_focus = {"role-a": "role-a knowledge focus", "role-b": "role-b knowledge focus"}

    _write(agents_root / "catalog.yaml", _catalog_text(catalog_entries))
    _write(agents_root / "orchestration" / "routing.yaml", _routing_text(knowledge_focus))
    _write(agents_root / "catalog-order.txt", "role-a\nrole-b\n")
    _write(agents_root / "_catalog_header.yaml.tmpl", HEADER_TEMPLATE)


def _paths(root: Path) -> tuple[Path, Path, Path, Path, Path]:
    agents_root = root / "agents"
    return (
        agents_root,
        agents_root / "catalog.yaml",
        agents_root / "orchestration" / "routing.yaml",
        agents_root / "catalog-order.txt",
        agents_root / "_catalog_header.yaml.tmpl",
    )


class ScalarRoundTripTests(unittest.TestCase):
    def test_scalar_round_trip(self) -> None:
        values = [
            "plain value",
            "value: with colon-space",
            "value with trailing # comment marker",
            'value with a "double quote" inside',
            "[leading-bracket looks like flow syntax",
            "trailing space ",
            "",
            "normal-hyphenated-value",
        ]
        for value in values:
            with self.subTest(value=value):
                emitted = rm.emit_scalar(value)
                self.assertEqual(value, rm.read_scalar(emitted))

    def test_plain_values_are_not_quoted(self) -> None:
        self.assertEqual("prior architecture decisions", rm.emit_scalar("prior architecture decisions"))

    def test_values_needing_quoting_use_json(self) -> None:
        self.assertEqual('"a: b"', rm.emit_scalar("a: b"))
        self.assertEqual('""', rm.emit_scalar(""))

    def test_embedded_newline_is_quoted(self) -> None:
        # A bare `\n`/`\r` inside a value must always be quoted -- emitted
        # unquoted, it would split into an extra physical line and violate
        # the flat single-line-per-field frontmatter grammar.
        self.assertEqual(json.dumps("line one\nline two"), rm.emit_scalar("line one\nline two"))
        self.assertEqual(json.dumps("line one\rline two"), rm.emit_scalar("line one\rline two"))


class FrontmatterParsingTests(unittest.TestCase):
    def test_strip_frontmatter_leaves_body_byte_identical(self) -> None:
        body = "# Role Title\n\n## Role\n\nDo the thing. Preserve   spacing and\ttabs.\n"
        frontmatter = rm.render_frontmatter(
            {
                "id": "sample-role",
                "phase": "build",
                "capability": "code_author",
                "model": "sonnet",
                "codex_model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
                "knowledge_focus": "sample knowledge focus",
            }
        )
        text = frontmatter + body
        self.assertEqual(body, rm.strip_frontmatter(text))

    def test_strip_frontmatter_is_a_no_op_on_unmigrated_text(self) -> None:
        text = "# Role\n\nNo frontmatter here.\n"
        self.assertEqual(text, rm.strip_frontmatter(text))

    def test_is_migrated_requires_delimiter_at_byte_zero(self) -> None:
        self.assertTrue(rm.is_migrated("---\nid: x\n---\n"))
        self.assertFalse(rm.is_migrated("\n---\nid: x\n---\n"))
        self.assertFalse(rm.is_migrated("# Role\n---\n"))

    def test_parse_frontmatter_missing_closing_delimiter_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "no matching closing"):
            rm.parse_frontmatter("---\nid: x\n# Role\n")

    def test_render_frontmatter_requires_all_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing field"):
            rm.render_frontmatter({"id": "x"})

    def test_field_with_embedded_newline_round_trips_through_render_and_parse(self) -> None:
        # Exercises the REAL round-trip path (render_frontmatter ->
        # parse_frontmatter), not the bare emit_scalar/read_scalar pair in
        # isolation (see test_scalar_round_trip above, which never caught
        # this): an unquoted embedded newline would split the frontmatter
        # block into an extra physical line that does not match the flat
        # `key: value` grammar, and parse_frontmatter would raise
        # "unrecognized frontmatter line" trying to read the continuation
        # back.
        fields = {
            "id": "sample-role",
            "phase": "build",
            "capability": "code_author",
            "model": "sonnet",
            "codex_model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "knowledge_focus": "line one\nline two\nline three",
        }
        rendered = rm.render_frontmatter(fields)
        parsed_fields, body = rm.parse_frontmatter(rendered + "# Body\n")
        self.assertEqual(fields, parsed_fields)
        self.assertEqual("# Body\n", body)


class OrderFileTests(unittest.TestCase):
    def test_comments_and_blank_lines_are_ignored(self) -> None:
        content = "# header comment\nrole-a\n\n  role-b  # trailing comment\n"
        self.assertEqual(["role-a", "role-b"], rm.parse_order_file(content))

    def test_duplicate_id_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate role id"):
            rm.parse_order_file("role-a\nrole-a\n")

    def test_invalid_id_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid role id"):
            rm.parse_order_file("Role_A\n")


class GeneratorIdentityTests(unittest.TestCase):
    def test_generator_is_identity_on_current_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="role-metadata-identity-") as directory:
            copy_root = Path(directory) / "agents"
            shutil.copytree(REPOSITORY_ROOT / "agents", copy_root)
            catalog_path = copy_root / "catalog.yaml"
            routing_path = copy_root / "orchestration" / "routing.yaml"
            before_catalog = catalog_path.read_bytes()
            before_routing = routing_path.read_bytes()

            rendered = grm.generate(
                agents_root=copy_root,
                catalog_path=catalog_path,
                routing_path=routing_path,
                order_path=copy_root / "catalog-order.txt",
                header_template_path=copy_root / "_catalog_header.yaml.tmpl",
            )

            self.assertEqual(before_catalog, rendered[catalog_path].encode("utf-8"))
            self.assertEqual(before_routing, rendered[routing_path].encode("utf-8"))

    def test_check_passes_on_current_tree(self) -> None:
        generator = ROOT / "src" / "generate_role_metadata.py"
        result = subprocess.run(
            [sys.executable, str(generator), "--check"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("2 role metadata files are current", result.stdout)


class CheckModeFixtureTests(unittest.TestCase):
    def _run_check(self, root: Path) -> subprocess.CompletedProcess[str]:
        agents_root, catalog_path, routing_path, order_path, header_path = _paths(root)
        generator = ROOT / "src" / "generate_role_metadata.py"
        return subprocess.run(
            [
                sys.executable, str(generator), "--check",
                "--agents-root", str(agents_root),
                "--catalog", str(catalog_path),
                "--routing", str(routing_path),
                "--order", str(order_path),
                "--header-template", str(header_path),
            ],
            check=False, capture_output=True, text=True, encoding="utf-8",
        )

    def test_check_passes_on_freshly_built_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            result = self._run_check(root)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_check_fails_on_hand_edited_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            _, catalog_path, _, _, _ = _paths(root)
            # Hand-edit formatting (not a value the generator would itself
            # re-derive differently) so the file on disk no longer matches
            # the generator's canonical rendering: the field value is still
            # "build", but with trailing whitespace the renderer never
            # emits.
            catalog_path.write_text(
                catalog_path.read_text(encoding="utf-8").replace("phase: build\n", "phase: build   \n", 1),
                encoding="utf-8",
            )
            result = self._run_check(root)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("Role metadata derived files are stale", result.stderr)
            self.assertIn("catalog.yaml", result.stderr)

    def test_check_fails_on_hand_edited_knowledge_focus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            _, _, routing_path, _, _ = _paths(root)
            # Hand-edit formatting inside the knowledge_focus block (extra
            # space after the colon) that the surgical splice's canonical
            # `json.dumps` re-rendering never reproduces, so a fresh
            # generate() call comes back different even though the value
            # itself is unchanged.
            routing_path.write_text(
                routing_path.read_text(encoding="utf-8").replace(
                    '"role-a": "role-a knowledge focus"', '"role-a":  "role-a knowledge focus"', 1
                ),
                encoding="utf-8",
            )
            result = self._run_check(root)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("Role metadata derived files are stale", result.stderr)
            self.assertIn("routing.yaml", result.stderr)


class RoleModelBuildTests(unittest.TestCase):
    """`build_role_model` now reads role metadata exclusively from each
    `AGENT.md`'s frontmatter; catalog.yaml/routing.yaml are not read here at
    all (only the tests' own `--check` fixtures still write them, as
    expected *rendered output* for `CheckModeFixtureTests`).
    """

    def test_two_migrated_roles_build_role_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)
            order_ids, roles = grm.build_role_model(agents_root, order_path)
            self.assertEqual(["role-a", "role-b"], order_ids)
            self.assertEqual("domain/role-a/AGENT.md", roles["role-a"]["definition"])
            self.assertEqual("domain/role-b/AGENT.md", roles["role-b"]["definition"])
            self.assertEqual("role-a knowledge focus", roles["role-a"]["knowledge_focus"])
            self.assertEqual("role-b knowledge focus", roles["role-b"]["knowledge_focus"])

            catalog_content = grm.render_catalog(order_ids, roles, HEADER_TEMPLATE)
            self.assertIn("role-b:", catalog_content)
            self.assertIn("gpt-5.6-terra", catalog_content)

    def test_unmigrated_agent_md_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)

            # Overwrite role-b's AGENT.md with plain prose carrying no
            # frontmatter at all -- this must now be a generator error, not
            # a silently-accepted transitional state.
            (agents_root / "domain" / "role-b" / "AGENT.md").write_text(
                "# Role B\n\nNo frontmatter here.\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(grm.RoleMetadataError, "does not carry"):
                grm.build_role_model(agents_root, order_path)

    def test_migrated_role_missing_required_field_fails_closed_with_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)

            # Drop the frontmatter's knowledge_focus field entirely -- there
            # is no other source left to fall back to.
            role_b_path = agents_root / "domain" / "role-b" / "AGENT.md"
            content = role_b_path.read_text(encoding="utf-8")
            content = content.replace("knowledge_focus: role-b knowledge focus\n", "")
            role_b_path.write_text(content, encoding="utf-8")

            with self.assertRaisesRegex(grm.RoleMetadataError, r"role-b.*missing required field.*knowledge_focus"):
                grm.build_role_model(agents_root, order_path)

    def test_order_file_lists_id_with_no_matching_agent_md_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)
            order_path.write_text("role-a\nrole-b\nrole-c\n", encoding="utf-8")

            with self.assertRaisesRegex(grm.RoleMetadataError, "no matching AGENT.md"):
                grm.build_role_model(agents_root, order_path)

    def test_discovered_agent_md_not_in_order_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)
            _write_migrated_role(agents_root, "domain/role-c", "role-c", "role-c knowledge focus")

            with self.assertRaisesRegex(grm.RoleMetadataError, "not listed in"):
                grm.build_role_model(agents_root, order_path)

    def test_duplicate_id_across_two_agent_md_files_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)

            # A second AGENT.md whose frontmatter claims role-b's id.
            _write_migrated_role(
                agents_root, "domain/role-b-duplicate", "role-b", "duplicate role-b knowledge focus"
            )

            with self.assertRaisesRegex(grm.RoleMetadataError, "duplicate role id"):
                grm.build_role_model(agents_root, order_path)


class TierConsistencyTests(unittest.TestCase):
    def test_tier_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _build_two_role_fixture(root)
            agents_root, _catalog_path, _routing_path, order_path, _header_path = _paths(root)
            role_a_path = agents_root / "domain" / "role-a" / "AGENT.md"
            role_a_path.write_text(
                role_a_path.read_text(encoding="utf-8").replace(
                    "model: sonnet\ncodex_model: gpt-5.6-terra",
                    "model: opus\ncodex_model: gpt-5.6-terra",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(grm.RoleMetadataError, "requires codex_model"):
                grm.build_role_model(agents_root, order_path)


class KnowledgeFocusSpliceTests(unittest.TestCase):
    def test_splice_preserves_everything_outside_the_block(self) -> None:
        original = _routing_text(
            {"role-a": "role-a focus", "role-b": "role-b focus"},
            extra={"change_intake": {"keywords": ["implement"], "agents": [], "quality_gates": []}},
        )
        roles = {
            "role-a": {"knowledge_focus": "role-a focus"},
            "role-b": {"knowledge_focus": "role-b focus"},
        }
        spliced = grm.splice_knowledge_focus(original, ["role-a", "role-b"], roles)
        self.assertEqual(original, spliced)

    def test_splice_updates_only_changed_values_and_preserves_order(self) -> None:
        original = _routing_text({"role-a": "old focus", "role-b": "role-b focus"})
        roles = {
            "role-a": {"knowledge_focus": "new focus"},
            "role-b": {"knowledge_focus": "role-b focus"},
        }
        spliced = grm.splice_knowledge_focus(original, ["role-a", "role-b"], roles)
        after = json.loads(spliced)
        self.assertEqual(["role-a", "role-b"], list(after["knowledge_focus"].keys()))
        self.assertEqual("new focus", after["knowledge_focus"]["role-a"])
        before = json.loads(original)
        before["knowledge_focus"] = after["knowledge_focus"]
        self.assertEqual(before, after)

    def test_splice_appends_new_roles_in_order_file_order(self) -> None:
        original = _routing_text({"role-a": "role-a focus"})
        roles = {
            "role-a": {"knowledge_focus": "role-a focus"},
            "role-b": {"knowledge_focus": "role-b focus"},
        }
        spliced = grm.splice_knowledge_focus(original, ["role-a", "role-b"], roles)
        after = json.loads(spliced)
        self.assertEqual(["role-a", "role-b"], list(after["knowledge_focus"].keys()))

    def test_missing_anchor_fails_closed(self) -> None:
        original = json.dumps({"version": 1, "routes": [], "risk_rules": []}, indent=2) + "\n"
        with self.assertRaisesRegex(grm.RoleMetadataError, "exactly one"):
            grm.splice_knowledge_focus(original, ["role-a"], {"role-a": {"knowledge_focus": "x"}})

    def test_duplicate_anchor_fails_closed(self) -> None:
        block = '  "knowledge_focus": {\n    "role-a": "x"\n  }'
        original = "{\n" + block + ",\n" + block.replace("role-a", "role-a-again") + "\n}\n"
        with self.assertRaisesRegex(grm.RoleMetadataError, "exactly one"):
            grm.splice_knowledge_focus(original, ["role-a"], {"role-a": {"knowledge_focus": "x"}})

    def test_spliced_result_passes_load_routing(self) -> None:
        sys.path.insert(0, str(ROOT / "src"))
        from routing import load_routing  # noqa: E402

        original = _routing_text({"role-a": "role-a focus"})
        roles = {"role-a": {"knowledge_focus": "updated focus"}}
        spliced = grm.splice_knowledge_focus(original, ["role-a"], roles)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routing.yaml"
            path.write_text(spliced, encoding="utf-8")
            config = load_routing(path)
        self.assertEqual({"role-a": "updated focus"}, config["knowledge_focus"])


if __name__ == "__main__":
    unittest.main()
