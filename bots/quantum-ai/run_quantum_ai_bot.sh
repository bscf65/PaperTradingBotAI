#!/usr/bin/env bash
set -euo pipefail

BOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$BOT_DIR"

show_help() {
  cat <<'EOF'
InvestAI Quantum/AI Bot Runner

Usage:
  ./run_quantum_ai_bot.sh [python_file.py] [options]

Examples:
  ./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py --config configs/quantum_ai_100.json --once
  ./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py --config configs/quantum_ai_100.json --reset
  ./run_quantum_ai_bot.sh analyze_quantum_ai_performance_v2.py

Notes:
  - This activates the local .venv automatically.
  - This is paper trading only. No broker login. No real orders.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

PY_FILE="${1:-quantum_ai_paper_bot_v2.py}"
if [[ $# -gt 0 ]]; then
  shift
fi

if [[ ! -d ".venv" ]]; then
  echo "ERROR: .venv not found. Run setup_quantum_ai_bot.sh first."
  exit 1
fi

if [[ ! -f "$PY_FILE" ]]; then
  echo "ERROR: Python file not found: $PY_FILE"
  ls -lah
  exit 1
fi

source .venv/bin/activate

echo "Activated virtual environment: $(which python)"
echo "Running: python $PY_FILE $*"
echo "------------------------------------------------------------"
python "$PY_FILE" "$@"
