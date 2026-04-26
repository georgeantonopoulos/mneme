#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'MSG'
Install or update Mneme.

Environment variables:
  MNEME_REPO_URL     Git repository URL (default: public Mneme repo)
  MNEME_INSTALL_DIR  Checkout directory (default: ~/.local/share/mneme)
  MNEME_BIN_DIR      Symlink directory (default: ~/.local/bin)

Usage:
  curl -fsSL https://raw.githubusercontent.com/georgeantonopoulos/mneme/main/scripts/install.sh | bash
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

if "$BIN_DIR/mneme" --help >/dev/null 2>&1; then
  echo "Mneme installed: $BIN_DIR/mneme"
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
