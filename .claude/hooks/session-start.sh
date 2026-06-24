#!/bin/bash
# SessionStart hook: bootstraps Python deps for Claude Code on the web sessions.
# Skipped entirely on local developer machines.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO_DIR="${CLAUDE_PROJECT_DIR:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
VENV_DIR="$REPO_DIR/.venv"

# Create the venv once; re-use it on resume.
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

# Install / upgrade the package plus dev extras (pytest).
# Uses pip's own caching — already-satisfied deps are fast on resume.
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -e "$REPO_DIR[dev]"

# Export the venv bin dir onto PATH for every startup and resume.
echo "export PATH=\"$VENV_DIR/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
