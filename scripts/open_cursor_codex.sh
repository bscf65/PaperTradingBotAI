#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="/home/bscf/Documents/InvestAI/AIBots Project/ProjectMain"
cd "$PROJECT_ROOT"

if command -v cursor >/dev/null 2>&1; then
  echo "Opening Cursor at: $PROJECT_ROOT"
  cursor "$PROJECT_ROOT" >/tmp/investai_cursor_launch.log 2>&1 &
else
  echo "Cursor command not found. Open Cursor manually and choose this folder:"
  echo "$PROJECT_ROOT"
fi

if command -v codex >/dev/null 2>&1; then
  echo
  echo "Starting Codex in project root..."
  echo "Safety prompt saved at: $PROJECT_ROOT/CODEX_SAFE_START_PROMPT.md"
  echo
  codex
else
  echo "Codex command not found. Run setup again or install with: sudo npm install -g @openai/codex"
fi
