import unittest
from collections import deque
from pathlib import Path

from asf.state_machine.graph import build_graph
from asf.state_machine.triggers import Trigger
from asf.workflow.loader import load_workflow

REPO_ROOT = Path(__file__).resolve().parents[2]


class StateMachineGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wf_path = REPO_ROOT / "workflow-definitions" / "software-development.yaml"
        cls.workflow_def = load_workflow(wf_path)
        cls.graph = build_graph(cls.workflow_def)

    def test_software_development_stage_list_exact_24(self):
        expected_stages = [
            "NEW",
            # Step 1: spec (approval)
            "SPEC_DRAFT",
            "SPEC_REVIEW",
            "SPEC_REJECTED",
            "SPEC_APPROVED",
            "SPEC_ESCALATED",
            # Step 2: plan (approval)
            "PLAN_DRAFT",
            "PLAN_REVIEW",
            "PLAN_REJECTED",
            "PLAN_APPROVED",
            "PLAN_ESCALATED",
            # Step 3: task (approval)
            "TASK_DRAFT",
            "TASK_REVIEW",
            "TASK_REJECTED",
            "TASK_APPROVED",
            "TASK_ESCALATED",
            # Step 4: implement (plain)
            "IMPLEMENTING",
            # Step 5: review (plain)
            "CODE_REVIEW",
            # Step 6: test (plain)
            "TESTING",
            # Step 7: ci (plain)
            "CI",
            # Step 8: merge (plain)
            "READY_TO_MERGE",
            # Global terminals
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        ]

        actual_stages = [s.name for s in self.graph.stages]
        self.assertEqual(len(self.graph.stages), 24)
        self.assertEqual(actual_stages, expected_stages)

        # Stage names unique
        self.assertEqual(len(actual_stages), len(set(actual_stages)))

    def test_every_stage_reachable_from_new(self):
        adj: dict[str, list[str]] = {}
        for edge in self.graph.edges:
            adj.setdefault(edge.source, []).append(edge.target)

        visited: set[str] = set()
        queue: deque[str] = deque(["NEW"])
        visited.add("NEW")

        while queue:
            curr = queue.popleft()
            for neighbor in adj.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        all_stage_names = {s.name for s in self.graph.stages}
        self.assertEqual(visited, all_stage_names)

    def test_completed_reachable_from_every_non_terminal_stage(self):
        # Exclude transitions to FAILED and CANCELLED
        adj: dict[str, list[str]] = {}
        for edge in self.graph.edges:
            if edge.target not in {"FAILED", "CANCELLED"}:
                adj.setdefault(edge.source, []).append(edge.target)

        non_terminal_stages = [
            s.name for s in self.graph.stages if s.name not in {"COMPLETED", "FAILED", "CANCELLED"}
        ]

        for start in non_terminal_stages:
            with self.subTest(stage=start):
                visited: set[str] = set()
                queue: deque[str] = deque([start])
                visited.add(start)
                reached_completed = False

                while queue:
                    curr = queue.popleft()
                    if curr == "COMPLETED":
                        reached_completed = True
                        break
                    for neighbor in adj.get(curr, []):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)

                self.assertTrue(
                    reached_completed,
                    f"COMPLETED was not reachable from non-terminal stage '{start}'",
                )

    def test_failed_and_cancelled_edges_from_every_non_terminal_stage(self):
        non_terminal_stages = {
            s.name for s in self.graph.stages if s.name not in {"COMPLETED", "FAILED", "CANCELLED"}
        }

        fail_sources = {
            e.source for e in self.graph.edges if e.trigger == Trigger.FAIL and e.target == "FAILED"
        }
        cancel_sources = {
            e.source
            for e in self.graph.edges
            if e.trigger == Trigger.CANCEL and e.target == "CANCELLED"
        }

        self.assertEqual(fail_sources, non_terminal_stages)
        self.assertEqual(cancel_sources, non_terminal_stages)

    def test_terminal_stages_have_no_outgoing_edges(self):
        terminal_stages = {"COMPLETED", "FAILED", "CANCELLED"}
        outgoing_from_terminals = [e for e in self.graph.edges if e.source in terminal_stages]
        self.assertEqual(outgoing_from_terminals, [])

    def test_guards_appear_only_on_revise_edges(self):
        for edge in self.graph.edges:
            if edge.guard != "none":
                self.assertEqual(
                    edge.trigger,
                    Trigger.REVISE,
                    f"Guard '{edge.guard}' appeared on non-REVISE edge: {edge}",
                )
                self.assertIn(edge.guard, {"within_limit", "limit_reached"})
