#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 /path/to/mneme.sqlite [retrieval prompt]" >&2
  exit 2
fi

DB_PATH="$1"
PROMPT="${2:-working brain retrieval validation}"
LABEL_PROVIDER="${MNEME_LABEL_PROVIDER:-ollama}"
LABEL_MODEL="${MNEME_LABEL_MODEL:-gemma4:e4b}"
LABEL_COMMAND="${MNEME_LABEL_COMMAND:-}"
DEPTH="${MNEME_BRAIN_DEPTH:-default}"
PYTHON_BIN="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -f "$DB_PATH" || ! -r "$DB_PATH" ]]; then
  echo "DB_PATH must be an existing readable SQLite file: $DB_PATH" >&2
  exit 2
fi

case "$DEPTH" in
  smoke)
    DEFAULT_MAX_CLUSTERS=3
    DEFAULT_MAX_NODES=5
    DEFAULT_MAX_SYNAPSES=5
    DEFAULT_MAX_RELATIONSHIPS=5
    ;;
  default)
    DEFAULT_MAX_CLUSTERS=25
    DEFAULT_MAX_NODES=50
    DEFAULT_MAX_SYNAPSES=50
    DEFAULT_MAX_RELATIONSHIPS=25
    ;;
  deep)
    DEFAULT_MAX_CLUSTERS=100000
    DEFAULT_MAX_NODES=500
    DEFAULT_MAX_SYNAPSES=500
    DEFAULT_MAX_RELATIONSHIPS=100
    ;;
  full)
    DEFAULT_MAX_CLUSTERS=100000
    DEFAULT_MAX_NODES=100000
    DEFAULT_MAX_SYNAPSES=100000
    DEFAULT_MAX_RELATIONSHIPS=100000
    ;;
  *)
    echo "unknown MNEME_BRAIN_DEPTH '$DEPTH' (expected smoke, default, deep, or full)" >&2
    exit 2
    ;;
esac

LABEL_MAX_CLUSTERS="${MNEME_LABEL_MAX_CLUSTERS:-$DEFAULT_MAX_CLUSTERS}"
LABEL_MAX_NODES="${MNEME_LABEL_MAX_NODES:-$DEFAULT_MAX_NODES}"
LABEL_MAX_SYNAPSES="${MNEME_LABEL_MAX_SYNAPSES:-$DEFAULT_MAX_SYNAPSES}"
LABEL_MAX_RELATIONSHIPS="${MNEME_LABEL_MAX_RELATIONSHIPS:-$DEFAULT_MAX_RELATIONSHIPS}"

label_args=(--label-provider "$LABEL_PROVIDER" --label-model "$LABEL_MODEL")
if [[ -n "$LABEL_COMMAND" ]]; then
  label_args=(--label-command "$LABEL_COMMAND")
  if [[ -n "${MNEME_LABEL_PROVIDER:-}" ]]; then
    label_args=(--label-provider "$LABEL_PROVIDER" "${label_args[@]}")
  else
    label_args=(--label-provider custom "${label_args[@]}")
  fi
fi

"$PYTHON_BIN" -m mneme.cli consolidate \
  --db "$DB_PATH" \
  --label-max-clusters "$LABEL_MAX_CLUSTERS" \
  "${label_args[@]}"

"$PYTHON_BIN" -m mneme.cli brain label \
  --db "$DB_PATH" \
  --max-clusters "$LABEL_MAX_CLUSTERS" \
  --max-nodes "$LABEL_MAX_NODES" \
  --max-synapses "$LABEL_MAX_SYNAPSES" \
  --max-relationships "$LABEL_MAX_RELATIONSHIPS" \
  "${label_args[@]}"

"$PYTHON_BIN" -m mneme.cli brain report --db "$DB_PATH"
"$PYTHON_BIN" -m mneme.cli retrieve --db "$DB_PATH" --prompt "$PROMPT" --max-items 5
