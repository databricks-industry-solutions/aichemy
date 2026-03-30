#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

usage() {
    echo "Usage: $0 [--dry] [--target dev|prod] [--sync-only]"
    echo ""
    echo "  --dry        Preview config sync without writing"
    echo "  --target T   Deploy to target T (default: dev)"
    echo "  --sync-only  Only sync config.yml → databricks.yml, skip deploy"
    exit 1
}

DRY=""
TARGET="dev"
SYNC_ONLY=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry)       DRY="--dry"; shift ;;
        --target)    TARGET="$2"; shift 2 ;;
        --sync-only) SYNC_ONLY=true; shift ;;
        -h|--help)   usage ;;
        *)           echo "Unknown option: $1"; usage ;;
    esac
done

echo "==> Syncing config.yml → databricks.yml"
python3 "$SCRIPT_DIR/gen_databricksyaml.py" $DRY

if $SYNC_ONLY; then
    exit 0
fi

if [[ -n "$DRY" ]]; then
    echo ""
    echo "==> Dry run — skipping deploy"
    exit 0
fi

echo ""
echo "==> Validating bundle (target: $TARGET)"
databricks bundle validate --target "$TARGET"

echo ""
echo "==> Deploying bundle (target: $TARGET)"
databricks bundle deploy --target "$TARGET"
