"""Meaningful state-machine checks using real isolated Git repositories."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("taskctl", Path(__file__).with_name("taskctl.py"))
taskctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(taskctl)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repos = [self.root / name for name in ("app", "web", "api")]
        for repo in self.repos:
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "source.txt").write_text("original\n")
            subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
        arguments = ["init", "--goal", "Ship a verified feature", "--tier", "standard"]
        for repo in self.repos:
            arguments += ["--repo", str(repo)]
        self.run_id = self.call(*arguments)["run"]

    def call(self, *args):
        return taskctl.run(taskctl.parser().parse_args(["--root", str(self.root), *args]))

    def state(self):
        return self.call("status", self.run_id)

    def add(self, key="one", repo=0, depends=(), agent="gt-implementer"):
        args = ["add", self.run_id, "--id", key, "--title", key, "--agent", agent,
                "--repo", str(self.repos[repo]), "--accept", "Relevant checks pass"]
        for dependency in depends:
            args += ["--depends", dependency]
        return self.call(*args)

    def claim(self, key="one", owner="worker-1"):
        return self.call("claim", self.run_id, key, "--owner", owner)

    def finish(self, key="one", evidence="Unit suite passed", owner="worker-1"):
        return self.call("finish", self.run_id, key, "--owner", owner, "--evidence", evidence)

    def review(self, key="one", verdict="pass", owner="reviewer-1", reviewer="gt-reviewer"):
        return self.call("review", self.run_id, key, "--reviewer", reviewer, "--owner", owner,
                         "--verdict", verdict, "--evidence", "Independent checks passed")

    def rejected(self, operation):
        before = json.dumps(self.state(), sort_keys=True)
        with self.assertRaises(taskctl.WorkflowError):
            operation()
        self.assertEqual(before, json.dumps(self.state(), sort_keys=True))

    def test_dependencies_and_full_transition(self):
        self.add()
        self.add("two", depends=["one"])
        self.rejected(lambda: self.claim("two"))
        self.claim()
        self.finish()
        self.assertFalse(self.state()["complete"])
        self.review()
        self.claim("two")
        self.finish("two")
        self.review("two")
        self.assertTrue(self.state()["complete"])

    def test_invalid_graph_and_out_of_scope_are_atomic(self):
        self.rejected(lambda: self.add(depends=["missing"]))
        self.rejected(lambda: self.add(depends=["one"]))
        outside = self.root / "outside"
        subprocess.run(["git", "init", "-q", str(outside)], check=True)
        self.rejected(lambda: self.call("add", self.run_id, "--id", "one", "--title", "x",
            "--agent", "gt-implementer", "--repo", str(outside), "--accept", "verified"))

    def test_concurrency_checkout_reservation_and_two_task_limit(self):
        self.add()
        self.add("same")
        self.add("two", repo=1)
        self.add("three", repo=2)
        self.claim()
        self.rejected(lambda: self.claim("same"))
        self.claim("two")
        self.rejected(lambda: self.claim("three"))
        self.finish()
        self.rejected(lambda: self.claim("same"))
        self.review()
        self.claim("three")

    def test_owner_and_evidence_are_required(self):
        self.add()
        self.claim()
        self.rejected(lambda: self.finish(owner="wrong"))
        self.rejected(lambda: self.finish(evidence="  "))
        self.finish()
        self.rejected(lambda: self.review(owner="worker-1"))

    def test_same_role_cannot_review_itself(self):
        self.add(agent="gt-reviewer")
        self.claim()
        self.finish()
        self.rejected(self.review)

    def test_stale_review_and_recovery(self):
        self.add()
        self.claim()
        self.finish()
        (self.repos[0] / "source.txt").write_text("changed\n")
        self.rejected(self.review)
        self.rejected(lambda: self.call("resume", self.run_id, "one", "--evidence", "worker ended"))
        self.call("resume", self.run_id, "one", "--workers-stopped", "--evidence", "worker ended")
        task = self.state()["tasks"]["one"]
        self.assertIsNone(task["evidence"])
        self.assertIsNone(task["snapshot"])
        self.assertIsNone(task["approval"])
        self.claim()
        self.finish()
        self.review()

    def test_snapshot_captures_untracked_index_deletion_and_symlink(self):
        repo = self.repos[0]
        first = taskctl.snapshot(str(repo))
        (repo / "extra").write_text("new")
        second = taskctl.snapshot(str(repo))
        self.assertNotEqual(first, second)
        (repo / "extra").unlink()
        self.assertEqual(first, taskctl.snapshot(str(repo)))
        subprocess.run(["git", "-C", str(repo), "rm", "--cached", "source.txt"], check=True, capture_output=True)
        self.assertNotEqual(first, taskctl.snapshot(str(repo)))
        (repo / "source.txt").unlink()
        (repo / "source.txt").symlink_to("missing-target")
        self.assertNotEqual(second, taskctl.snapshot(str(repo)))

    def test_snapshot_excludes_ledger_and_ignored_files(self):
        repo = self.repos[0]
        (repo / ".gitignore").write_text("ignored\n")
        before = taskctl.snapshot(str(repo))
        ledger = repo / ".claude" / "task-runs" / "example"
        ledger.mkdir(parents=True)
        (ledger / "state.json").write_text("{}")
        (repo / "ignored").write_text("ignored")
        self.assertEqual(before, taskctl.snapshot(str(repo)))

    def test_uninitialized_submodule_does_not_recurse_into_parent(self):
        repo = self.repos[0]
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "Fixture"], check=True)
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
        subprocess.run(["git", "-C", str(repo), "update-index", "--add", "--cacheinfo",
                        f"160000,{head},vendor"], check=True)
        (repo / "vendor").mkdir()
        self.assertEqual(64, len(taskctl.snapshot(str(repo))))

    def test_review_cycle_budget(self):
        self.add()
        for _ in range(2):
            self.claim()
            self.finish()
            self.review(verdict="changes")
        self.assertEqual(self.state()["tasks"]["one"]["status"], "blocked")
        self.rejected(lambda: self.call("resume", self.run_id, "one", "--workers-stopped", "--evidence", "try again"))

    def test_claim_budget_and_explicit_block(self):
        self.add()
        for index in range(3):
            self.claim()
            self.rejected(lambda: self.call("block", self.run_id, "one", "--evidence", "interrupted"))
            self.call("block", self.run_id, "one", "--workers-stopped", "--evidence", "worker stopped")
            if index < 2:
                self.call("resume", self.run_id, "one", "--workers-stopped", "--evidence", "cause resolved")
        self.rejected(lambda: self.call("resume", self.run_id, "one", "--workers-stopped", "--evidence", "again"))

    def test_cross_run_checkout_collision(self):
        self.add()
        self.claim()
        self.run_id = self.call("init", "--goal", "Other run", "--repo", str(self.repos[0]))["run"]
        self.add()
        self.rejected(self.claim)

    def test_concurrent_process_claims_serialize(self):
        self.add("one")
        self.add("two")
        commands = [["python3", str(Path(__file__).with_name("taskctl.py")), "--root", str(self.root),
                     "claim", self.run_id, key, "--owner", key] for key in ("one", "two")]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in commands]
        for process in processes:
            process.communicate(timeout=15)
        self.assertEqual([0, 2], sorted(process.returncode for process in processes))
        self.assertEqual(1, sum(task["status"] == "running" for task in self.state()["tasks"].values()))

    def test_high_risk_requires_risk_reviewer(self):
        self.add(agent="gt-desktop")
        self.assertEqual("high", self.state()["tasks"]["one"]["risk"])
        self.claim()
        self.finish()
        self.rejected(self.review)
        self.review(reviewer="gt-risk-reviewer")

    def test_opus_task_cannot_downgrade_review_risk(self):
        self.rejected(lambda: self.call("add", self.run_id, "--id", "one", "--title", "Desktop flow",
            "--agent", "gt-desktop", "--repo", str(self.repos[0]), "--risk", "low", "--accept", "Flow works"))

    def test_cross_coordinator_root_reservation(self):
        self.add()
        self.claim()
        original_root, original_run = self.root, self.run_id
        self.root = self.repos[0]
        self.run_id = self.call("init", "--goal", "Repo-local run", "--repo", str(self.repos[0]))["run"]
        self.add()
        self.rejected(self.claim)
        local_root, local_run = self.root, self.run_id
        self.root, self.run_id = original_root, original_run
        self.finish()
        self.review()
        self.root, self.run_id = local_root, local_run
        self.claim()

    def test_orphaned_reservation_requires_explicit_recovery(self):
        self.add()
        identity = {"root": str(self.root), "run": self.run_id, "task": "one"}
        taskctl.reservation(str(self.repos[0]), "acquire", identity)
        self.rejected(self.claim)
        self.rejected(lambda: self.call("block", self.run_id, "one", "--evidence", "orphan"))
        self.rejected(lambda: self.call("recover", self.run_id, "one", "--evidence", "orphan"))
        self.call("recover", self.run_id, "one", "--workers-stopped", "--evidence", "Verified session exited")
        self.assertEqual("blocked", self.state()["tasks"]["one"]["status"])
        self.call("resume", self.run_id, "one", "--workers-stopped", "--evidence", "Cause resolved")
        self.claim()

    def test_completion_revalidates_latest_approval_per_repo(self):
        self.add()
        self.claim()
        self.finish()
        self.review()
        self.assertTrue(self.state()["complete"])
        (self.repos[0] / "source.txt").write_text("Later changes")
        self.assertFalse(self.state()["complete"])
        self.assertEqual([str(self.repos[0])], self.state()["stale_repositories"])
        self.add("two")
        self.rejected(lambda: self.claim("two"))
        self.call("invalidate", self.run_id, "--repo", str(self.repos[0]), "--evidence", "Reviewed external drift; recheck previous acceptance")
        self.claim("one")
        self.finish("one")
        self.review("one")
        self.claim("two")
        self.finish("two")
        self.review("two")
        self.assertTrue(self.state()["complete"])

    def test_invalidation_propagates_to_consumers_without_replenishing_budget(self):
        self.add("one")
        self.claim("one")
        self.finish("one")
        self.review("one")
        self.add("two", repo=1, depends=["one"])
        self.claim("two")
        self.finish("two")
        self.review("two")
        self.call("invalidate", self.run_id, "--repo", str(self.repos[0]), "--evidence", "Producer changed")
        self.assertEqual(["pending", "pending"], [t["status"] for t in self.state()["tasks"].values()])
        self.assertEqual([1, 1], [t["claims"] for t in self.state()["tasks"].values()])
        self.rejected(lambda: self.claim("two"))

    def test_legitimate_repair_after_prior_approval_preserves_admission(self):
        self.add("one")
        self.claim("one")
        self.finish("one")
        self.review("one")
        self.add("two", depends=["one"])
        self.claim("two")
        (self.repos[0] / "source.txt").write_text("Authorized second task")
        self.finish("two")
        self.review("two", verdict="changes")
        self.claim("two")
        (self.repos[0] / "source.txt").write_text("Authorized second task repaired")
        self.finish("two")
        self.review("two")
        self.assertTrue(self.state()["complete"])

    def accepted_producer_and_consumer(self):
        self.add("producer")
        self.claim("producer")
        self.finish("producer")
        self.review("producer")
        self.add("consumer", repo=1, depends=["producer"])
        self.claim("consumer")

    def revise_producer(self):
        self.add("revision")
        self.claim("revision")
        (self.repos[0] / "source.txt").write_text("Changed producer contract")
        self.finish("revision")
        self.review("revision")

    def test_changed_dependency_rejects_finish_and_allows_explicit_recovery(self):
        self.accepted_producer_and_consumer()
        self.revise_producer()
        self.rejected(lambda: self.finish("consumer"))
        self.call("block", self.run_id, "consumer", "--workers-stopped",
                  "--evidence", "Consumer stopped; input changed")
        self.call("resume", self.run_id, "consumer", "--workers-stopped",
                  "--evidence", "Reconcile new producer contract and rerun tests")
        self.claim("consumer")
        self.finish("consumer")
        self.review("consumer")
        self.assertTrue(self.state()["complete"])

    def test_changed_dependency_rejects_review(self):
        self.accepted_producer_and_consumer()
        self.finish("consumer")
        self.revise_producer()
        self.rejected(lambda: self.review("consumer"))

    def test_later_producer_approval_does_not_revalidate_old_consumer(self):
        self.accepted_producer_and_consumer()
        self.finish("consumer")
        self.review("consumer")
        self.revise_producer()
        self.assertFalse(self.state()["complete"])
        self.assertEqual([str(self.repos[0])], self.state()["stale_repositories"])
        self.add("consumer_followup", repo=1, depends=["consumer"])
        self.rejected(lambda: self.claim("consumer_followup"))
        self.call("invalidate", self.run_id, "--repo", str(self.repos[0]),
                  "--evidence", "Revalidate producer and all consumers against new contract")
        for key in ("producer", "revision", "consumer", "consumer_followup"):
            self.claim(key)
            self.finish(key)
            self.review(key)
        self.assertTrue(self.state()["complete"])

    def test_transitive_dependencies_are_bound_to_consumers(self):
        self.accepted_producer_and_consumer()
        self.finish("consumer")
        self.review("consumer")
        self.add("downstream", repo=2, depends=["consumer"])
        self.claim("downstream")
        self.revise_producer()
        self.rejected(lambda: self.finish("downstream"))

    def test_existing_consumer_without_dependency_binding_needs_revalidation(self):
        self.accepted_producer_and_consumer()
        state_path = self.root / ".claude" / "task-runs" / self.run_id / "state.json"
        state = json.loads(state_path.read_text())
        del state["tasks"]["consumer"]["dependency_snapshots"]
        taskctl.save(state_path, state)
        self.rejected(lambda: self.finish("consumer"))


if __name__ == "__main__":
    unittest.main()
