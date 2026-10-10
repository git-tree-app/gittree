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

    def add(self, key="one", repo=0, depends=(), agent="gt-implementer", **extra):
        args = ["add", self.run_id, "--id", key, "--title", key, "--agent", agent,
                "--repo", str(self.repos[repo]), "--accept", "Relevant checks pass"]
        if agent in taskctl.OPUS_AGENTS and "route_reason" not in extra:
            extra["route_reason"] = "rule 1 risky contract"
        for name, value in extra.items():
            args += ["--" + name.replace("_", "-"), value]
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

    def test_reviewer_is_a_stage_not_a_task(self):
        self.rejected(lambda: self.add(agent="gt-reviewer"))
        self.rejected(lambda: self.add(agent="gt-risk-reviewer"))

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
        self.assertEqual(64, len(taskctl.content_digest(str(repo))))
        self.assertTrue(taskctl.snapshot(str(repo)).startswith("v2:"))

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
            "--agent", "gt-desktop", "--repo", str(self.repos[0]), "--risk", "low", "--accept", "Flow works",
            "--route-reason", "rule 2"))

    def test_opus_profile_requires_route_reason_and_low_risk_refuses_opus_review(self):
        self.rejected(lambda: self.call("add", self.run_id, "--id", "one", "--title", "Desktop flow",
            "--agent", "gt-desktop", "--repo", str(self.repos[0]), "--accept", "Flow works"))
        self.rejected(lambda: self.add(agent="gt-architect", route_reason="  "))
        self.add(agent="gt-architect")
        self.assertEqual("rule 1 risky contract", self.state()["tasks"]["one"]["route_reason"])
        self.add("routine")
        self.claim("routine")
        self.finish("routine")
        self.rejected(lambda: self.review("routine", reviewer="gt-risk-reviewer"))
        self.review("routine")

    def test_commit_after_acceptance_keeps_admission(self):
        self.add()
        self.add("two", depends=["one"])
        self.claim()
        (self.repos[0] / "source.txt").write_text("accepted change\n")
        self.finish()
        self.review()
        subprocess.run(["git", "-C", str(self.repos[0]), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repos[0]), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "commit", "-qm", "Accepted work"], check=True)
        self.assertEqual([], self.state()["stale_repositories"])
        self.claim("two")
        subprocess.run(["git", "-C", str(self.repos[0]), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        "commit", "-q", "--allow-empty", "-m", "Empty"], check=True)
        self.finish("two")
        self.review("two")
        self.assertTrue(self.state()["complete"])
        subprocess.run(["git", "-C", str(self.repos[0]), "reset", "-q", "--hard", "HEAD~1"], check=True)
        self.assertTrue(self.state()["complete"])
        (self.repos[0] / "source.txt").write_text("drift after acceptance\n")
        self.assertFalse(self.state()["complete"])
        self.assertEqual([str(self.repos[0])], self.state()["stale_repositories"])

    def git(self, repo, *args):
        subprocess.run(["git", "-C", str(self.repos[repo]), "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                        *args], check=True, capture_output=True)

    def test_committing_staged_unreviewed_content_is_detected(self):
        self.add()
        self.claim()
        (self.repos[0] / "source.txt").write_text("accepted change\n")
        self.finish()
        self.review()
        (self.repos[0] / "source.txt").write_text("unreviewed\n")
        self.git(0, "add", "source.txt")
        (self.repos[0] / "source.txt").write_text("accepted change\n")
        self.assertEqual([], self.state()["stale_repositories"])  # nothing committed yet
        self.git(0, "commit", "-qm", "smuggled")
        self.assertEqual([str(self.repos[0])], self.state()["stale_repositories"])
        self.add("two")
        self.rejected(lambda: self.claim("two"))
        # A task-created file left out of the commit (`commit -am`) makes the moved HEAD stale;
        # an untracked file that predates the claim is the owner's and may stay untracked.
        self.git(0, "reset", "-q", "--hard", "HEAD")
        (self.repos[0] / "owner-scratch.txt").write_text("pre-existing dirty work\n")
        self.call("invalidate", self.run_id, "--repo", str(self.repos[0]), "--evidence", "reset fixture")
        self.claim()
        (self.repos[0] / "source.txt").write_text("accepted change\n")
        (self.repos[0] / "other.txt").write_text("also reviewed\n")
        self.finish()
        self.review()
        self.git(0, "commit", "-qam", "partial")
        self.rejected(lambda: self.claim("two"))  # other.txt was created by the task and is not committed
        self.git(0, "add", "other.txt")
        self.git(0, "commit", "-qm", "complete")
        self.assertTrue((self.repos[0] / "owner-scratch.txt").exists())
        self.claim("two")

    def test_committed_reviewed_deletion_keeps_admission(self):
        self.git(0, "commit", "-qm", "Fixture")
        (self.repos[0] / "keep.txt").write_text("kept\n")
        self.git(0, "add", "keep.txt")
        self.git(0, "commit", "-qm", "Second file")
        self.add()
        self.add("two", depends=["one"])
        self.claim()
        (self.repos[0] / "source.txt").unlink()
        self.finish()
        self.review()
        self.git(0, "commit", "-qam", "delete reviewed file")
        self.claim("two")
        self.call("block", self.run_id, "two", "--workers-stopped", "--evidence", "admission checked")
        (self.repos[0] / "source.txt").write_text("restored without review\n")
        self.add("three")
        self.rejected(lambda: self.claim("three"))

    def test_producer_commit_after_consumer_claim_is_not_stale(self):
        self.git(0, "commit", "-qm", "Fixture")
        (self.repos[0] / "owner-scratch.txt").write_text("not part of any task\n")
        self.add("producer")
        self.claim("producer")
        (self.repos[0] / "contract.json").write_text("{}\n")
        self.finish("producer")
        self.review("producer")
        self.add("consumer", repo=1, depends=["producer"])
        self.claim("consumer")
        self.git(0, "add", "contract.json")
        self.git(0, "commit", "-qm", "producer committed after consumer claim")
        self.assertEqual(["owner-scratch.txt"], taskctl.untracked(str(self.repos[0])))
        self.finish("consumer")
        self.review("consumer")
        self.assertTrue(self.state()["complete"])

    def test_integration_gate_requires_task_created_files_committed(self):
        self.git(0, "commit", "-qm", "Fixture")
        (self.repos[0] / "owner-scratch.txt").write_text("predates every task\n")
        self.add()
        self.claim()
        (self.repos[0] / "source.txt").write_text("accepted change\n")
        (self.repos[0] / "new.txt").write_text("created by the task\n")
        self.finish()
        self.review()
        self.call("add", self.run_id, "--id", "gate", "--title", "Final gate", "--agent", "gt-test-manager",
                  "--repo", str(self.repos[0]), "--accept", "All suites pass", "--integration")
        self.claim("gate")
        self.finish("gate")
        self.review("gate", reviewer="gt-risk-reviewer")
        self.assertTrue(self.state()["complete"])
        self.git(0, "commit", "-qam", "drops new.txt")
        self.assertFalse(self.state()["complete"])
        self.assertEqual([str(self.repos[0])], self.state()["stale_repositories"])
        self.git(0, "add", "new.txt")
        self.git(0, "commit", "-qm", "complete")
        self.assertTrue(self.state()["complete"])
        self.assertEqual(["owner-scratch.txt"], taskctl.untracked(str(self.repos[0])))

    def test_submodule_pointer_changes_are_content(self):
        repo = self.repos[0]
        self.git(0, "commit", "-qm", "Fixture")
        first = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
        self.git(0, "commit", "-q", "--allow-empty", "-m", "Second")
        second = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
        self.git(0, "update-index", "--add", "--cacheinfo", f"160000,{first},vendor")
        (repo / "vendor").mkdir()
        before = taskctl.content_digest(str(repo))
        self.git(0, "update-index", "--add", "--cacheinfo", f"160000,{second},vendor")
        self.assertNotEqual(before, taskctl.content_digest(str(repo)))

    def test_legacy_snapshot_is_stale_until_rebound(self):
        self.add()
        self.claim()
        self.finish()
        self.review()
        state_path = self.root / ".claude" / "task-runs" / self.run_id / "state.json"
        state = json.loads(state_path.read_text())
        del state["carryovers"]
        state["tasks"]["one"]["approval"]["snapshot"] = "f" * 64
        taskctl.save(state_path, state)
        status = self.state()
        self.assertEqual([], status["open_carryovers"])
        self.assertEqual([str(self.repos[0])], status["stale_repositories"])
        self.add("two")
        self.rejected(lambda: self.claim("two"))
        self.rejected(lambda: self.call("rebind", self.run_id, "--repo", str(self.repos[1]), "--evidence", "x"))
        self.call("rebind", self.run_id, "--repo", str(self.repos[0]), "--evidence", "Checkout equals accepted diff of one")
        self.rejected(lambda: self.call("rebind", self.run_id, "--repo", str(self.repos[0]), "--evidence", "twice"))
        self.assertEqual([], self.state()["stale_repositories"])
        self.claim("two")

    def test_resubmit_rebinds_review_without_spending_a_claim(self):
        self.add()
        self.claim()
        self.finish()
        self.rejected(lambda: self.call("resubmit", self.run_id, "one", "--owner", "worker-1", "--evidence", "nothing"))
        (self.repos[0] / "source.txt").write_text("reviewer-requested one-liner\n")
        self.rejected(self.review)
        self.rejected(lambda: self.call("resubmit", self.run_id, "one", "--owner", "other", "--evidence", "x"))
        self.call("resubmit", self.run_id, "one", "--owner", "worker-1", "--evidence", "alias added; tests rerun")
        task = self.state()["tasks"]["one"]
        self.assertEqual(1, task["claims"])
        self.assertIn("RESUBMIT: alias added", task["evidence"])
        (self.repos[0] / "source.txt").write_text("second follow-up\n")
        self.rejected(lambda: self.call("resubmit", self.run_id, "one", "--owner", "worker-1", "--evidence", "again"))
        self.rejected(self.review)
        (self.repos[0] / "source.txt").write_text("reviewer-requested one-liner\n")
        self.review()
        self.assertEqual("done", self.state()["tasks"]["one"]["status"])

    def test_escalate_hands_submission_to_opus_without_retry_charge(self):
        self.add()
        self.claim()
        self.finish()
        self.rejected(lambda: self.review(verdict="escalate", reviewer="gt-risk-reviewer"))
        self.review(verdict="escalate")
        task = self.state()["tasks"]["one"]
        self.assertEqual(("review", "high", 0), (task["status"], task["risk"], task["changes"]))
        self.assertTrue(taskctl.read_reservation(str(self.repos[0])))
        self.rejected(lambda: self.review(verdict="escalate"))
        self.rejected(self.review)
        self.review(reviewer="gt-risk-reviewer", owner="reviewer-2")
        self.assertEqual("done", self.state()["tasks"]["one"]["status"])
        self.assertIsNone(taskctl.read_reservation(str(self.repos[0])))

    def test_risk_can_only_be_raised_before_acceptance(self):
        self.add()
        self.call("risk", self.run_id, "one", "--evidence", "touches entitlement rules")
        self.rejected(lambda: self.call("risk", self.run_id, "one", "--evidence", "again"))
        self.claim()
        self.finish()
        self.rejected(self.review)
        self.review(reviewer="gt-risk-reviewer")
        self.add("two")
        self.claim("two")
        self.finish("two")
        self.review("two")
        self.rejected(lambda: self.call("risk", self.run_id, "two", "--evidence", "late"))

    def test_usage_carryovers_and_reservations_in_status(self):
        self.add()
        self.add("two", agent="gt-architect")
        self.claim()
        self.call("finish", self.run_id, "one", "--owner", "worker-1", "--evidence", "ok", "--tokens", "1200", "--model", "claude-sonnet-4-5")
        self.assertEqual(self.run_id, self.state()["reservations"][str(self.repos[0])]["run"])
        self.call("review", self.run_id, "one", "--reviewer", "gt-reviewer", "--owner", "r1", "--verdict", "pass",
                  "--evidence", "ok", "--tokens", "800")
        self.claim("two")
        self.call("finish", self.run_id, "two", "--owner", "worker-1", "--evidence", "ok", "--tokens", "5000")
        self.call("review", self.run_id, "two", "--reviewer", "gt-risk-reviewer", "--owner", "r2", "--verdict", "pass",
                  "--evidence", "ok", "--tokens", "3000", "--model", "claude-opus-4-1")
        usage = self.state()["usage"]
        self.assertEqual({"sonnet": 2000, "opus": 8000}, usage["by_model"])
        self.assertEqual(0.8, usage["opus_share"])
        self.assertEqual(4, usage["dispatches"])
        self.call("carry", self.run_id, "--task", "two", "--evidence", "minor: tooltip wording")
        self.call("carry", self.run_id, "--evidence", "runbook gap")
        self.rejected(lambda: self.call("carry", self.run_id, "--task", "missing", "--evidence", "x"))
        self.assertEqual(2, len(self.state()["open_carryovers"]))
        self.call("carry", self.run_id, "--close", "1", "--evidence", "fixed in follow-up task three")
        self.rejected(lambda: self.call("carry", self.run_id, "--close", "1", "--evidence", "twice"))
        self.assertEqual([2], [item["id"] for item in self.state()["open_carryovers"]])
        self.assertIsNone(self.state()["reservations"][str(self.repos[0])])
        self.assertTrue(self.state()["complete"])

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
