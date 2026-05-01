#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$BOT_DIR"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Usage:
  ./run_options_bot.sh [python_file.py] [args...]

Examples:
  ./run_options_bot.sh options_etf_paper_bot_v4.py --config configs/two_way_default.json --once
  ./run_options_bot.sh options_etf_paper_bot_v4.py --config configs/two_way_default.json --reset
  ./run_options_bot.sh analyze_options_performance_v4.py

If no Python file is provided, defaults to options_etf_paper_bot_v4.py.
EOF
  exit 0
fi

PY_FILE="${1:-options_etf_paper_bot_v4.py}"
if [[ $# -gt 0 ]]; then
  shift
fi

if [[ ! -d ".venv" ]]; then
  echo "ERROR: .venv not found. Run: bash setup_options_bot.sh"
  exit 1
fi

if [[ ! -f "$PY_FILE" ]]; then
  echo "ERROR: Python file not found: $PY_FILE"
  ls -la
  exit 1
fi

source .venv/bin/activate

echo "Activated virtual environment: $(which python)"
echo "Running: python $PY_FILE $*"
echo "------------------------------------------------------------"
python "$PY_FILE" "$@"
