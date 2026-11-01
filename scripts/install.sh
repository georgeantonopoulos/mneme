#!/usr/bin/env bash
set -euo pipefail

RUN_SETUP=1
for arg in "$@"; do
  case "$arg" in
    --no-setup) RUN_SETUP=0 ;;
  esac
done

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'MSG'
Install or update Mneme.

Environment variables:
  MNEME_REPO_URL     Git repository URL (default: public Mneme repo)
  MNEME_INSTALL_DIR  Checkout directory (default: ~/.local/share/mneme)
  MNEME_BIN_DIR      Symlink directory (default: ~/.local/bin)

Usage:
  curl -fsSL https://raw.githubusercontent.com/georgeantonopoulos/mneme/main/scripts/install.sh | bash
  curl -fsSL .../install.sh | bash -s -- --no-setup     # install only (for agents and scripts)

After install, in a terminal the installer starts `mneme setup` for you. Otherwise:
  mneme setup            # point Mneme at your notes and choose a model
  mneme learn            # read them into the brain
  mneme ask "..."        # recall, with the evidence
  mneme note --help      # path-safe Markdown note editor for agents
MSG
  exit 0
fi

REPO_URL="${MNEME_REPO_URL:-https://github.com/georgeantonopoulos/mneme.git}"
INSTALL_DIR="${MNEME_INSTALL_DIR:-$HOME/.local/share/mneme}"
BIN_DIR="${MNEME_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_DIR/.venv"

printf 'Installing Mneme from %s\n' "$REPO_URL"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  echo "git is required for this installer" >&2
  exit 1
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

mkdir -p "$BIN_DIR"

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$INSTALL_DIR"
else
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
  "$VENV_DIR/bin/python" -m pip install --upgrade "$INSTALL_DIR"
  ln -sf "$VENV_DIR/bin/mneme" "$BIN_DIR/mneme"
fi

MNEME_BIN="$BIN_DIR/mneme"
[ -x "$MNEME_BIN" ] || MNEME_BIN="$(command -v mneme || echo "$BIN_DIR/mneme")"

if "$MNEME_BIN" --help >/dev/null 2>&1; then
  echo "Mneme installed: $MNEME_BIN"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      cat <<MSG

Add Mneme to your PATH if your shell cannot find it yet:

  export PATH="$BIN_DIR:\$PATH"
MSG
      ;;
  esac
else
  echo "Install finished, but Mneme did not pass its help check." >&2
  exit 1
fi

# In a terminal, go straight into the setup wizard (curl | bash leaves stdin as the pipe, so read /dev/tty).
if [ "$RUN_SETUP" = "1" ] && [ -t 1 ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
  "$MNEME_BIN" setup < /dev/tty
else
  echo
  echo "Next: mneme setup"
fi
