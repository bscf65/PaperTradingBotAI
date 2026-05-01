#!/usr/bin/env bash
set -euo pipefail

DEFAULT_SOURCE="/home/bscf/Documents/InvestAI/QuantumAI/quantum_ai_bot_v2_investai_package"
SOURCE_DIR="${1:-$DEFAULT_SOURCE}"
if [[ ! -d "$SOURCE_DIR" ]]; then
  SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi

BOT_DIR="$HOME/quantum-ai-bot"
mkdir -p "$BOT_DIR" "$BOT_DIR/configs" "$BOT_DIR/logs"

copy_if_different() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$src" ]]; then
    echo "Skipping missing file: $src"
    return
  fi
  if [[ "$(realpath "$src")" == "$(realpath -m "$dst")" ]]; then
    echo "Already in place: $(basename "$dst")"
    return
  fi
  cp "$src" "$dst"
  echo "Copied: $(basename "$dst")"
}

copy_if_different "$SOURCE_DIR/quantum_ai_paper_bot_v2.py" "$BOT_DIR/quantum_ai_paper_bot_v2.py"
copy_if_different "$SOURCE_DIR/analyze_quantum_ai_performance_v2.py" "$BOT_DIR/analyze_quantum_ai_performance_v2.py"
copy_if_different "$SOURCE_DIR/run_quantum_ai_bot.sh" "$BOT_DIR/run_quantum_ai_bot.sh"
copy_if_different "$SOURCE_DIR/README.md" "$BOT_DIR/README.md"

if [[ -d "$SOURCE_DIR/configs" ]]; then
  cp "$SOURCE_DIR"/configs/*.json "$BOT_DIR/configs/" 2>/dev/null || true
  echo "Copied configs."
fi

cd "$BOT_DIR"
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
  echo "Created virtual environment: $BOT_DIR/.venv"
else
  echo "Virtual environment already exists: $BOT_DIR/.venv"
fi

source .venv/bin/activate
python -m pip install --upgrade pip
pip install pandas numpy requests yfinance

chmod +x run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py analyze_quantum_ai_performance_v2.py

echo
echo "Setup complete."
echo "Working bot folder: $BOT_DIR"
echo
echo "Try:"
echo "  cd $BOT_DIR"
echo "  ./run_quantum_ai_bot.sh quantum_ai_paper_bot_v2.py --config configs/quantum_ai_100.json --once"
