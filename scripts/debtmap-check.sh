#!/usr/bin/env bash
# Runs debtmap and blocks the commit if any Critical-tier items are found.
set -euo pipefail

if ! command -v debtmap &>/dev/null; then
  echo "debtmap not found. Install it with:"
  echo "  curl -sSL https://raw.githubusercontent.com/iepathos/debtmap/master/install.sh | bash"
  exit 1
fi

OUT=$(debtmap analyze . --format markdown)
echo "$OUT"

if echo "$OUT" | grep -q "Critical: 0"; then
  exit 0
else
  echo ""
  echo "debtmap: Critical-tier debt found. Fix before committing."
  exit 1
fi
