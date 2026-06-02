#!/usr/bin/env python3
"""
Sync apps/react-app/config.yml → databricks.yml

Makes config.yml the single source of truth for shared parameters.
Run before `databricks bundle deploy`.

Usage:
    python3 gen_databricksyaml.py          # update databricks.yml in place
    python3 gen_databricksyaml.py --dry    # preview changes without writing
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "apps" / "react-app" / "config.yml"
BUNDLE_PATH = ROOT / "databricks.yml"

_SCALAR_RE = re.compile(r'^["\']?(.+?)["\']?$')

# config.yml lakebase.* keys → databricks.yml variables.*
LAKEBASE_TO_VAR = {
    "project_id": "lakebase_project_id",
    "branch_id": "lakebase_branch_id",
    "endpoint_id": "lakebase_endpoint_id",
    "database": "lakebase_database",
}

VAR_KEYS = {
    "catalog",
    "schema",
    "experiment_id",
    "llm_endpoint",
    "secret_scope",
    *LAKEBASE_TO_VAR.values(),
}


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


def _read_nested_section(path: Path, section: str) -> dict[str, str]:
    """Read one-level nested scalar key: value pairs under a top-level section."""
    result: dict[str, str] = {}
    in_section = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        indent = len(line) - len(line.lstrip())
        key, _, raw = stripped.partition(":")
        key = key.strip()
        raw = raw.strip()

        if indent == 0:
            in_section = key == section
            continue

        if not in_section or indent != 2:
            continue
        if not raw or raw.startswith("{") or raw.startswith("["):
            continue
        m = _SCALAR_RE.match(raw)
        result[key] = m.group(1) if m else raw
    return result


def _read_service_principal_scope(path: Path) -> str | None:
    """Return the secret scope name from service_principal.<scope>."""
    in_section = False
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        indent = len(line) - len(line.lstrip())
        key, _, raw = stripped.partition(":")
        key = key.strip()
        raw = raw.strip()

        if indent == 0:
            in_section = key == "service_principal"
            continue

        if in_section and indent == 2 and not raw:
            return key
    return None


def _build_config() -> dict[str, str]:
    config = _read_config_values(CONFIG_PATH)
    lakebase = _read_nested_section(CONFIG_PATH, "lakebase")
    for lk, var in LAKEBASE_TO_VAR.items():
        if lk in lakebase:
            config[var] = lakebase[lk]
    scope = _read_service_principal_scope(CONFIG_PATH)
    if scope:
        config["secret_scope"] = scope
    return config


def _replace_default(line: str, cfg_val: str) -> str:
    line = re.sub(r'(default:\s*)"[^"]*"', rf'\1"{cfg_val}"', line)
    if '"' not in line.split("default:", 1)[1]:
        line = re.sub(r"(default:\s*)\S+", rf'\1"{cfg_val}"', line)
    return line


def sync(*, dry: bool = False) -> list[str]:
    config = _build_config()
    lines = BUNDLE_PATH.read_text().splitlines(keepends=True)
    changes: list[str] = []

    current_var: str | None = None
    in_targets = False
    in_workspace = False

    new_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped.startswith("variables:"):
            current_var = None
            in_targets = False
        elif indent == 0 and stripped.startswith("targets:"):
            in_targets = True
            current_var = None
        elif indent == 0 and not stripped.startswith("#") and ":" in stripped:
            in_targets = False
            current_var = None

        if not in_targets and indent == 2 and stripped.endswith(":"):
            key = stripped.rstrip().rstrip(":")
            current_var = key if key in VAR_KEYS else None

        if current_var and current_var in VAR_KEYS and stripped.startswith("default:"):
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
                    line = _replace_default(line, cfg_val)

        if in_targets and stripped.startswith("workspace:"):
            in_workspace = True
        elif (
            in_targets
            and indent <= 4
            and not stripped.startswith("workspace:")
            and ":" in stripped
            and indent > 0
        ):
            if indent <= 4 and not stripped.startswith("host:"):
                in_workspace = stripped.startswith("workspace:")

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
