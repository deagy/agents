#!/usr/bin/env python3
"""Tests for tools/port_cline_agents.py.

`port_agents()`/`port_skills()` are what regenerate.yml now runs to keep
`cline-agents/agents/*.md` and `cline-agents/skills/*.md` in sync with the
register-generated `agents/*.md`/`skills/*/SKILL.md` -- previously a static,
one-time hand port. The fail-loud safety net (any unrecognized
`roster/`-relative or `../`-relative reference stops the script rather than
shipping a leaked path) is the single most important property here: these
tests verify it actually trips, not just that the happy path works.

    python3 -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import port_cline_agents as p  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


class ToolAndModelMappingTests(unittest.TestCase):
    def test_tools_map_to_canonical_cline_names_deduped_in_order(self) -> None:
        source_dir_content = (
            "---\n"
            "name: sample-role\n"
            "description: A sample role.\n"
            "tools: Read, Grep, Glob, Bash, Edit, Write\n"
            "model: sonnet\n"
            "effort: medium\n"
            "generated: true\n"
            "canonical_source: roster/engineering/sample-role/AGENT.md\n"
            "---\n"
            "\n"
            "# Role: sample-role\n"
            "\n"
            "# Sample Role\n"
            "\n"
            "## Role\n"
            "\n"
            "Do a sample thing.\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "agents").mkdir()
            (root / "cline-agents" / "agents").mkdir(parents=True)
            (root / "agents" / "sample-role.md").write_text(source_dir_content, encoding="utf-8")

            p.port_agents(root)
            content = (root / "cline-agents" / "agents" / "sample-role.md").read_text(encoding="utf-8")

        self.assertIn("allowedTools: [read_files, search_codebase, run_commands, editor]", content)
        self.assertIn("modelId: anthropic/claude-sonnet-4.6", content)
        self.assertIn("providerId: anthropic", content)
        self.assertIn("convertedFrom: agents/sample-role.md", content)
        self.assertNotIn("effort:", content)
        self.assertNotIn("generated:", content)
        self.assertNotIn("# Role: sample-role", content)

    def test_read_only_tools_map_without_write_or_exec(self) -> None:
        result = [p.TOOL_MAP[t] for t in ["Read", "Grep", "Glob"]]
        deduped = list(dict.fromkeys(result))
        self.assertEqual(deduped, ["read_files", "search_codebase"])

    def test_haiku_and_opus_tiers_map_correctly(self) -> None:
        self.assertEqual(p.MODEL_TIER_MAP["haiku"], "anthropic/claude-haiku-4.6")
        self.assertEqual(p.MODEL_TIER_MAP["opus"], "anthropic/claude-opus-4.6")


class PathSubstitutionTests(unittest.TestCase):
    def _body(self, role: str, extra: str) -> str:
        return f"\n# Role: {role}\n\n# Title\n\n## Role\n\n{extra}\n"

    def test_shared_policy_backtick_reference_is_rewritten(self) -> None:
        body = self._body("some-role", "Follow `../../shared/team-profile.yaml`.")
        converted = p._convert_agent_body("some-role", body)
        self.assertIn("this project's team-profile documentation", converted)
        self.assertNotIn("../../shared/team-profile.yaml", converted)

    def test_shared_policy_header_prefix_is_stripped_but_filename_kept(self) -> None:
        body = self._body("some-role", "# Shared policy: roster/shared/technology-standards.md")
        converted = p._convert_agent_body("some-role", body)
        self.assertIn("# Shared policy: technology-standards.md", converted)

    def test_routing_yaml_boilerplate_across_a_line_break_is_rewritten(self) -> None:
        body = self._body(
            "some-role",
            "noted that roster/orchestration/\n    routing.yaml's own routing rules matter.",
        )
        converted = p._convert_agent_body("some-role", body)
        self.assertIn("this project's routing configuration's own routing rules", converted)


class FailLoudSafetyNetTests(unittest.TestCase):
    def test_unrecognized_roster_relative_reference_raises(self) -> None:
        body = "\n# Role: some-role\n\n# Title\n\n## Role\n\nSee `roster/some/brand-new/file.md` for details.\n"
        converted = p._convert_agent_body("some-role", body)
        with self.assertRaises(SystemExit):
            p._check_no_leaks("some-role", converted)

    def test_unrecognized_dotdot_reference_raises(self) -> None:
        converted = "See `../../some/new/path.md` for details."
        with self.assertRaises(SystemExit):
            p._check_no_leaks("some-role", converted)

    def test_known_substitutions_leave_no_leak(self) -> None:
        body = "\n# Role: some-role\n\n# Title\n\n## Role\n\nFollow `../../shared/team-profile.yaml`.\n"
        converted = p._convert_agent_body("some-role", body)
        p._check_no_leaks("some-role", converted)  # must not raise

    def test_application_engineer_is_exempt_from_the_leak_check(self) -> None:
        p._check_no_leaks("application-engineer", "roster/catalog.yaml is this role's whole subject.")


class HandCasedExceptionTests(unittest.TestCase):
    def test_application_engineer_gets_the_port_note_appended(self) -> None:
        body = "\n# Role: application-engineer\n\n# Title\n\n## Role\n\nOwn this suite's tooling.\n"
        converted = p._convert_agent_body("application-engineer", body)
        self.assertIn("Port note (not part of the original role authority text)", converted)

    def test_debugging_engineer_agent_md_bullet_is_reworded(self) -> None:
        body = (
            "\n# Role: debugging-engineer\n\n# Title\n\n## Role\n\n"
            "- When inspecting agents, verify `AGENT.md` authority, catalog registration, "
            "routing rules, knowledge focus, workflow alignment, selector tests, and runbook "
            "examples.\n"
        )
        converted = p._convert_agent_body("debugging-engineer", body)
        self.assertIn("the agent definition's authority, catalog/registry registration", converted)
        self.assertNotIn("verify `AGENT.md` authority", converted)

    def test_knowledge_store_steward_security_clause_gets_the_added_explanation(self) -> None:
        body = (
            "\n# Role: knowledge-store-steward\n\n# Title\n\n## Role\n\n"
            "resolves to the shared global store by default (`SECURITY.md`), so also verify.\n"
        )
        converted = p._convert_agent_body("knowledge-store-steward", body)
        self.assertIn("exact default-resolution behavior", converted)

    def test_missing_override_text_fails_loudly_rather_than_silently_skipping(self) -> None:
        body = "\n# Role: debugging-engineer\n\n# Title\n\n## Role\n\nNo AGENT.md bullet here at all.\n"
        with self.assertRaises(SystemExit):
            p._convert_agent_body("debugging-engineer", body)


class RealRepoRegressionTests(unittest.TestCase):
    """Runs the actual converter against this checkout's real agents/skills
    and diffs the result against the committed cline-agents/ content -- the
    thing that actually proves the table is complete and correct, not just
    plausible against synthetic fixtures above.
    """

    def test_agents_reproduce_committed_content_exactly(self) -> None:
        # The committed cline-agents/agents/*.md this test compares against
        # already reflects this converter's own output (including the 3
        # gitlab_* autonomy keys it deliberately keeps, unlike the old hand
        # port -- see the commit message / README), so this is a genuine
        # byte-for-byte equality check, not a fuzzy one: any divergence here
        # means either the table regressed or committed content drifted
        # without re-running the converter.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cline-agents" / "agents").mkdir(parents=True)
            import shutil

            shutil.copytree(REPO_ROOT / "agents", root / "agents")

            ported = p.port_agents(root)
            self.assertEqual(len(ported), 71)

            mismatches = []
            for role in ported:
                generated = (root / "cline-agents" / "agents" / f"{role}.md").read_text(encoding="utf-8")
                committed_path = REPO_ROOT / "cline-agents" / "agents" / f"{role}.md"
                if not committed_path.is_file():
                    continue
                committed = committed_path.read_text(encoding="utf-8")
                if generated != committed:
                    mismatches.append(role)

            self.assertEqual(mismatches, [], f"Unexpected divergence from committed content: {mismatches}")

    def test_skills_have_no_remaining_roster_relative_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cline-agents" / "skills").mkdir(parents=True)
            import shutil

            shutil.copytree(REPO_ROOT / "skills", root / "skills")

            ported = p.port_skills(root)
            self.assertEqual(len(ported), 7)

            for name in ported:
                content = (root / "cline-agents" / "skills" / f"{name}.md").read_text(encoding="utf-8")
                for match in p.LEAK_RE.finditer(content):
                    self.assertTrue(
                        any(
                            allowed in match.group(0) or match.group(0) in allowed
                            for allowed in p.SKILL_LEAK_ALLOWLIST
                        ),
                        f"{name}: unexpected leaked reference {match.group(0)!r}",
                    )

    def test_skills_no_longer_reference_the_dead_suite_fallback_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cline-agents" / "skills").mkdir(parents=True)
            import shutil

            shutil.copytree(REPO_ROOT / "skills", root / "skills")
            p.port_skills(root)

            content = (root / "cline-agents" / "skills" / "run-agent-orchestration.md").read_text(encoding="utf-8")
            self.assertNotIn("../../suite/roster/", content)
            self.assertIn("Cline packaging note", content)

    def test_script_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cline-agents" / "agents").mkdir(parents=True)
            (root / "cline-agents" / "skills").mkdir(parents=True)
            import shutil

            shutil.copytree(REPO_ROOT / "agents", root / "agents")
            shutil.copytree(REPO_ROOT / "skills", root / "skills")

            p.port_agents(root)
            p.port_skills(root)
            first_pass = {
                f.name: f.read_text(encoding="utf-8")
                for f in (root / "cline-agents" / "agents").glob("*.md")
            }

            p.port_agents(root)
            second_pass = {
                f.name: f.read_text(encoding="utf-8")
                for f in (root / "cline-agents" / "agents").glob("*.md")
            }
            self.assertEqual(first_pass, second_pass)

    def test_cli_runs_cleanly_against_this_checkout(self) -> None:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "port_cline_agents.py"), "--root", str(REPO_ROOT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ported 71 agent(s) and 7 skill(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
