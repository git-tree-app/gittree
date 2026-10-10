"""Focused installer and launch-scope tests; no Claude model calls."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('gt_setup', Path(__file__).with_name('setup.py'))
if SPEC is None or SPEC.loader is None:
    raise RuntimeError('Cannot load setup.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class SetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / 'source'
        self.target = self.base / 'target'
        self.target.mkdir()
        global_mock = patch.object(setup, 'global_settings', return_value={})
        global_mock.start()
        self.addCleanup(global_mock.stop)
        assets = {
            '.claude/agents/gt-orchestrator.md': '---\nname: gt-orchestrator\nmodel: sonnet\n---\nCoordinate.\n',
            '.claude/agents/gt-reviewer.md': 'Review carefully.\n',
            '.claude/skills/orchestrate/SKILL.md': 'Use the workflow.\n',
            '.claude/orchestration/WORKFLOW.md': 'A bounded workflow.\n',
            '.claude/orchestration/ROUTING.md': 'Routing rules.\n',
            '.claude/orchestration/repositories.json': '{"repositories": []}\n',
            '.claude/orchestration/setup.py': Path(setup.__file__).read_text(),
        }
        for name, text in assets.items():
            self.write(self.source / name, text)

    def write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def install(self) -> None:
        setup.write_plan(setup.install_plan(self.source, self.target))

    def git_init(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '--quiet', str(path)], check=True, capture_output=True)

    def test_install_is_standalone_and_idempotent(self) -> None:
        self.install()
        self.assertEqual(setup.install_plan(self.source, self.target), {})
        self.assertEqual((self.target / '.claude/agents/gt-reviewer.md').read_text(), 'Review carefully.\n')
        self.assertFalse((self.target / '.claude/agents/gt-reviewer.md').is_symlink())
        settings = json.loads((self.target / '.claude/settings.json').read_text())
        self.assertEqual(settings['agent'], 'gt-orchestrator')
        self.assertIs(settings['ultracode'], False)
        self.assertEqual(settings['env'], setup.BOUNDED_ENV)

    def test_preserves_existing_instructions_settings_and_unknown_files(self) -> None:
        original = {'permissions': {'allow': ['Read']}, 'hooks': {'Stop': []}, 'env': {'CUSTOM_KEY': 'unchanged'}}
        self.write(self.target / '.claude/settings.json', json.dumps(original))
        self.write(self.target / '.claude/settings.local.json', '{"permissions": {"deny": ["Write(secret)"]}}')
        self.write(self.target / 'CLAUDE.md', '# Project instructions\nKeep everything.\n')
        self.write(self.target / '.gitignore', 'node_modules/\n')
        self.write(self.target / '.claude/agents/custom.md', 'My agent')
        local_before = (self.target / '.claude/settings.local.json').read_bytes()
        self.install()
        actual = setup.read_json(self.target / '.claude/settings.json')
        self.assertEqual(actual['permissions'], original['permissions'])
        self.assertEqual(actual['hooks'], original['hooks'])
        self.assertEqual(actual['env']['CUSTOM_KEY'], 'unchanged')
        self.assertEqual((self.target / '.claude/settings.local.json').read_bytes(), local_before)
        self.assertTrue((self.target / 'CLAUDE.md').read_text().startswith('# Project instructions\nKeep everything.\n'))
        self.assertEqual((self.target / '.claude/agents/custom.md').read_text(), 'My agent')
        self.assertEqual((self.target / '.gitignore').read_text().splitlines()[0], 'node_modules/')
        self.assertEqual(setup.install_plan(self.source, self.target), {})

    def test_unmanaged_collision_refuses_before_any_write(self) -> None:
        collision = self.target / '.claude/agents/gt-reviewer.md'
        self.write(collision, 'A custom reviewer')
        with self.assertRaisesRegex(setup.SetupError, 'collision'):
            self.install()
        self.assertFalse((self.target / 'CLAUDE.md').exists())
        self.assertFalse((self.target / '.claude/settings.json').exists())
        self.assertEqual(collision.read_text(), 'A custom reviewer')

    def test_managed_local_edit_refuses_update(self) -> None:
        self.install()
        file = self.target / '.claude/agents/gt-reviewer.md'
        self.write(file, 'Locally edited')
        self.write(self.source / '.claude/agents/gt-reviewer.md', 'Upstream update')
        before = (self.target / setup.MANIFEST_PATH).read_bytes()
        with self.assertRaisesRegex(setup.SetupError, 'Local edit'):
            self.install()
        self.assertEqual(file.read_text(), 'Locally edited')
        self.assertEqual((self.target / setup.MANIFEST_PATH).read_bytes(), before)

    def test_unedited_managed_file_updates(self) -> None:
        self.install()
        self.write(self.source / '.claude/agents/gt-reviewer.md', 'Upstream update')
        self.install()
        self.assertEqual((self.target / '.claude/agents/gt-reviewer.md').read_text(), 'Upstream update')

    def test_conflicting_routing_does_not_partially_install(self) -> None:
        for name in ('settings.json', 'settings.local.json'):
            path = self.target / '.claude' / name
            self.write(path, '{"model": "opus"}')
            with self.assertRaisesRegex(setup.SetupError, 'conflicting model'):
                self.install()
            self.assertFalse((self.target / '.claude/agents').exists())
            path.unlink()

    def test_all_targets_preflight_before_mutation(self) -> None:
        other = self.base / 'other'
        self.write(other / '.claude/agents/gt-reviewer.md', 'Collision')
        with patch.object(setup, 'package_root', return_value=self.source):
            code = setup.main(['install', '--target', str(self.target), '--target', str(other)])
        self.assertEqual(code, 1)
        self.assertFalse((self.target / '.claude').exists())

    def test_symlink_destinations_are_rejected(self) -> None:
        outside = self.base / 'outside'
        outside.mkdir()
        (self.target / '.claude').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, 'symlink'):
            self.install()
        self.assertEqual(list(outside.iterdir()), [])

    def test_scope_defaults_to_single_repo(self) -> None:
        self.git_init(self.target)
        self.git_init(self.base / 'sibling')
        self.assertEqual(setup.resolve_scopes(self.target, None, False), [self.target])
        self.assertEqual(setup.resolve_scopes(self.target, None, True), [self.target])

    def test_container_requires_scope_and_all_expands_immediate_repos(self) -> None:
        self.git_init(self.target / 'one')
        self.git_init(self.target / 'two')
        with self.assertRaisesRegex(setup.SetupError, 'repository container'):
            setup.resolve_scopes(self.target, None, False)
        self.assertEqual(setup.resolve_scopes(self.target, None, True), [self.target / 'one', self.target / 'two'])
        self.assertEqual(setup.resolve_scopes(self.target, ['two'], False), [self.target / 'two'])

    def test_scope_rejects_subdirectories_duplicates_and_combined_flags(self) -> None:
        self.git_init(self.target)
        child = self.target / 'child'
        child.mkdir()
        with self.assertRaisesRegex(setup.SetupError, 'exact Git top-level'):
            setup.resolve_scopes(self.target, ['child'], False)
        alias = self.base / 'alias'
        alias.symlink_to(self.target, target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, 'Duplicate'):
            setup.resolve_scopes(self.target, [str(self.target), str(alias)], False)
        with self.assertRaisesRegex(setup.SetupError, 'cannot be combined'):
            setup.resolve_scopes(self.target, ['.'], True)

    def test_launch_uses_argv_and_resume_scope_guard(self) -> None:
        outside = self.base / 'repo with spaces'
        task = 'Handle "quoted" task; $(touch /tmp/do-not-execute)'
        args = setup.launch_arguments(self.target, [outside], task, 'session-id')
        self.assertEqual(args[:7], ['claude', '--agent', 'gt-orchestrator', '--model', 'sonnet', '--effort', 'medium'])
        self.assertIn('--resume', args)
        self.assertIn('--add-dir', args)
        self.assertIn(str(outside), args)
        self.assertIn('validate the saved ledger scope', args[-1])
        self.assertIn(task, args[-1])

    def test_environment_overrides_are_rejected_without_printing_values(self) -> None:
        for key in setup.ROUTING_OVERRIDES:
            with patch.dict(os.environ, {key: 'private-model-value'}):
                with self.assertRaises(setup.SetupError) as context:
                    setup.runtime_environment(self.target)
                self.assertIn(key, str(context.exception))
                self.assertNotIn('private-model-value', str(context.exception))
        self.write(self.target / '.claude/settings.local.json', json.dumps({'env': {setup.ROUTING_OVERRIDES[0]: 'high'}}))
        with self.assertRaisesRegex(setup.SetupError, setup.ROUTING_OVERRIDES[0]):
            setup.runtime_environment(self.target)

    def test_global_settings_routing_override_is_rejected(self) -> None:
        with patch.object(setup, 'global_settings', return_value={'env': {setup.ROUTING_OVERRIDES[1]: 'private-value'}}):
            with self.assertRaisesRegex(setup.SetupError, setup.ROUTING_OVERRIDES[1]) as context:
                setup.runtime_environment(self.target)
            self.assertNotIn('private-value', str(context.exception))

    def test_fallback_chain_rejected_in_project_and_local_settings(self) -> None:
        for name in ('settings.json', 'settings.local.json'):
            for fallback in (['private-model-name'], 'private-model-name'):
                with self.subTest(name=name, fallback_type=type(fallback).__name__):
                    path = self.target / '.claude' / name
                    self.write(path, json.dumps({'fallbackModel': fallback}))
                    with self.assertRaisesRegex(setup.SetupError, 'fallbackModel') as context:
                        self.install()
                    self.assertNotIn('private-model-name', str(context.exception))
                    self.assertFalse((self.target / '.claude/agents').exists())
                    with self.assertRaisesRegex(setup.SetupError, 'fallbackModel'):
                        setup.runtime_environment(self.target)
                    path.unlink()

    def test_empty_fallback_chain_allowed(self) -> None:
        self.write(self.target / '.claude/settings.json', '{"fallbackModel": []}')
        self.install()
        self.assertEqual(setup.read_json(self.target / '.claude/settings.json')['fallbackModel'], [])

    def test_global_dangerous_routing_blocks_install_and_launch(self) -> None:
        dangerous = [
            ({'fallbackModel': ['private-model-name']}, 'fallbackModel'),
            ({'ultracode': True}, 'ultracode'),
            *[({'env': {key: 'private-model-name'}}, key) for key in setup.ROUTING_OVERRIDES],
        ]
        for settings, key in dangerous:
            with self.subTest(key=key), patch.object(setup, 'global_settings', return_value=settings):
                with self.assertRaisesRegex(setup.SetupError, key) as context:
                    self.install()
                self.assertNotIn('private-model-name', str(context.exception))
                self.assertFalse((self.target / '.claude').exists())
                with self.assertRaisesRegex(setup.SetupError, key):
                    setup.runtime_environment(self.target)

    def test_ultracode_true_is_explicit_conflict(self) -> None:
        for name in ('settings.json', 'settings.local.json'):
            path = self.target / '.claude' / name
            self.write(path, '{"ultracode": true}')
            with self.assertRaisesRegex(setup.SetupError, 'ultracode'):
                self.install()
            self.assertFalse((self.target / '.claude/agents').exists())
            with self.assertRaisesRegex(setup.SetupError, 'ultracode'):
                setup.runtime_environment(self.target)
            path.unlink()

    def test_shell_routing_override_blocks_install_before_writes(self) -> None:
        for key in setup.ROUTING_OVERRIDES:
            with patch.dict(os.environ, {key: 'private-value'}):
                with self.assertRaisesRegex(setup.SetupError, key):
                    self.install()
                self.assertFalse((self.target / '.claude').exists())

    def test_installed_launcher_survives_source_removal(self) -> None:
        self.install()
        self.git_init(self.target)
        self.source.rename(self.base / 'source-moved')
        environment = {key: value for key, value in os.environ.items() if key not in setup.ROUTING_OVERRIDES}
        environment['CLAUDE_CONFIG_DIR'] = str(self.base / 'empty-global-config')
        result = subprocess.run([sys.executable, str(self.target / '.claude/orchestration/setup.py'), 'launch', '--dry-run', 'Fix a bug'],
                                cwd=self.base, env=environment, capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        self.assertEqual(output['cwd'], str(self.target))
        self.assertEqual(output['scopes'], [str(self.target)])
        self.assertNotIn('source-moved', result.stdout)

    def test_cli_version_gate_makes_no_model_request(self) -> None:
        with patch.object(setup.shutil, 'which', return_value='/fake/claude'):
            with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '2.1.284 (Claude Code)\n', '')) as run:
                self.assertEqual(setup.claude_version()[1], (2, 1, 284))
                self.assertEqual(run.call_args.args[0], ['/fake/claude', '--version'])
            with patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '2.1.283\n', '')):
                with self.assertRaisesRegex(setup.SetupError, 'required'):
                    setup.claude_version()


if __name__ == '__main__':
    unittest.main()
