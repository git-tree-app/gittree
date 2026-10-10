#!/usr/bin/env python3
"""Install and launch GitTree's portable Claude orchestration configuration.

Uses only Python's standard library. Installation is collision-checked before
writing; it does not overwrite independently edited managed files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


MIN_CLAUDE_VERSION = (2, 1, 284)
MANIFEST_PATH = Path('.claude/orchestration/install-manifest.json')
DEFAULT_SETTINGS = {
    'agent': 'gt-orchestrator',
    'model': 'sonnet',
    'effortLevel': 'medium',
    'ultracode': False,
}
BOUNDED_ENV = {
    'CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH': '1',
    'CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS': '2',
}
ROUTING_OVERRIDES = ('CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_SUBAGENT_MODEL_FORCE')
ALIAS_ENV = (
    'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL',
    'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_MODEL',
)
RETRY_ENV = ('FALLBACK_FOR_ALL_PRIMARY_MODELS',)
BLOCK_START = '<!-- gittree-orchestration:start -->'
BLOCK_END = '<!-- gittree-orchestration:end -->'
CLAUDE_BLOCK = f'''{BLOCK_START}
## GitTree orchestration

All implementation tasks follow [.claude/orchestration/WORKFLOW.md](.claude/orchestration/WORKFLOW.md).
Use `/orchestrate` for the complete workflow. Routing is defined in
[.claude/orchestration/ROUTING.md](.claude/orchestration/ROUTING.md).
In a single Git repository, scope defaults to that repository only. Expand scope
only when explicitly requested. Simple questions and explanations do not spawn subagents.
{BLOCK_END}'''
IGNORE_LINES = ('.claude/task-runs/', '.claude/orchestration/__pycache__/')


class SetupError(Exception):
    """An actionable configuration or validation failure."""


def package_root() -> Path:
    """Return the project containing this standalone orchestration package."""
    return Path(__file__).resolve().parents[2]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise SetupError(f'Invalid JSON in {path}: {error}') from error
    if not isinstance(value, dict):
        raise SetupError(f'Expected a JSON object in {path}')
    return value


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()


def source_files(source: Path) -> dict[Path, bytes]:
    """Collect only this package's managed assets, never user configuration."""
    files = list((source / '.claude/agents').glob('gt-*.md'))
    skill = source / '.claude/skills/orchestrate'
    if skill.exists():
        files += [path for path in skill.rglob('*') if path.is_file()]
    directory = source / '.claude/orchestration'
    files += list(directory.glob('*.md')) + list(directory.glob('*.py'))
    if (directory / 'repositories.json').is_file():
        files.append(directory / 'repositories.json')
    if not (source / '.claude/agents/gt-orchestrator.md').is_file():
        raise SetupError('Source package is incomplete: missing gt-orchestrator.md')
    if not (skill / 'SKILL.md').is_file():
        raise SetupError('Source package is incomplete: missing orchestrate/SKILL.md')
    return {path.relative_to(source): path.read_bytes() for path in sorted(set(files))}


def check_safe_path(root: Path, path: Path) -> None:
    """Refuse writing through symlinks, including symlinked parent directories."""
    for candidate in (path, *path.parents):
        if candidate == root:
            break
        if candidate.is_symlink():
            raise SetupError(f'Refusing managed destination through symlink: {candidate}')
    if path.exists() and not path.is_file():
        raise SetupError(f'Expected a file at {path}')


def settings_env(settings: dict, name: str) -> dict:
    value = settings.get('env', {})
    if not isinstance(value, dict):
        raise SetupError(f'{name}: env must be a JSON object')
    return value


def validate_routing(settings: dict, name: str) -> None:
    for key, expected in DEFAULT_SETTINGS.items():
        if key in settings and settings[key] != expected:
            raise SetupError(f'{name}: conflicting {key}; expected {expected!r}. Resolve explicitly before installing or launching.')
    validate_routing_overrides(settings, name)
    environment = settings_env(settings, name)
    for key, expected in BOUNDED_ENV.items():
        if key in environment and str(environment[key]) != expected:
            raise SetupError(f'{name}: conflicting {key}; expected {expected!r}.')


def validate_routing_overrides(settings: dict, name: str) -> None:
    """Reject routing changes that can bypass a worker's assigned model or effort."""
    if settings.get('fallbackModel'):
        raise SetupError(f'{name}: fallbackModel permits automatic model substitution; remove it explicitly before installing or launching.')
    if settings.get('ultracode'):
        raise SetupError(f'{name}: ultracode must be false for this bounded orchestration workflow; disable it explicitly.')
    environment = settings_env(settings, name)
    for key in ROUTING_OVERRIDES:
        if environment.get(key):
            raise SetupError(f'{name}: {key} overrides per-agent routing; remove it explicitly.')


def validate_inherited_routing() -> None:
    """Check inherited configuration before installing or starting a session."""
    for key in ROUTING_OVERRIDES:
        if os.environ.get(key):
            raise SetupError(f'Environment contains {key}; it overrides per-agent routing. Remove it explicitly before installing or launching.')
    validate_routing_overrides(global_settings(), 'Global Claude settings')


def marked_claude(existing: str) -> str:
    start_count, end_count = existing.count(BLOCK_START), existing.count(BLOCK_END)
    if start_count != end_count or start_count > 1:
        raise SetupError('CLAUDE.md has malformed or duplicate orchestration markers')
    if start_count:
        start, end = existing.index(BLOCK_START), existing.index(BLOCK_END)
        if end < start:
            raise SetupError('CLAUDE.md orchestration markers are out of order')
        return existing[:start] + CLAUDE_BLOCK + existing[end + len(BLOCK_END):]
    return existing + ('\n' if existing.endswith('\n') else '\n\n' if existing else '') + CLAUDE_BLOCK + '\n'


def install_plan(source: Path, target: Path) -> dict[Path, bytes]:
    """Preflight all destination files before returning a mutation plan."""
    validate_inherited_routing()
    if not target.is_dir():
        raise SetupError(f'Target directory does not exist: {target}')
    manifest_file = target / MANIFEST_PATH
    check_safe_path(target, manifest_file)
    manifest = read_json(manifest_file)
    previous = manifest.get('files', {})
    if not isinstance(previous, dict):
        raise SetupError(f'Invalid files map in {manifest_file}')
    assets = source_files(source)
    plan: dict[Path, bytes] = {}
    for relative, data in assets.items():
        destination = target / relative
        check_safe_path(target, destination)
        if destination.exists():
            current = destination.read_bytes()
            if current != data and digest(current) != previous.get(str(relative)):
                raise SetupError(f'Local edit or unmanaged collision: {destination}. Preserve or reconcile it before installing.')
        plan[destination] = data
    settings_path = target / '.claude/settings.json'
    local_settings_path = target / '.claude/settings.local.json'
    for path in (settings_path, local_settings_path):
        check_safe_path(target, path)
        validate_routing(read_json(path), str(path))
    settings = read_json(settings_path)
    settings.update(DEFAULT_SETTINGS)
    settings['env'] = {**settings_env(settings, str(settings_path)), **BOUNDED_ENV}
    plan[settings_path] = json_bytes(settings)
    claude_path = target / 'CLAUDE.md'
    ignore_path = target / '.gitignore'
    for path in (claude_path, ignore_path):
        check_safe_path(target, path)
    existing_claude = claude_path.read_text() if claude_path.exists() else ''
    plan[claude_path] = marked_claude(existing_claude).encode()
    existing_ignore = ignore_path.read_text() if ignore_path.exists() else ''
    missing = [line for line in IGNORE_LINES if line not in existing_ignore.splitlines()]
    if missing:
        existing_ignore += ('' if not existing_ignore or existing_ignore.endswith('\n') else '\n')
        existing_ignore += '\n'.join(missing) + '\n'
    plan[ignore_path] = existing_ignore.encode()
    plan[manifest_file] = json_bytes({'schema_version': 1, 'files': {str(path): digest(data) for path, data in assets.items()}})
    return {path: data for path, data in plan.items() if not path.exists() or path.read_bytes() != data}


def write_plan(plan: dict[Path, bytes]) -> None:
    """Write already preflighted files atomically, one file at a time."""
    for path, data in plan.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def git_root(path: Path) -> Path | None:
    try:
        result = subprocess.run(['git', '-C', str(path), 'rev-parse', '--show-toplevel'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def resolve_scopes(root: Path, repositories: list[str] | None, all_repositories: bool) -> list[Path]:
    """Resolve explicit Git roots; a standalone install never discovers siblings."""
    if repositories and all_repositories:
        raise SetupError('--all and --repo cannot be combined')
    if repositories:
        scopes = [(root / item).resolve() for item in repositories]
    elif git_root(root) == root:
        scopes = [root]
    elif all_repositories:
        scopes = sorted(path.resolve() for path in root.iterdir() if path.is_dir() and git_root(path) == path.resolve())
        if not scopes:
            raise SetupError(f'No immediate Git repositories found in {root}')
    else:
        raise SetupError('This project is a repository container. Choose --repo PATH (repeatable) or --all explicitly.')
    if len(set(scopes)) != len(scopes):
        raise SetupError('Duplicate repository paths, including aliases, are not allowed')
    for path in scopes:
        if not path.is_dir() or git_root(path) != path:
            raise SetupError(f'--repo must name an exact Git top-level directory: {path}')
    return scopes


def runtime_environment(root: Path) -> dict[str, str]:
    validate_inherited_routing()
    for name in ('settings.json', 'settings.local.json'):
        path = root / '.claude' / name
        validate_routing(read_json(path), str(path))
    return {**os.environ, **BOUNDED_ENV}


def global_settings() -> dict:
    """Read user settings only to identify environment overrides, never mutate them."""
    directory = Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home() / '.claude'))).expanduser()
    return read_json(directory / 'settings.json')


def claude_version() -> tuple[str, tuple[int, int, int]]:
    executable = shutil.which('claude')
    if executable is None:
        raise SetupError('Claude Code is not on PATH. Install or update Claude Code before launching.')
    try:
        result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError(f'Could not read Claude Code version: {type(error).__name__}') from error
    match = re.search(r'\b(\d+)\.(\d+)\.(\d+)\b', result.stdout)
    if result.returncode or not match:
        raise SetupError('Could not parse claude --version')
    version = tuple(int(part) for part in match.groups())
    if version < MIN_CLAUDE_VERSION:
        raise SetupError(f'Claude Code {".".join(map(str, MIN_CLAUDE_VERSION))}+ is required; found {".".join(map(str, version))}.')
    return executable, version


def launch_arguments(root: Path, scopes: list[Path], task: str, resume: str | None) -> list[str]:
    prompt = (
        'Follow .claude/orchestration/WORKFLOW.md and use the orchestrate skill.\n'
        'Authorized repository scope (exact Git roots; do not expand without user approval):\n'
        + '\n'.join(f'- {path}' for path in scopes)
        + '\nRecord this scope in the task ledger before delegating.'
    )
    if resume:
        prompt += '\nBefore resuming, validate the saved ledger scope against these exact roots. If it differs, stop and ask the user; never silently expand or replace saved scope. Reconcile running attempts against repository evidence before new work.'
    if task:
        prompt += '\n\nUser task:\n' + task
    else:
        prompt += '\nAsk the user for the task if no unfinished authorized task is present.'
    arguments = ['claude', '--agent', 'gt-orchestrator', '--model', 'sonnet', '--effort', 'medium']
    if resume:
        arguments += ['--resume', resume]
    for path in scopes:
        if path != root and root not in path.parents:
            arguments += ['--add-dir', str(path)]
    return arguments + [prompt]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('install', 'check'):
        command = commands.add_parser(name)
        command.add_argument('--target', action='append', help='Project root (repeatable); defaults to this package root')
    commands.add_parser('doctor', help='Inspect configuration and CLI version without a model request')
    launch = commands.add_parser('launch')
    group = launch.add_mutually_exclusive_group()
    group.add_argument('--repo', action='append')
    group.add_argument('--all', action='store_true', dest='all_repositories')
    launch.add_argument('--resume', metavar='SESSION')
    launch.add_argument('--dry-run', action='store_true')
    launch.add_argument('task', nargs='*')
    options = parser.parse_args(argv)
    root = package_root()
    try:
        if options.command in ('install', 'check'):
            targets = [Path(value).expanduser().resolve() for value in options.target] if options.target else [root]
            if len(set(targets)) != len(targets):
                raise SetupError('Duplicate installation targets')
            # Preflight every target before any mutation, including root settings.
            plans = [(target, install_plan(root, target)) for target in targets]
            for target, plan in plans:
                if options.command == 'install':
                    write_plan(plan)
                    print(f'Installed: {target} ({len(plan)} files changed)')
                else:
                    print(f'{"Needs install/update" if plan else "Current"}: {target} ({len(plan)} files differ)')
            return int(options.command == 'check' and any(plan for _, plan in plans))
        environment = runtime_environment(root)
        source_files(root)  # Validate the portable package before doctor or launch.
        if options.command == 'doctor':
            executable, version = claude_version()
            print(f'Claude Code {".".join(map(str, version))}: {executable}')
            print(f'Package root: {root}')
            print('Coordinator: gt-orchestrator / sonnet / medium; depth 1; concurrency 2')
            aliases = [key for key in ALIAS_ENV if environment.get(key)]
            aliases += [key for key in ALIAS_ENV if settings_env(global_settings(), 'global Claude settings').get(key)]
            for name in ('settings.json', 'settings.local.json'):
                aliases += [key for key in ALIAS_ENV if settings_env(read_json(root / '.claude' / name), name).get(key)]
            print('Configured model alias environment keys: ' + (', '.join(sorted(set(aliases))) or 'none'))
            retry_keys = [key for key in RETRY_ENV if environment.get(key)]
            configurations = [global_settings()] + [read_json(root / '.claude' / name) for name in ('settings.json', 'settings.local.json')]
            for configuration in configurations:
                retry_keys += [key for key in RETRY_ENV if settings_env(configuration, 'Claude settings').get(key)]
            print('Configured retry behavior environment keys: ' + (', '.join(sorted(set(retry_keys))) or 'none'))
            print('Automatic fallback chains: none configured in inspected settings; ultracode: disabled')
            print('Version/configuration checks only; no authentication, model availability, or paid request tested.')
            return 0
        scopes = resolve_scopes(root, options.repo, options.all_repositories)
        arguments = launch_arguments(root, scopes, ' '.join(options.task), options.resume)
        if options.dry_run:
            print(json.dumps({'cwd': str(root), 'scopes': [str(path) for path in scopes], 'argv': arguments,
                              'note': 'No Claude process or model request started; run doctor for CLI validation.'}, indent=2))
            return 0
        executable, _ = claude_version()
        arguments[0] = executable
        os.chdir(root)
        os.execvpe(executable, arguments, environment)
        return 0
    except (SetupError, OSError, UnicodeError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
