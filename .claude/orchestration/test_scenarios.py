"""Bounded workflow simulations; tiny temporary Git fixtures, no model calls.

Run: python3 -m unittest discover -s .claude/orchestration -p test_scenarios.py -v
Task count exercises coordination; it does not represent a production-sized app.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("scenario_taskctl", Path(__file__).with_name("taskctl.py"))
taskctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(taskctl)


class WorkflowScenarios(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gittree-orchestration-scenario-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repos = [self.root / name for name in ("api", "desktop", "website")]
        for repo in self.repos:
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "fixture.txt").write_text("initial\n")
            subprocess.run(["git", "-C", str(repo), "add", "fixture.txt"], check=True)

    def call(self, *args):
        return taskctl.run(taskctl.parser().parse_args(["--root", str(self.root), *args]))

    def start(self, tier):
        args = ["init", "--goal", "Synthetic orchestration scenario", "--tier", tier]
        for repo in self.repos[:1] if tier == "small" else self.repos:
            args.extend(["--repo", str(repo)])
        self.run_id = self.call(*args)["run"]

    def add(self, key, repo=0, depends=(), high=False, integration=False):
        args = ["add", self.run_id, "--id", key, "--title", key,
                "--agent", "gt-test-manager" if integration else "gt-desktop" if high else "gt-implementer",
                "--repo", str(self.repos[repo]), "--accept", "Fixture matches task; dependency evidence current"]
        if integration:
            args.append("--integration")
        elif high:
            args.extend(["--route-reason", "rule 2 desktop flow"])
        for dependency in depends:
            args.extend(["--depends", dependency])
        self.call(*args)

    def claim(self, key):
        self.call("claim", self.run_id, key, "--owner", "worker-" + key)

    def finish(self, key):
        self.call("finish", self.run_id, key, "--owner", "worker-" + key,
                  "--evidence", "Synthetic fixture assertion passed")

    def review(self, key, high=False, verdict="pass"):
        self.call("review", self.run_id, key, "--owner", "reviewer-" + key,
                  "--reviewer", "gt-risk-reviewer" if high else "gt-reviewer",
                  "--verdict", verdict, "--evidence", "Independent synthetic assertion verified")

    def complete_task(self, key, repo=0, write=False, high=False):
        self.claim(key)
        if write:
            (self.repos[repo] / "fixture.txt").write_text(key + "\n")
            self.assertEqual(key + "\n", (self.repos[repo] / "fixture.txt").read_text())
        self.finish(key)
        self.review(key, high)

    def state_after_restart(self):
        """A new interpreter must recover exactly the on-disk ledger."""
        result = subprocess.run([sys.executable, str(Path(__file__).with_name("taskctl.py")),
                                 "--root", str(self.root), "status", self.run_id],
                                capture_output=True, text=True, check=True, timeout=30)
        loaded = json.loads(result.stdout)
        self.assertEqual(self.call("status", self.run_id), loaded)
        return loaded

    def test_small_single_task(self):
        self.root = self.repos[0]
        self.start("small")
        self.add("tiny_fix")
        self.complete_task("tiny_fix", write=True)
        self.assertTrue(self.state_after_restart()["complete"])

    def test_parallel_fork_join_and_checkout_exclusion(self):
        self.start("standard")
        for key, repo in (("api", 0), ("desktop", 1), ("website", 2), ("same_checkout", 0)):
            self.add(key, repo)
        self.claim("api")
        with self.assertRaises(taskctl.WorkflowError):
            self.claim("same_checkout")
        self.claim("desktop")
        with self.assertRaises(taskctl.WorkflowError):
            self.claim("website")
        self.finish("api")
        with self.assertRaises(taskctl.WorkflowError):
            self.claim("website")
        self.review("api")
        self.claim("website")
        for key in ("desktop", "website"):
            self.finish(key)
            self.review(key)
        self.complete_task("same_checkout")
        self.add("integration", 2, ["same_checkout", "desktop", "website"])
        self.complete_task("integration", 2)
        self.assertTrue(self.state_after_restart()["complete"])

    def scale(self, waves):
        self.start("large")
        previous = [None, None, None]
        for wave in range(waves):
            for repo in range(3):
                key = f"repo{repo}_step{wave:02d}"
                self.add(key, repo, [previous[repo]] if previous[repo] else [], high=wave == 0)
                self.claim(key)
                if wave == 2 and repo == 0:
                    self.call("checkpoint", self.run_id, "--evidence", "Simulated interruption; worker confirmed stopped")
                    self.call("block", self.run_id, key, "--workers-stopped", "--evidence", "Worker stopped before fixture write")
                    self.assertEqual("blocked", self.state_after_restart()["tasks"][key]["status"])
                    self.call("resume", self.run_id, key, "--workers-stopped", "--evidence", "Continue persisted next step")
                    self.claim(key)
                (self.repos[repo] / "fixture.txt").write_text(key + "\n")
                self.finish(key)
                if wave == 3 and repo == 1:
                    self.review(key, verdict="changes")
                    self.claim(key)
                    (self.repos[repo] / "fixture.txt").write_text(key + " corrected\n")
                    self.finish(key)
                self.review(key, high=wave == 0)
                previous[repo] = key
            if wave % 5 == 0:
                self.call("checkpoint", self.run_id, "--evidence", f"Milestone {wave}: three independent streams accepted")
                self.state_after_restart()
        # A real consumer changes after all producer streams settle, then the
        # producer changes again to integrate it: A -> B -> A, with actual writes.
        self.add("cross_repo_consumer", 2, previous)
        self.complete_task("cross_repo_consumer", 2, write=True)
        self.add("producer_integration", 0, ["cross_repo_consumer"])
        self.complete_task("producer_integration", 0, write=True)
        self.assertFalse(self.state_after_restart()["complete"])
        # Sonnet owns the read-only final suite, with independent Opus acceptance.
        self.add("final_integration", integration=True)
        self.complete_task("final_integration", high=True)
        state = self.state_after_restart()
        self.assertEqual(waves * 3 + 3, len(state["tasks"]))
        self.assertTrue(state["complete"])
        self.assertEqual([], state["stale_repositories"])
        self.assertEqual(2, state["tasks"]["repo0_step02"]["claims"])
        self.assertEqual(2, state["tasks"]["repo1_step03"]["claims"])
        self.assertTrue(all(task["status"] == "done" for task in state["tasks"].values()))

    def test_large_30_task_dag_with_recovery(self):
        self.scale(9)

    def test_very_large_60_task_dag_with_recovery(self):
        self.scale(19)

    def test_cross_repo_roundtrip_requires_explicit_integration_gate(self):
        self.start("large")
        steps = [("api_contract", 0, []), ("web_consumer", 2, ["api_contract"]),
                 ("api_integration", 0, ["web_consumer"])]
        for key, repo, dependencies in steps:
            self.add(key, repo, dependencies)
            self.complete_task(key, repo, write=True)
        self.assertFalse(self.state_after_restart()["complete"])
        self.add("final_integration", integration=True)
        self.complete_task("final_integration", high=True)
        state = self.state_after_restart()
        self.assertTrue(state["complete"])
        self.assertTrue(all(task["claims"] == 1 for task in state["tasks"].values()))
        (self.repos[2] / "fixture.txt").write_text("External edit after final acceptance\n")
        self.assertFalse(self.state_after_restart()["complete"])


if __name__ == "__main__":
    unittest.main()
