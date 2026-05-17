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
LABEL_MAX_CLUSTERS="${MNEME_LABEL_MAX_CLUSTERS:-25}"
LABEL_MAX_NODES="${MNEME_LABEL_MAX_NODES:-50}"
LABEL_MAX_SYNAPSES="${MNEME_LABEL_MAX_SYNAPSES:-50}"
LABEL_MAX_RELATIONSHIPS="${MNEME_LABEL_MAX_RELATIONSHIPS:-25}"
PYTHON_BIN="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

label_args=(--label-provider "$LABEL_PROVIDER" --label-model "$LABEL_MODEL")
if [[ -n "$LABEL_COMMAND" ]]; then
  label_args=(--label-provider custom --label-command "$LABEL_COMMAND")
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
