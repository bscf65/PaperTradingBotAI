#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$HOME/ai-private-tech-bot"
cd "$BOT_DIR"

BOT_FILE="${1:-private_ai_paper_bot_v4.py}"
if [[ $# -gt 0 ]]; then
  shift
fi

if [[ "$BOT_FILE" == "--help" || "$BOT_FILE" == "-h" ]]; then
  cat <<'EOF'
InvestAI AI Private-Tech Bot Runner

Usage:
  ./run_private_ai_bot.sh [python_file.py] [args...]

Examples:
  ./run_private_ai_bot.sh private_ai_paper_bot_v4.py --config configs/scan_only_private_ai.json --once
  ./run_private_ai_bot.sh private_ai_paper_bot_v4.py --config configs/private_ai_100.json --reset
  ./run_private_ai_bot.sh analyze_private_ai_performance_v4.py
  ./run_private_ai_bot.sh collect_investai_ml_data_v4.py
EOF
  exit 0
fi

if [[ ! -f ".venv/bin/activate" ]]; then
  echo "ERROR: Missing virtual environment at $BOT_DIR/.venv"
  echo "Run setup_private_ai_bot.sh first."
  exit 1
fi

if [[ ! -f "$BOT_FILE" ]]; then
  echo "ERROR: Bot file not found: $BOT_DIR/$BOT_FILE"
  ls -la
  exit 1
fi

source .venv/bin/activate

echo "Activated virtual environment: $(which python)"
echo "Running: python $BOT_FILE $*"
echo "------------------------------------------------------------"
python "$BOT_FILE" "$@"
