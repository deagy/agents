#!/usr/bin/env python3
"""Tests for .github/workflows/regenerate.yml's patch-production step.

regenerate.yml hands the `open-pr` job a patch artifact rather than letting
it check out or execute cadre's code (see that workflow's header comment for
why the jobs are split). That makes the patch the sole channel through which
a regeneration reaches a pull request -- anything missing from it is silently
missing from the release, with no failing step anywhere.

A plain `git diff` reports only *tracked* files. When cadre v0.15.0 added a
new module (roster/shared/src/settings.py), the patch therefore contained
every modified file that had started importing it but not the module itself,
and the opened PR shipped a package whose `cadre select`/`cadre config` died
with ModuleNotFoundError. Nothing caught it: the `changed` check one step
earlier uses `git status --porcelain`, which *does* see untracked files, so
the workflow correctly decided there was something to ship and then shipped
a truncated patch. validate.yml does not run automatically on a PR opened
with the default GITHUB_TOKEN either, so CI was silent too.

These tests pin both halves: the workflow text (so the staged form is not
reverted) and the underlying git behavior that makes staging necessary (so a
reader can see *why* without reconstructing the incident).

    python3 -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "regenerate.yml"
PATCH_STEP_NAME = "Save the diff as a patch artifact"


def _patch_step_body() -> str:
    """The `run:` body of regenerate.yml's patch-producing step.

    Text-sliced rather than YAML-parsed on purpose: `tools/` has no
    third-party dependency (see validate.yml, which runs these with a bare
    `python3 -m unittest`), and adding PyYAML solely to read one step would
    be a heavier change than the assertion warrants.
    """
    lines = WORKFLOW_PATH.read_text(encoding="utf-8").splitlines()
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == f"- name: {PATCH_STEP_NAME}"),
        None,
    )
    if start is None:
        raise AssertionError(
            f"regenerate.yml no longer has a step named {PATCH_STEP_NAME!r}; if it was renamed, "
            "update this test rather than deleting it -- the guarantee it pins still matters"
        )
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip().startswith("- name: "):
            break
        body.append(line)
    return "\n".join(body)


class PatchStepStagesNewFilesTests(unittest.TestCase):
    def test_patch_step_stages_before_diffing(self) -> None:
        body = _patch_step_body()
        self.assertIn(
            "git add -A",
            body,
            "the patch step must stage first, or newly added generated files are dropped",
        )
        self.assertIn(
            "git diff --cached",
            body,
            "the patch must be taken from the index (--cached), not the worktree",
        )

    def test_patch_step_does_not_use_a_bare_worktree_diff(self) -> None:
        body = _patch_step_body()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("git diff"):
                continue
            self.assertIn(
                "--cached",
                stripped,
                "a bare `git diff` here silently omits every newly added file "
                f"(offending line: {stripped!r})",
            )


class GitDiffSemanticsTests(unittest.TestCase):
    """Documents the git behavior the fix above exists for.

    Not a test of this repository's own code -- a guard against someone
    'simplifying' the staged form back to a bare `git diff` because the
    reason wasn't obvious.
    """

    def _git(self, repository: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout

    def test_bare_diff_omits_new_files_while_staged_diff_includes_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self._git(repository, "init", "-q", ".")
            self._git(repository, "config", "user.email", "test@example.com")
            self._git(repository, "config", "user.name", "Test")
            (repository / "tracked.txt").write_text("original\n", encoding="utf-8")
            self._git(repository, "add", "-A")
            self._git(repository, "commit", "-qm", "init")

            # Exactly the shape a regeneration produces: an existing file
            # updated to reference a module the same regeneration adds.
            (repository / "tracked.txt").write_text("import newmodule\n", encoding="utf-8")
            (repository / "newmodule.py").write_text("VALUE = 1\n", encoding="utf-8")

            worktree_diff = self._git(repository, "diff", "--binary")
            self.assertIn("tracked.txt", worktree_diff)
            self.assertNotIn(
                "newmodule.py",
                worktree_diff,
                "a bare `git diff` is expected to omit untracked files -- this is the "
                "behavior regenerate.yml's staged form works around",
            )

            self._git(repository, "add", "-A")
            staged_diff = self._git(repository, "diff", "--cached", "--binary")
            self.assertIn("tracked.txt", staged_diff)
            self.assertIn("newmodule.py", staged_diff)

    def test_staged_diff_also_captures_deletions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            self._git(repository, "init", "-q", ".")
            self._git(repository, "config", "user.email", "test@example.com")
            self._git(repository, "config", "user.name", "Test")
            (repository / "removed.txt").write_text("gone soon\n", encoding="utf-8")
            self._git(repository, "add", "-A")
            self._git(repository, "commit", "-qm", "init")

            (repository / "removed.txt").unlink()
            self._git(repository, "add", "-A")
            staged_diff = self._git(repository, "diff", "--cached", "--binary")
            self.assertIn("removed.txt", staged_diff)
            self.assertIn("+++ /dev/null", staged_diff)


if __name__ == "__main__":
    unittest.main()
