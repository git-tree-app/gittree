import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from extensions import extension_plan, GRAPH_TOOLS, validate_marketplace
from setup import SetupError, write_plan


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        settings = patch("extensions.global_settings", return_value={})
        settings.start()
        self.addCleanup(settings.stop)

    def test_merge_idempotence_and_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"existing": {"command": "test"}}}))
            (root / ".claude").mkdir()
            (root / ".claude/settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(rm *)"]}}))
            plan = extension_plan(root)
            write_plan(plan)
            self.assertEqual(plan, extension_plan(root))
            self.assertIn("existing", json.loads((root / ".mcp.json").read_text())["mcpServers"])
            self.assertEqual(json.loads((root / ".claude/settings.json").read_text())["permissions"]["deny"], ["Bash(rm *)"])

    def test_conflicting_server_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = '{"mcpServers":{"code-review-graph":{"command":"custom"}}}'
            (root / ".mcp.json").write_text(value)
            with self.assertRaises(SetupError):
                extension_plan(root)
            self.assertEqual((root / ".mcp.json").read_text(), value)

    def test_graph_tool_surface_excludes_mutations_and_egress(self):
        self.assertEqual(len(GRAPH_TOOLS), 6)
        self.assertFalse(set(GRAPH_TOOLS) & {"apply_refactor_tool", "embed_graph_tool", "generate_wiki_tool"})

    def test_marketplace_name_collision_is_rejected(self):
        with self.assertRaises(SetupError):
            validate_marketplace([{"name": "caveman", "source": "github", "repo": "someone/else"}])
        self.assertTrue(validate_marketplace([{"name": "caveman", "source": "github", "repo": "JuliusBrussee/caveman"}]))

    def test_local_disables_rejected_before_writes_and_preserved(self):
        for value, message in (
            ({"disabledMcpjsonServers": ["code-review-graph"]}, "code-review-graph"),
            ({"enabledPlugins": {"caveman@caveman": False}}, "Caveman"),
        ):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".claude").mkdir()
                local = root / ".claude/settings.local.json"
                local.write_text(json.dumps(value))
                before = local.read_bytes()
                with self.assertRaisesRegex(SetupError, f"settings.local.json.*{message}.*disabled"):
                    write_plan(extension_plan(root))
                self.assertEqual(local.read_bytes(), before)
                self.assertFalse((root / ".mcp.json").exists())
                self.assertFalse((root / ".claude/settings.json").exists())

    def test_global_mcp_disable_is_not_erased_by_project_enablement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("extensions.global_settings", return_value={"disabledMcpjsonServers": ["code-review-graph"]}):
                with self.assertRaisesRegex(SetupError, "Global Claude settings.*code-review-graph.*disabled"):
                    write_plan(extension_plan(root))
            self.assertEqual(list(root.iterdir()), [])

    def test_project_plugin_enablement_overrides_global_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("extensions.global_settings", return_value={"enabledPlugins": {"caveman@caveman": False}}):
                plan = extension_plan(root)
            settings = json.loads(plan[root / ".claude/settings.json"])
            self.assertIs(settings["enabledPlugins"]["caveman@caveman"], True)

    def test_unrelated_local_preferences_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".claude").mkdir()
            local = root / ".claude/settings.local.json"
            local.write_text('{"enabledPlugins":{"other@other":false},"disabledMcpjsonServers":["other"]}')
            before = local.read_bytes()
            write_plan(extension_plan(root))
            self.assertEqual(local.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
