#!/usr/bin/env python3
"""
Sync apps/react-app/config.yml → databricks.yml

Makes config.yml the single source of truth for shared parameters.
Run before `databricks bundle deploy`.

Usage:
    python3 sync_config.py          # update databricks.yml in place
    python3 sync_config.py --dry    # preview changes without writing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "apps" / "react-app" / "config.yml"
BUNDLE_PATH = ROOT / "databricks.yml"

# Minimal YAML value parser (handles strings, numbers, unquoted scalars)
_SCALAR_RE = re.compile(r'^["\']?(.+?)["\']?$')


def _read_config_values(path: Path) -> dict[str, str]:
    """Read top-level scalar key: value pairs from config.yml."""
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent > 0:
            continue
        key, _, raw = stripped.partition(":")
        key = key.strip()
        raw = raw.strip()
        if not raw or raw.startswith("{") or raw.startswith("["):
            continue
        m = _SCALAR_RE.match(raw)
        result[key] = m.group(1) if m else raw
    return result


# Maps  config.yml key  →  (regex to find the line in databricks.yml, format template)
# The regex must have exactly one capture group around the value portion.
FIELD_PATTERNS: dict[str, tuple[str, str]] = {
    "catalog": (
        r'^(\s+default:\s*")[^"]*(".*# catalog.*)$|^(\s+default:\s*")[^"]*("\s*)$',
        None,  # handled specially below
    ),
    "schema": (None, None),
    "experiment_id": (None, None),
    "llm_endpoint": (None, None),
    "host": (None, None),
}


def sync(*, dry: bool = False) -> list[str]:
    config = _read_config_values(CONFIG_PATH)
    lines = BUNDLE_PATH.read_text().splitlines(keepends=True)

    changes: list[str] = []

    # We walk through databricks.yml and update `default:` values in the
    # variables section, and `host:` values in the targets section, by
    # tracking which variable block we're inside.

    current_var: str | None = None  # which variable block we're in (catalog, schema, …)
    in_targets = False
    in_workspace = False

    var_keys = {"catalog", "schema", "experiment_id", "llm_endpoint"}

    new_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(line.lstrip())

        # Track top-level sections
        if indent == 0 and stripped.startswith("variables:"):
            current_var = None
            in_targets = False
        elif indent == 0 and stripped.startswith("targets:"):
            in_targets = True
            current_var = None
        elif indent == 0 and not stripped.startswith("#") and ":" in stripped:
            in_targets = False
            current_var = None

        # Inside variables: detect sub-keys like "  catalog:"
        if not in_targets and indent == 2 and stripped.rstrip().rstrip(":") in var_keys:
            current_var = stripped.rstrip().rstrip(":")

        # Replace `default:` value for a known variable
        if current_var and current_var in var_keys and stripped.startswith("default:"):
            cfg_val = config.get(current_var)
            if cfg_val is not None:
                old_val_match = re.search(r'default:\s*"([^"]*)"', line) or re.search(
                    r"default:\s*(\S+)", line
                )
                old_val = old_val_match.group(1) if old_val_match else ""
                if old_val != cfg_val:
                    changes.append(
                        f"  variables.{current_var}.default: {old_val!r} → {cfg_val!r}"
                    )
                    line = re.sub(
                        r'(default:\s*)"[^"]*"',
                        rf'\1"{cfg_val}"',
                        line,
                    )
                    if '"' not in line.split("default:")[1]:
                        line = re.sub(
                            r"(default:\s*)\S+",
                            rf'\1"{cfg_val}"',
                            line,
                        )

        # Track workspace blocks inside targets
        if in_targets and stripped.startswith("workspace:"):
            in_workspace = True
        elif in_targets and indent <= 4 and not stripped.startswith("workspace:") and ":" in stripped and indent > 0:
            if indent <= 4 and not stripped.startswith("host:"):
                in_workspace = stripped.startswith("workspace:")

        # Replace host: in targets.*.workspace
        if in_targets and in_workspace and stripped.startswith("host:"):
            cfg_host = config.get("host")
            if cfg_host:
                old_host_match = re.search(r"host:\s*(\S+)", line)
                old_host = old_host_match.group(1) if old_host_match else ""
                if old_host != cfg_host:
                    changes.append(
                        f"  targets.*.workspace.host: {old_host!r} → {cfg_host!r}"
                    )
                    line = re.sub(r"(host:\s*)\S+", rf"\1{cfg_host}", line)

        new_lines.append(line)

    if changes:
        print("Changes detected:" if dry else "Applied changes:")
        print("\n".join(changes))
        if not dry:
            BUNDLE_PATH.write_text("".join(new_lines))
            print(f"\n✓ {BUNDLE_PATH.name} updated.")
        else:
            print(f"\n(dry run — {BUNDLE_PATH.name} not modified)")
    else:
        print("✓ Already in sync — nothing to do.")

    return changes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    sync(dry=args.dry)
