#!/usr/bin/env python3
"""Guard against drift between cadre-lifecycle-core's shared assets and the
byte-for-byte-except-naming copies bundled into cadre-lifecycle-github and
cadre-lifecycle-gitlab (see plugins/lifecycle-{github,gitlab}/tools/ and the
lifecycle-onboarding-*/lifecycle-review-generic-*/brief-pending-gates-*
skills under plugins/lifecycle-{github,gitlab}/skills/).

Those three plugins deliberately duplicate this content instead of sharing a
single source, so each forge plugin is self-sufficient without also
installing cadre-lifecycle-core (see plugins/lifecycle-github/.claude-plugin/
plugin.json and plugins/lifecycle-gitlab/.claude-plugin/plugin.json). Nothing
enforces that the duplicates stay in sync except this test: a future edit to
plugins/lifecycle/tools/bootstrap_sdlc.py (or its test, or one of the three
duplicated skills) that isn't mirrored into both forge plugins would
otherwise only be caught by a human noticing, if ever.

If this test fails, the fix is to re-sync the drifted copy, not to remove the
duplication: the duplication itself is the accepted architectural tradeoff
that buys per-forge self-sufficiency (see AGENTS.md's plugin-split
rationale and CHANGELOG.md's v0.7.0 entry, which introduced it deliberately
by removing cadre-lifecycle-github/-gitlab's prior dependency on
cadre-lifecycle-core).

    python3 -m unittest discover -s tools -p "test_*.py"
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

FORGES = ("github", "gitlab")

# tools/bootstrap_sdlc.py's docstring names its own path in four example
# invocation lines; that is the only line expected to differ between the
# core, github, and gitlab copies.
BOOTSTRAP_PATH_PATTERN = re.compile(
    r"plugins/lifecycle(?:-github|-gitlab)?/tools/bootstrap_sdlc\.py"
)

# test_bootstrap_sdlc.py's docstring names its own module path (in the
# opening summary line) and the `unittest discover -s` path in its trailing
# usage line; those are the only expected differences.
TEST_BOOTSTRAP_PATH_PATTERN = re.compile(
    r"plugins/lifecycle(?:-github|-gitlab)?/tools"
)

# The three duplicated skills cross-reference each other and themselves by
# name (e.g. "lifecycle-onboarding's Step 4"); the bundled copies rename
# those references to their own suffixed sibling skill. Normalizing them
# back to the core plugin's bare names makes the bodies comparable. This
# pattern intentionally only matches the CALLER-SUPPLIED forge's own suffix
# (see _normalize_skill_name's `forge` parameter) -- a reference bearing the
# *other* forge's suffix (e.g. a "-gitlab" name inside a github skill,
# likely a copy-paste mistake) must NOT normalize away, so it still shows up
# as a real diff against the core body instead of silently comparing equal.
def _skill_name_pattern(forge: str) -> re.Pattern[str]:
    return re.compile(
        rf"lifecycle-onboarding(?:-{forge})?"
        rf"|lifecycle-review-generic(?:-{forge})?"
        rf"|brief-pending-gates(?:-{forge})?"
    )


def _normalize_skill_name(match: re.Match) -> str:
    text = match.group(0)
    if text.startswith("lifecycle-onboarding"):
        return "lifecycle-onboarding"
    if text.startswith("lifecycle-review-generic"):
        return "lifecycle-review"
    return "brief-pending-gates"


# The duplicated skills also cite the forge-specific gate-tracking skill name
# and its reason-code vocabulary as a generic, cross-forge example (e.g.
# "translating the same reason-code vocabulary `gitlab-gate-tracking` uses
# later"). The core copy happens to spell that example using GitLab's own
# terms verbatim, so the gitlab copy needs no rewrite there, but the github
# copy must translate each term to its own equivalent. This mapping is
# intentionally one-directional and only ever applied for forge="github" --
# it maps the github-side term back to the core/gitlab-side term so the
# *translated* github copy compares equal to core.
#
# That equality check on its own is NOT sufficient to prove translation
# happened: a github copy that left the raw GitLab-flavored tokens
# untranslated would ALSO compare equal to core (core's text already
# spells them that way), so drift would silently pass. GITLAB_LEAK_TERMS
# below plus test_github_copies_translate_gate_tracking_terms is the
# actual enforcement -- it asserts none of the raw GitLab-only tokens
# appear literally in a github copy.
GITHUB_TO_CORE_TERMS = {
    "create-github-gate-issues": "gitlab-gate-tracking",
    "no-github-binding": "no-gitlab-binding",
    "github-user-unresolved": "gitlab-user-unresolved",
    "GitLab equivalent": "GitHub equivalent",
}
GITHUB_TERM_PATTERN = re.compile("|".join(re.escape(k) for k in GITHUB_TO_CORE_TERMS))

# core's "Known limitation" paragraph (GitLab-flavored) claims a
# gitlab-user-ambiguous case exists; GitHub genuinely has no equivalent
# (its login lookup is exact-match -- see create-github-gate-issues's own
# Step 5), so the github copy legitimately drops that clause instead of
# translating it term-for-term. Normalize the github copy's shorter clause
# back to core's for comparison purposes; a gitlab copy is never subject to
# this substitution, so it still must literally retain core's own clause.
GITHUB_AMBIGUOUS_CLAUSE = (
    "account) at that point even though this preflight looked fine — unlike\n"
    "GitLab, GitHub's lookup is exact-match, so there is no separate\n"
    "ambiguous-match case here. Tell the human this explicitly rather\n"
    "than implying the binding has been fully verified."
)
CORE_AMBIGUOUS_CLAUSE = (
    "account) or `gitlab-user-ambiguous` (more than one match) at that point even\n"
    "though this preflight looked fine. Tell the human this explicitly rather\n"
    "than implying the binding has been fully verified."
)

# The subset of GITHUB_TO_CORE_TERMS values that are genuinely GitLab-only
# identifiers (skill name, reason codes) rather than reversed prose swaps
# like "GitHub equivalent"/"GitLab equivalent" -- these must never appear
# literally in a github copy.
GITLAB_LEAK_TERMS = (
    "gitlab-gate-tracking",
    "no-gitlab-binding",
    "gitlab-user-unresolved",
    "gitlab-user-ambiguous",
)


# The three bundled skills each carry a callout explaining the duplication
# itself -- necessarily forge-copy-only, since it references *this*
# repository's own AGENTS.md plugin-split rationale, a cadre-lifecycle-
# specific concept the register (source of the core copy) has no notion of.
# The core copy is entirely register-generated (plugins/lifecycle/skills/ is
# a GENERATED_NESTED_PATHS entry there), so this note can never live there
# without a future regeneration silently deleting it again -- confirmed by
# exactly that happening once already (deagy/cadre-lifecycle, drift-check
# investigation). Normalized away here, not treated as unexpected drift.
DUPLICATION_NOTE = (
    "> Duplication note: this skill's body is intentionally duplicated across "
    "the core plugin and both forge plugins so each plugin is self-sufficient "
    "and needs no dependency on the others (see AGENTS.md's plugin-split "
    "rationale). Frontmatter `name`/`description` and forge-specific "
    "cross-references intentionally differ per copy; the body must otherwise "
    "stay in sync -- `tools/test_plugin_duplication_health.py` enforces it.\n\n"
)


def _normalize_forge_terms(forge: str, text: str) -> str:
    if forge != "github":
        return text
    text = GITHUB_TERM_PATTERN.sub(lambda m: GITHUB_TO_CORE_TERMS[m.group(0)], text)
    return text.replace(GITHUB_AMBIGUOUS_CLAUSE, CORE_AMBIGUOUS_CLAUSE)


def _skill_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} does not start with a --- frontmatter delimiter")
    end = text.index("\n---\n", 4)
    return text[end + len("\n---\n") :]


class BootstrapScriptDuplicationTests(unittest.TestCase):
    """plugins/lifecycle*/tools/bootstrap_sdlc.py must stay identical."""

    def _paths(self) -> dict[str, Path]:
        return {
            "core": REPO_ROOT / "plugins/lifecycle/tools/bootstrap_sdlc.py",
            "github": REPO_ROOT / "plugins/lifecycle-github/tools/bootstrap_sdlc.py",
            "gitlab": REPO_ROOT / "plugins/lifecycle-gitlab/tools/bootstrap_sdlc.py",
        }

    def test_all_copies_exist(self) -> None:
        for name, path in self._paths().items():
            self.assertTrue(path.is_file(), f"{name} copy missing at {path}")

    def test_copies_are_identical_except_the_docstring_example_paths(self) -> None:
        paths = self._paths()
        normalized = {
            name: BOOTSTRAP_PATH_PATTERN.sub("PLUGIN_TOOLS_PATH", path.read_text(encoding="utf-8"))
            for name, path in paths.items()
        }
        core = normalized["core"]
        for name in ("github", "gitlab"):
            self.assertEqual(
                core,
                normalized[name],
                f"plugins/lifecycle-{name}/tools/bootstrap_sdlc.py has drifted from "
                "plugins/lifecycle/tools/bootstrap_sdlc.py beyond the docstring's "
                "example invocation paths",
            )

    def test_each_copy_actually_names_its_own_path(self) -> None:
        # Guard against the normalization above silently passing if a copy's
        # docstring was never updated at all (e.g. still says
        # plugins/lifecycle/tools/... verbatim) -- that would also normalize
        # away to the same placeholder and falsely look "in sync".
        for name in ("github", "gitlab"):
            path = self._paths()[name]
            text = path.read_text(encoding="utf-8")
            self.assertIn(f"plugins/lifecycle-{name}/tools/bootstrap_sdlc.py", text)


class TestBootstrapScriptDuplicationTests(unittest.TestCase):
    """plugins/lifecycle*/tools/test_bootstrap_sdlc.py must stay identical."""

    def _paths(self) -> dict[str, Path]:
        return {
            "core": REPO_ROOT / "plugins/lifecycle/tools/test_bootstrap_sdlc.py",
            "github": REPO_ROOT / "plugins/lifecycle-github/tools/test_bootstrap_sdlc.py",
            "gitlab": REPO_ROOT / "plugins/lifecycle-gitlab/tools/test_bootstrap_sdlc.py",
        }

    def test_all_copies_exist(self) -> None:
        for name, path in self._paths().items():
            self.assertTrue(path.is_file(), f"{name} copy missing at {path}")

    def test_copies_are_identical_except_the_docstring_paths(self) -> None:
        paths = self._paths()
        normalized = {
            name: TEST_BOOTSTRAP_PATH_PATTERN.sub("PLUGIN_TOOLS_PATH", path.read_text(encoding="utf-8"))
            for name, path in paths.items()
        }
        core = normalized["core"]
        for name in ("github", "gitlab"):
            self.assertEqual(
                core,
                normalized[name],
                f"plugins/lifecycle-{name}/tools/test_bootstrap_sdlc.py has drifted from "
                "plugins/lifecycle/tools/test_bootstrap_sdlc.py beyond the docstring paths",
            )

    def test_each_copy_actually_names_its_own_path(self) -> None:
        for name in ("github", "gitlab"):
            path = self._paths()[name]
            text = path.read_text(encoding="utf-8")
            self.assertIn(f"plugins/lifecycle-{name}/tools", text)


class DuplicatedSkillBodyTests(unittest.TestCase):
    """The three bundled skills' bodies must match their core source."""

    SKILLS = {
        "lifecycle-onboarding": "lifecycle-onboarding{suffix}",
        "lifecycle-review": "lifecycle-review-generic{suffix}",
        "brief-pending-gates": "brief-pending-gates{suffix}",
    }

    def _core_path(self, skill: str) -> Path:
        return REPO_ROOT / "plugins/lifecycle/skills" / skill / "SKILL.md"

    def _forge_path(self, skill: str, forge: str) -> Path:
        suffix = f"-{forge}"
        dest_name = self.SKILLS[skill].format(suffix=suffix)
        return REPO_ROOT / f"plugins/lifecycle-{forge}/skills" / dest_name / "SKILL.md"

    def test_all_copies_exist(self) -> None:
        for skill in self.SKILLS:
            self.assertTrue(self._core_path(skill).is_file(), f"missing core skill {skill}")
            for forge in FORGES:
                path = self._forge_path(skill, forge)
                self.assertTrue(path.is_file(), f"missing bundled skill copy {path}")

    def test_bodies_match_after_normalizing_cross_reference_renames(self) -> None:
        for skill in self.SKILLS:
            core_body = _skill_body(self._core_path(skill))
            for forge in FORGES:
                forge_body = _skill_body(self._forge_path(skill, forge))
                normalized = _skill_name_pattern(forge).sub(_normalize_skill_name, forge_body)
                normalized = _normalize_forge_terms(forge, normalized)
                normalized = normalized.replace(DUPLICATION_NOTE, "", 1)
                self.assertEqual(
                    core_body,
                    normalized,
                    f"{self._forge_path(skill, forge)} body has drifted from "
                    f"{self._core_path(skill)} beyond the expected cross-reference "
                    "renames and the forge-only duplication note",
                )

    def test_forge_copies_carry_the_duplication_note(self) -> None:
        # The positive half of the normalization above: proves the note is
        # actually present in every forge copy, rather than the normalization
        # silently no-op'ing (e.g. after a future wording tweak) and this
        # test class passing for the wrong reason.
        for skill in self.SKILLS:
            for forge in FORGES:
                path = self._forge_path(skill, forge)
                body = _skill_body(path)
                self.assertIn(DUPLICATION_NOTE, body, f"{path} is missing the duplication-note callout")

    def test_core_copy_never_carries_the_duplication_note(self) -> None:
        # The core copy is entirely register-generated; a hand-added
        # duplication note there would silently vanish on the next real
        # regeneration (exactly what happened before this test existed).
        # Fail loudly instead if it ever reappears there.
        for skill in self.SKILLS:
            path = self._core_path(skill)
            body = _skill_body(path)
            self.assertNotIn(
                DUPLICATION_NOTE,
                body,
                f"{path} (register-generated) carries the forge-only duplication note -- "
                "it will be silently deleted on the next real regeneration; remove it here "
                "instead of relying on that",
            )

    def test_github_copies_translate_gate_tracking_terms(self) -> None:
        # Regression guard: a github copy that left core's GitLab-flavored
        # gate-tracking-skill/reason-code example untranslated would still
        # pass test_bodies_match_after_normalizing_cross_reference_renames
        # above, because the untranslated text is byte-identical to core's
        # own text. This is the actual enforcement that translation happened.
        for skill in self.SKILLS:
            path = self._forge_path(skill, "github")
            body = _skill_body(path)
            for term in GITLAB_LEAK_TERMS:
                self.assertNotIn(
                    term,
                    body,
                    f"{path} still contains the untranslated GitLab-only term {term!r}",
                )

    def test_frontmatter_name_matches_the_suffixed_skill_directory(self) -> None:
        for skill in self.SKILLS:
            for forge in FORGES:
                path = self._forge_path(skill, forge)
                text = path.read_text(encoding="utf-8")
                expected_name = self.SKILLS[skill].format(suffix=f"-{forge}")
                self.assertIn(f"name: {expected_name}\n", text)


if __name__ == "__main__":
    unittest.main()
