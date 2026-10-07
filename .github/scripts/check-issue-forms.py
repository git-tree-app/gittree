#!/usr/bin/env python3
"""The issue forms keep what the app and GitHub rely on.

- Every label a form names exists in this repository (GitHub silently drops
  an unknown one): `labels.txt` lists them, and with GH_TOKEN set the live
  labels are checked too.
- The field ids the app prefills (`?version=…&os-version=…`) exist, with the
  meaning the app gives them. The app's own lists are BUG_ISSUE_PARAMS and
  CRASH_ISSUE_PARAMS in the source repository's `features/about/model`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FORMS = ROOT / ".github/ISSUE_TEMPLATE"

# Field id -> what the app puts there.
PREFILLED = {
    "bug_report.yml": {
        "version": "input",  # v1.2.3
        "os-version": "input",  # macOS 15.3 / Windows 11 24H2 (build 26100) / Ubuntu 24.04.1 LTS
        "git-version": "input",  # git version 2.47.1
    },
    "crash_report.yml": {
        "version": "input",  # 1.2.3
        "os-version": "input",
        "git-version": "input",
        "crash-id": "input",  # crash-1790690000.txt
    },
}


def main() -> int:
    known = set((ROOT / ".github/labels.txt").read_text("utf-8").split())
    problems: list[str] = []
    named: set[str] = set()
    for form in sorted(FORMS.glob("*.yml")):
        if form.name == "config.yml":
            continue
        data = yaml.safe_load(form.read_text("utf-8"))
        labels = set(data.get("labels") or [])
        named |= labels
        for label in sorted(labels - known):
            problems.append(f"{form.name}: label '{label}' is not in .github/labels.txt")
        fields = {item.get("id"): item.get("type") for item in data.get("body", []) if item.get("id")}
        for field, kind in PREFILLED.get(form.name, {}).items():
            if fields.get(field) != kind:
                problems.append(f"{form.name}: the app prefills '{field}', which must be an {kind} field")
    token = os.environ.get("GH_TOKEN")
    if token:
        output = subprocess.run(
            ["gh", "label", "list", "--limit", "500", "--json", "name"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        live = {entry["name"] for entry in json.loads(output)}
        for label in sorted(named - live):
            problems.append(f"label '{label}' does not exist in the repository; create it or drop it from the form")
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    if not problems:
        print(f"issue forms OK: labels {sorted(named)}, prefilled fields present")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
