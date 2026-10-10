"""Routing contract checks for the installed native Claude profiles."""
from pathlib import Path
import unittest

import taskctl


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parents[1] / "agents"
        self.profiles = {}
        for path in self.directory.glob("gt-*.md"):
            frontmatter = path.read_text().split("---", 2)[1]
            self.profiles[path.stem] = dict(line.split(": ", 1) for line in frontmatter.strip().splitlines())

    def test_dispatch_and_ledger_roles_agree(self):
        self.assertEqual(set(self.profiles), set(taskctl.AGENTS) | {"gt-orchestrator"})
        for name, profile in self.profiles.items():
            self.assertEqual(name, profile["name"])
            self.assertIn(profile["model"], ("sonnet", "opus", "haiku"))

    def test_workers_cannot_dispatch_and_reviewers_cannot_mutate(self):
        for name in taskctl.AGENTS:
            profile = self.profiles[name]
            tools = {item.strip() for item in profile["tools"].split(",")}
            self.assertFalse(tools & {"Agent", "SendMessage", "Skill"})
            self.assertLessEqual(int(profile["maxTurns"]), 32)
        for name in taskctl.REVIEWERS:
            self.assertEqual(self.profiles[name]["tools"], "Read, Grep, Glob")
            self.assertNotIn("memory", self.profiles[name])

    def test_priority_model_routes(self):
        for name in ("gt-desktop", "gt-architect", "gt-risk-reviewer"):
            self.assertEqual(self.profiles[name]["model"], "opus")
        self.assertEqual(self.profiles["gt-test-manager"]["model"], "sonnet")
        self.assertEqual(self.profiles["gt-scout"]["model"], "haiku")

    def test_main_preserves_connected_tools(self):
        self.assertNotIn("tools", self.profiles["gt-orchestrator"])


if __name__ == "__main__":
    unittest.main()
