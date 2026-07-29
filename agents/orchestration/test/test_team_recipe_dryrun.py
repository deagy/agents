"""Tests for the team-recipe dry-run visualizer.

Covers `agents/orchestration/src/team_recipe_dryrun.py`: a fixed recipe that
fires (enough matched routes and selected members), one that doesn't (too
few matched routes), a dynamic recipe that fires (role selected, required
route matched, a keyword hits), one that doesn't (no keyword hits), and a
run against the real current `routing.yaml` proving the tool doesn't crash
and produces a `fires: bool` verdict with reasoning for every real recipe.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

from build_dispatch_plan import build_dispatch_plan  # noqa: E402
from routing import load_catalog, load_routing  # noqa: E402
from team_recipe_dryrun import (  # noqa: E402
    _resolve_synthetic_mode_signals,
    explain_dynamic_recipe,
    explain_fixed_recipe,
    explain_recipes,
    main,
)

CONFIG = load_routing(ROOT / "routing.yaml")
CATALOG = load_catalog(AGENTS_ROOT / "catalog.yaml")

FIXED_RECIPE = next(recipe for recipe in CONFIG["team_recipes"] if recipe["type"] == "fixed")
DYNAMIC_RECIPE = next(recipe for recipe in CONFIG["team_recipes"] if recipe["type"] == "dynamic")


class FixedRecipeExplanationTests(unittest.TestCase):
    def test_fires_when_routes_and_members_both_satisfied(self) -> None:
        matched_route_ids = set(FIXED_RECIPE["route_ids"][: FIXED_RECIPE["minimum_matches"]])
        minimum_members = FIXED_RECIPE.get("minimum_members_selected", 2)
        selected_agents = set(FIXED_RECIPE["members"][:minimum_members])

        explanation = explain_fixed_recipe(FIXED_RECIPE, matched_route_ids, selected_agents)

        self.assertTrue(explanation["fires"])
        self.assertTrue(explanation["routes"]["satisfied"])
        self.assertTrue(explanation["members"]["satisfied"])
        self.assertEqual(explanation["routes"]["actual_matches"], len(matched_route_ids))
        self.assertEqual(sorted(explanation["members"]["selected_members"]), sorted(selected_agents))

    def test_does_not_fire_when_too_few_routes_match(self) -> None:
        # One fewer than minimum_matches -- routes condition alone must fail
        # even though every member is selected.
        matched_route_ids = set(FIXED_RECIPE["route_ids"][: FIXED_RECIPE["minimum_matches"] - 1])
        selected_agents = set(FIXED_RECIPE["members"])

        explanation = explain_fixed_recipe(FIXED_RECIPE, matched_route_ids, selected_agents)

        self.assertFalse(explanation["fires"])
        self.assertFalse(explanation["routes"]["satisfied"])
        self.assertTrue(explanation["members"]["satisfied"])
        self.assertEqual(
            explanation["routes"]["actual_matches"], FIXED_RECIPE["minimum_matches"] - 1
        )
        self.assertIn(explanation["routes"]["actual_matches"], range(FIXED_RECIPE["minimum_matches"]))

    def test_does_not_fire_when_too_few_members_selected(self) -> None:
        matched_route_ids = set(FIXED_RECIPE["route_ids"])
        selected_agents: set[str] = set()

        explanation = explain_fixed_recipe(FIXED_RECIPE, matched_route_ids, selected_agents)

        self.assertFalse(explanation["fires"])
        self.assertTrue(explanation["routes"]["satisfied"])
        self.assertFalse(explanation["members"]["satisfied"])
        self.assertEqual(explanation["members"]["selected_members"], [])
        self.assertEqual(sorted(explanation["members"]["unselected_members"]), sorted(FIXED_RECIPE["members"]))

    def test_unmatched_routes_reported_as_complement(self) -> None:
        matched_route_ids = {FIXED_RECIPE["route_ids"][0]}
        explanation = explain_fixed_recipe(FIXED_RECIPE, matched_route_ids, set())
        self.assertEqual(
            sorted(explanation["routes"]["unmatched_route_ids"]),
            sorted(set(FIXED_RECIPE["route_ids"]) - matched_route_ids),
        )


class DynamicRecipeExplanationTests(unittest.TestCase):
    def test_fires_when_role_route_and_keyword_all_satisfied(self) -> None:
        role = DYNAMIC_RECIPE["role"]
        requires_route = DYNAMIC_RECIPE.get("requires_route")
        matched_route_ids = {requires_route} if requires_route else set()
        keyword = DYNAMIC_RECIPE["keywords"][0]

        explanation = explain_dynamic_recipe(
            DYNAMIC_RECIPE, matched_route_ids, {role}, f"debugging this: {keyword} behavior"
        )

        self.assertTrue(explanation["fires"])
        self.assertTrue(explanation["role"]["selected"])
        self.assertTrue(explanation["requires_route"]["matched"])
        self.assertTrue(explanation["keywords"]["satisfied"])
        self.assertIn(keyword, explanation["keywords"]["matched_keywords"])

    def test_does_not_fire_without_a_keyword_match(self) -> None:
        role = DYNAMIC_RECIPE["role"]
        requires_route = DYNAMIC_RECIPE.get("requires_route")
        matched_route_ids = {requires_route} if requires_route else set()

        explanation = explain_dynamic_recipe(
            DYNAMIC_RECIPE, matched_route_ids, {role}, "plain unrelated task text with no signal"
        )

        self.assertFalse(explanation["fires"])
        self.assertTrue(explanation["role"]["selected"])
        self.assertTrue(explanation["requires_route"]["matched"])
        self.assertFalse(explanation["keywords"]["satisfied"])
        self.assertEqual(explanation["keywords"]["matched_keywords"], [])
        self.assertEqual(
            sorted(explanation["keywords"]["unmatched_keywords"]), sorted(DYNAMIC_RECIPE["keywords"])
        )

    def test_does_not_fire_when_role_not_selected(self) -> None:
        requires_route = DYNAMIC_RECIPE.get("requires_route")
        matched_route_ids = {requires_route} if requires_route else set()
        keyword = DYNAMIC_RECIPE["keywords"][0]

        explanation = explain_dynamic_recipe(DYNAMIC_RECIPE, matched_route_ids, set(), keyword)

        self.assertFalse(explanation["fires"])
        self.assertFalse(explanation["role"]["selected"])

    def test_does_not_fire_when_required_route_missing(self) -> None:
        role = DYNAMIC_RECIPE["role"]
        keyword = DYNAMIC_RECIPE["keywords"][0]

        explanation = explain_dynamic_recipe(DYNAMIC_RECIPE, set(), {role}, keyword)

        self.assertFalse(explanation["fires"])
        self.assertFalse(explanation["requires_route"]["matched"])

    def test_empty_keyword_list_can_never_fire(self) -> None:
        recipe = {**DYNAMIC_RECIPE, "keywords": []}
        role = recipe["role"]
        requires_route = recipe.get("requires_route")
        matched_route_ids = {requires_route} if requires_route else set()

        explanation = explain_dynamic_recipe(recipe, matched_route_ids, {role}, "anything at all")

        self.assertFalse(explanation["fires"])
        self.assertFalse(explanation["keywords"]["satisfied"])


class SyntheticModeSignalTests(unittest.TestCase):
    def test_rejects_unknown_route_id(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_synthetic_mode_signals(CONFIG, ["not-a-real-route"], [], "")

    def test_accepts_known_route_ids_and_arbitrary_agent_ids(self) -> None:
        route_id = CONFIG["routes"][0]["id"]
        matched_route_ids, selected_agents, task_text = _resolve_synthetic_mode_signals(
            CONFIG, [route_id], ["some-agent"], "task text"
        )
        self.assertEqual(matched_route_ids, {route_id})
        self.assertEqual(selected_agents, {"some-agent"})
        self.assertEqual(task_text, "task text")


class RecipeIdFilterTests(unittest.TestCase):
    def test_unknown_recipe_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            explain_recipes(CONFIG, set(), set(), "", recipe_id="not-a-real-recipe")

    def test_known_recipe_id_returns_exactly_one_explanation(self) -> None:
        explanations = explain_recipes(CONFIG, set(), set(), "", recipe_id=FIXED_RECIPE["id"])
        self.assertEqual(len(explanations), 1)
        self.assertEqual(explanations[0]["id"], FIXED_RECIPE["id"])


class RealRoutingConfigurationTests(unittest.TestCase):
    """Regression guard: every real team_recipes[] entry in this repository's
    own routing.yaml must produce a sensible, non-crashing explanation."""

    def test_every_real_recipe_produces_a_verdict_with_reasoning(self) -> None:
        explanations = explain_recipes(CONFIG, set(), set(), "")
        self.assertEqual(len(explanations), len(CONFIG["team_recipes"]))
        recipe_ids = {recipe["id"] for recipe in CONFIG["team_recipes"]}
        self.assertEqual({explanation["id"] for explanation in explanations}, recipe_ids)
        for explanation in explanations:
            self.assertIn(explanation["type"], {"fixed", "dynamic"})
            self.assertIsInstance(explanation["fires"], bool)
            if explanation["type"] == "fixed":
                self.assertIn("routes", explanation)
                self.assertIn("members", explanation)
            else:
                self.assertIn("role", explanation)
                self.assertIn("requires_route", explanation)
                self.assertIn("keywords", explanation)

    def test_no_signals_means_no_real_recipe_fires(self) -> None:
        # Every real fixed recipe requires minimum_matches >= 1 and every
        # real dynamic recipe requires a role selection and a keyword hit,
        # so an empty signal set must be a universal no-fire baseline.
        explanations = explain_recipes(CONFIG, set(), set(), "")
        for explanation in explanations:
            self.assertFalse(explanation["fires"], explanation["id"])

    def test_cli_main_runs_cleanly_over_full_real_config(self) -> None:
        exit_code = main(
            [
                "--routing",
                str(ROOT / "routing.yaml"),
                "--catalog",
                str(AGENTS_ROOT / "catalog.yaml"),
                "--matched-routes",
                "frontend,backend,infrastructure,pipeline,supply-chain,debugging",
                "--selected-agents",
                "code-reviewer,infrastructure-reviewer,pipeline-security-reviewer,"
                "supply-chain-security-reviewer,frontend-engineer,backend-engineer,"
                "infrastructure-provisioner,cicd-engineer,debugging-engineer",
                "--task",
                "intermittent flaky recurring hasn't converged elusive hard to reproduce",
                "--format",
                "json",
            ]
        )
        self.assertEqual(exit_code, 0)

    def test_fires_verdicts_match_a_real_build_dispatch_plan_teams_array(self) -> None:
        # The tool's headline claim is that its verdicts can never disagree
        # with a real dispatch. Lock that in as an automated regression,
        # not just a manual/prose demonstration: build a real plan for a
        # concrete task, then independently ask explain_recipes about the
        # same matched-routes/selected-agents/task-text signals, and assert
        # the set of recipe ids marked fires=True is exactly the set of
        # recipe ids build_dispatch_plan() actually put in plan["teams"].
        task = "Add a React upload form backed by a PostgreSQL API"
        plan = build_dispatch_plan(
            CONFIG,
            CATALOG,
            {
                "task": task,
                "task_id": None,
                "repository_root": str(AGENTS_ROOT.parent),
                "base": None,
                "changed_files": ["frontend/src/Upload.tsx", "services/upload/main.go"],
                "changed_file_source": "explicit",
                "classification": "internal",
                "source": "test-fixture",
                "top": 20,
            },
        )
        matched_route_ids = set(plan.get("matched_routes", []))
        selected_agents = {
            *plan["agents"].get("primary", []),
            *plan["agents"].get("reviewers", []),
            *plan["agents"].get("support", []),
        }
        explanations = explain_recipes(CONFIG, matched_route_ids, selected_agents, task)
        dryrun_fired_ids = {e["id"] for e in explanations if e["fires"]}
        plan_team_ids = {team["id"] for team in plan.get("teams", [])}
        self.assertEqual(plan_team_ids, dryrun_fired_ids)

    def test_cli_main_reports_task_mode_against_real_repository(self) -> None:
        exit_code = main(
            [
                "--routing",
                str(ROOT / "routing.yaml"),
                "--catalog",
                str(AGENTS_ROOT / "catalog.yaml"),
                "--task",
                "Add a React upload form backed by a PostgreSQL API",
                "--files",
                "frontend/src/Upload.tsx,services/upload/main.go",
                "--root",
                str(AGENTS_ROOT.parent),
            ]
        )
        self.assertEqual(exit_code, 0)

    def test_cli_main_requires_a_mode(self) -> None:
        with self.assertRaises(ValueError):
            main(["--routing", str(ROOT / "routing.yaml"), "--catalog", str(AGENTS_ROOT / "catalog.yaml")])

    def test_cli_main_rejects_files_combined_with_synthetic_mode(self) -> None:
        with self.assertRaises(ValueError):
            main(
                [
                    "--routing",
                    str(ROOT / "routing.yaml"),
                    "--catalog",
                    str(AGENTS_ROOT / "catalog.yaml"),
                    "--matched-routes",
                    "frontend",
                    "--files",
                    "a.tsx",
                ]
            )


if __name__ == "__main__":
    unittest.main()
