"""Integration gates bind multi-repository milestones without approval laundering."""
import unittest

import test_taskctl as fixtures


taskctl = fixtures.taskctl


class IntegrationTests(unittest.TestCase):
    setUp = fixtures.LedgerTests.setUp
    call = fixtures.LedgerTests.call
    state = fixtures.LedgerTests.state
    add = fixtures.LedgerTests.add
    claim = fixtures.LedgerTests.claim
    finish = fixtures.LedgerTests.finish
    review = fixtures.LedgerTests.review
    rejected = fixtures.LedgerTests.rejected

    def accept(self, key, repo=0, depends=(), content=None):
        self.add(key, repo=repo, depends=depends)
        self.claim(key)
        if content is not None:
            (self.repos[repo] / 'source.txt').write_text(content)
        self.finish(key)
        self.review(key)

    def roundtrip(self, prefix='m1'):
        self.accept(prefix + '-a', content=prefix + ' producer')
        self.accept(prefix + '-b', repo=1, depends=[prefix + '-a'], content=prefix + ' consumer')
        self.accept(prefix + '-a2', depends=[prefix + '-b'], content=prefix + ' integrated producer')

    def gate(self, key='gate', **overrides):
        args = ['add', self.run_id, '--id', key, '--title', 'Verify complete integration',
                '--repo', str(self.repos[0]), '--agent', overrides.get('agent', 'gt-test-manager'),
                '--accept', 'Cross-repository flows and all applicable suites pass', '--integration']
        if 'risk' in overrides:
            args.extend(['--risk', overrides['risk']])
        return self.call(*args)

    def pass_gate(self, key='gate'):
        self.gate(key)
        self.claim(key)
        self.finish(key)
        self.review(key, reviewer='gt-risk-reviewer')

    def test_roundtrip_requires_explicit_final_integration(self):
        self.roundtrip()
        self.assertFalse(self.state()['complete'])
        self.pass_gate()
        self.assertTrue(self.state()['complete'])
        gate = self.state()['tasks']['gate']
        self.assertEqual(set(gate['integration_snapshots']), set(map(str, self.repos)))
        self.assertEqual(set(gate['depends']), {'m1-a', 'm1-b', 'm1-a2'})

    def test_multiple_milestones_use_fresh_gate_after_new_work(self):
        self.roundtrip()
        self.pass_gate('gate1')
        self.roundtrip('m2')
        self.assertFalse(self.state()['complete'])
        self.pass_gate('gate2')
        self.assertTrue(self.state()['complete'])

    def test_added_noop_task_is_not_covered_by_previous_gate(self):
        self.accept('one')
        self.pass_gate()
        self.accept('later')
        self.assertFalse(self.state()['complete'])
        self.assertEqual([], self.state()['stale_repositories'])
        self.pass_gate('fresh')
        self.assertTrue(self.state()['complete'])

    def test_gate_requires_all_other_tasks_done_and_preserves_role_boundaries(self):
        self.add('unfinished')
        self.gate()
        self.rejected(lambda: self.claim('gate'))
        self.rejected(lambda: self.gate('bad-agent', agent='gt-implementer'))
        self.rejected(lambda: self.gate('low-risk', risk='low'))
        self.claim('unfinished')
        self.finish('unfinished')
        self.review('unfinished')
        self.claim('gate')
        self.rejected(lambda: self.add('during-gate'))
        self.finish('gate')
        self.rejected(lambda: self.review('gate'))
        self.rejected(lambda: self.review('gate', owner='worker-1', reviewer='gt-risk-reviewer'))
        self.review('gate', reviewer='gt-risk-reviewer')

    def test_source_mutation_is_rejected_at_finish_review_and_completion(self):
        self.accept('one')
        self.gate()
        self.claim('gate')
        original = (self.repos[0] / 'source.txt').read_text()
        (self.repos[0] / 'source.txt').write_text('gate must not implement')
        self.rejected(lambda: self.finish('gate'))
        (self.repos[0] / 'source.txt').write_text(original)
        self.finish('gate')
        original_other = (self.repos[2] / 'source.txt').read_text()
        (self.repos[2] / 'source.txt').write_text('other checkout changed')
        self.rejected(lambda: self.review('gate', reviewer='gt-risk-reviewer'))
        (self.repos[2] / 'source.txt').write_text(original_other)
        self.review('gate', reviewer='gt-risk-reviewer')
        self.assertTrue(self.state()['complete'])
        (self.repos[2] / 'source.txt').write_text('post-review edit')
        self.assertFalse(self.state()['complete'])
        self.assertEqual([str(self.repos[2])], self.state()['stale_repositories'])

    def test_gate_admission_does_not_absorb_unreviewed_source_edits(self):
        self.accept('one')
        (self.repos[0] / 'source.txt').write_text('unreviewed change')
        self.gate()
        self.rejected(lambda: self.claim('gate'))

    def other_call(self, *args):
        return taskctl.run(taskctl.parser().parse_args(['--root', str(self.root / 'other'), *args]))

    def other_task(self, repo):
        run = self.other_call('init', '--goal', 'Other coordinator', '--repo', repo)['run']
        self.other_call('add', run, '--id', 'other', '--title', 'Other work', '--agent', 'gt-implementer',
                        '--repo', repo, '--accept', 'Checks pass')
        return run

    def test_partial_acquire_rolls_back_only_new_reservations(self):
        repos = sorted(map(str, self.repos))
        other = self.other_task(repos[1])
        self.other_call('claim', other, 'other', '--owner', 'other-worker')
        self.gate()
        self.rejected(lambda: self.claim('gate'))
        identity = {'root': str(self.root), 'run': self.run_id, 'task': 'gate'}
        self.assertFalse(taskctl.reservation(repos[0], 'inspect', identity))
        other_identity = {'root': str(self.root / 'other'), 'run': other, 'task': 'other'}
        self.assertTrue(taskctl.reservation(repos[1], 'inspect', other_identity))
        self.assertEqual(0, self.state()['tasks']['gate']['claims'])

    def test_gate_reserves_every_checkout_and_recovery_releases_them(self):
        self.gate()
        self.claim('gate')
        for repo in map(str, self.repos):
            other = self.other_task(repo)
            with self.assertRaises(taskctl.WorkflowError):
                self.other_call('claim', other, 'other', '--owner', 'other-worker')
        self.call('recover', self.run_id, 'gate', '--workers-stopped', '--evidence', 'All integration workers stopped')
        identity = {'root': str(self.root), 'run': self.run_id, 'task': 'gate'}
        for repo in map(str, self.repos):
            self.assertFalse(taskctl.reservation(repo, 'inspect', identity))
        self.call('resume', self.run_id, 'gate', '--workers-stopped', '--evidence', 'Restart tests')
        self.claim('gate')
        self.finish('gate')
        self.review('gate', reviewer='gt-risk-reviewer')
        self.assertTrue(self.state()['complete'])

    def test_failed_gate_allows_fix_then_revalidation_without_deadlock(self):
        self.accept('one')
        self.gate()
        self.claim('gate')
        self.finish('gate')
        self.review('gate', verdict='changes', reviewer='gt-risk-reviewer')
        self.accept('repair', content='Fix discovered by integration tests')
        self.claim('gate')
        self.finish('gate')
        self.review('gate', reviewer='gt-risk-reviewer')
        self.assertTrue(self.state()['complete'])
        self.assertIn('repair', self.state()['tasks']['gate']['depends'])
        self.assertEqual(2, self.state()['tasks']['gate']['claims'])
        self.assertEqual(1, self.state()['tasks']['gate']['changes'])

    def test_changed_covered_approval_revokes_integration_evidence(self):
        self.roundtrip()
        self.pass_gate()
        path = self.root / '.claude' / 'task-runs' / self.run_id / 'state.json'
        state = self.state()
        state['tasks']['m1-a']['approval']['evidence'] = 'Different acceptance revision'
        taskctl.save(path, state)
        self.assertFalse(self.state()['complete'])


if __name__ == '__main__':
    unittest.main()
