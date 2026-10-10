#!/usr/bin/env python3
"""Configure the requested Claude extensions in each selected project.

Uses native installers; never configures a proxy, embeddings or background daemon.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from setup import SetupError, check_safe_path, global_settings, read_json, write_plan, json_bytes

GRAPH_VERSION = "2.3.9"
GRAPH_TOOLS = (
    "get_minimal_context_tool", "get_impact_radius_tool", "get_review_context_tool",
    "query_graph_tool", "detect_changes_tool", "list_graph_stats_tool",
)
GRAPH_CONFIG = {
    "command": "uvx",
    "args": ["--from", f"code-review-graph=={GRAPH_VERSION}", "code-review-graph",
             "serve", "--tools", ",".join(GRAPH_TOOLS)],
    "env": {"CRG_TOOL_TIMEOUT": "30"},
}


def validate_marketplace(markets: list[dict]) -> bool:
    """A matching name is insufficient: verify the repository before installing code."""
    matches = [item for item in markets if item.get("name") == "caveman"]
    if any(item.get("source") != "github" or item.get("repo", "").lower() != "juliusbrussee/caveman" for item in matches):
        raise SetupError("The registered caveman marketplace points to a different source; reconcile it before installing")
    return bool(matches)


def extension_plan(root: Path) -> dict[Path, bytes]:
    """Merge only the requested extension settings, refusing conflicting installs."""
    paths = {name: root / name for name in (".mcp.json", ".caveman.json", ".claude/settings.json", ".gitignore")}
    for path in paths.values():
        check_safe_path(root, path)
    local_path = root / ".claude/settings.local.json"
    check_safe_path(root, local_path)
    settings = read_json(paths[".claude/settings.json"])
    local_settings = read_json(local_path)
    # Native settings merge arrays across scopes. A global MCP disable therefore
    # survives project enablement, while a global plugin false is overridden by
    # the project's true. Local plugin false has higher priority than the project.
    for name, configuration, check_plugin in (
        ("Global Claude settings", global_settings(), False),
        (str(paths[".claude/settings.json"]), settings, True),
        (str(local_path), local_settings, True),
    ):
        disabled = configuration.get("disabledMcpjsonServers", [])
        if not isinstance(disabled, list):
            raise SetupError(f"{name}: disabledMcpjsonServers must be a JSON array")
        if "code-review-graph" in disabled:
            raise SetupError(f"{name}: code-review-graph is explicitly disabled; reconcile before installing")
        if check_plugin:
            plugins = configuration.get("enabledPlugins", {})
            if not isinstance(plugins, dict):
                raise SetupError(f"{name}: enabledPlugins must be a JSON object")
            if plugins.get("caveman@caveman") is False:
                raise SetupError(f"{name}: Caveman is explicitly disabled; reconcile before installing")
    mcp = read_json(paths[".mcp.json"])
    servers = mcp.setdefault("mcpServers", {})
    if "code-review-graph" in servers and servers["code-review-graph"] != GRAPH_CONFIG:
        raise SetupError(f"Existing code-review-graph configuration differs in {root}; reconcile it before installing")
    servers["code-review-graph"] = GRAPH_CONFIG
    caveman = read_json(paths[".caveman.json"])
    if caveman.get("defaultMode", "lite") != "lite":
        raise SetupError(f"Existing Caveman mode differs in {root}; reconcile it before installing")
    caveman["defaultMode"] = "lite"
    settings.setdefault("enabledPlugins", {})["caveman@caveman"] = True
    marketplace = {"source": {"source": "github", "repo": "JuliusBrussee/caveman"}, "autoUpdate": False}
    known = settings.setdefault("extraKnownMarketplaces", {})
    if "caveman" in known and known["caveman"] != marketplace:
        raise SetupError(f"Existing Caveman marketplace differs in {root}; reconcile before installing")
    known["caveman"] = marketplace
    approved = settings.setdefault("enabledMcpjsonServers", [])
    if "code-review-graph" not in approved:
        approved.append("code-review-graph")
    ignore = paths[".gitignore"].read_text() if paths[".gitignore"].exists() else ""
    if ".code-review-graph/" not in ignore.splitlines():
        ignore += ("\n" if ignore and not ignore.endswith("\n") else "") + ".code-review-graph/\n"
    return {paths[".mcp.json"]: json_bytes(mcp), paths[".caveman.json"]: json_bytes(caveman),
            paths[".claude/settings.json"]: json_bytes(settings), paths[".gitignore"]: ignore.encode()}


def command(argv: list[str], cwd: Path) -> None:
    subprocess.run(argv, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "check", "build", "update", "status"))
    parser.add_argument("--target", action="append", help="Project root; repeatable, defaults to package root")
    args = parser.parse_args()
    targets = [Path(p).expanduser().resolve() for p in args.target] if args.target else [Path(__file__).resolve().parents[2]]
    try:
        for target in targets:
            if not target.is_dir():
                raise SetupError(f"Missing project: {target}")
        if args.action in ("install", "check"):
            plans = [(root, extension_plan(root)) for root in targets]
            if args.action == "check":
                drift = False
                for root, plan in plans:
                    different = [str(p.relative_to(root)) for p, content in plan.items() if not p.exists() or p.read_bytes() != content]
                    print(f"{root.name}: {'configuration current' if not different else 'differs: ' + ', '.join(different)}")
                    drift |= bool(different)
                return int(drift)
            if not shutil.which("claude") or not shutil.which("uvx"):
                raise SetupError("Claude Code and uv/uvx are required")
            if not shutil.which("code-review-graph"):
                command(["uv", "tool", "install", f"code-review-graph=={GRAPH_VERSION}"], targets[0])
            version = subprocess.check_output(["code-review-graph", "--version"], text=True).strip()
            if version.split()[-1].lstrip("v") != GRAPH_VERSION:
                raise SetupError(f"Expected code-review-graph {GRAPH_VERSION}; reconcile the installed version first")
            markets = json.loads(subprocess.check_output(["claude", "plugin", "marketplace", "list", "--json"], text=True))
            if not validate_marketplace(markets):
                command(["claude", "plugin", "marketplace", "add", "JuliusBrussee/caveman"], targets[0])
            for root, plan in plans:
                print(f"Installing requested extensions: {root}", flush=True)
                # Native plugin installer maintains Claude's installation registry.
                command(["claude", "plugin", "install", "caveman@caveman", "--scope", "project"], root)
                # Re-read settings after native installer so unrelated keys it adds survive.
                plan = extension_plan(root)
                write_plan({path: value for path, value in plan.items() if not path.exists() or path.read_bytes() != value})
            return 0
        for root in targets:
            detected = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True).strip()
            if Path(detected).resolve() != root:
                raise SetupError(f"Graph operations require an exact Git root: {root}")
        for root in targets:
            print(f"Graph {args.action}: {root}", flush=True)
            argv = ["code-review-graph", args.action, "--repo", str(root)]
            if args.action == "status":
                argv.append("--json")
            command(argv, root)
        return 0
    except (SetupError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Extension setup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
