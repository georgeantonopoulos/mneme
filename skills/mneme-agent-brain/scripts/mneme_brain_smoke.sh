#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 /path/to/mneme.sqlite [retrieval prompt]" >&2
  exit 2
fi

DB_PATH="$1"
PROMPT="${2:-Hermes Mneme brain validation}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${MNEME_REPO:-$(cd "$SKILL_DIR/../.." && pwd)}"
READY_SCRIPT="$REPO_ROOT/scripts/hermes_brain_ready.sh"

if [[ ! -x "$READY_SCRIPT" ]]; then
  echo "expected executable readiness script at: $READY_SCRIPT" >&2
  echo "set MNEME_REPO to a Mneme checkout if this skill was copied elsewhere" >&2
  exit 2
fi

"$READY_SCRIPT" "$DB_PATH" "$PROMPT"
