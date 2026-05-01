#!/usr/bin/env bash
set -euo pipefail

DEFAULT_SOURCE_DIR="/home/bscf/Documents/InvestAI/PrivateAI/private_ai_bot_v4_investai_package"
BOT_DIR="$HOME/ai-private-tech-bot"
SOURCE_DIR="${1:-}"

if [[ -z "$SOURCE_DIR" ]]; then
  THIS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  if [[ -f "$THIS_DIR/private_ai_paper_bot_v4.py" ]]; then
    SOURCE_DIR="$THIS_DIR"
  elif [[ -f "$DEFAULT_SOURCE_DIR/private_ai_paper_bot_v4.py" ]]; then
    SOURCE_DIR="$DEFAULT_SOURCE_DIR"
  else
    echo "ERROR: Could not find package source directory."
    echo "Run this script from the unzipped package folder, or pass the source path:"
    echo "  bash setup_private_ai_bot.sh /home/bscf/Documents/InvestAI/PrivateAI/private_ai_bot_v4_investai_package"
    exit 1
  fi
fi

mkdir -p "$BOT_DIR" "$BOT_DIR/logs" "$BOT_DIR/configs"

copy_file() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$src" ]]; then
    echo "Skipping missing: $src"
    return
  fi
  if [[ "$(realpath "$src")" == "$(realpath -m "$dst")" ]]; then
    echo "Already in place: $(basename "$dst")"
    return
  fi
  cp "$src" "$dst"
  echo "Copied: $(basename "$dst")"
}

copy_file "$SOURCE_DIR/private_ai_paper_bot_v4.py" "$BOT_DIR/private_ai_paper_bot_v4.py"
copy_file "$SOURCE_DIR/analyze_private_ai_performance_v4.py" "$BOT_DIR/analyze_private_ai_performance_v4.py"
copy_file "$SOURCE_DIR/collect_investai_ml_data_v4.py" "$BOT_DIR/collect_investai_ml_data_v4.py"
copy_file "$SOURCE_DIR/run_private_ai_bot.sh" "$BOT_DIR/run_private_ai_bot.sh"
copy_file "$SOURCE_DIR/README.md" "$BOT_DIR/README.md"

if [[ -d "$SOURCE_DIR/configs" ]]; then
  cp "$SOURCE_DIR"/configs/*.json "$BOT_DIR/configs/"
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

chmod +x private_ai_paper_bot_v4.py analyze_private_ai_performance_v4.py collect_investai_ml_data_v4.py run_private_ai_bot.sh

cat <<EOF

Setup complete.
Working bot folder: $BOT_DIR

Try:
  cd $BOT_DIR
  ./run_private_ai_bot.sh private_ai_paper_bot_v4.py --config configs/scan_only_private_ai.json --once

Start paper simulation:
  ./run_private_ai_bot.sh private_ai_paper_bot_v4.py --config configs/private_ai_100.json --reset

Build ML dataset from all InvestAI bot logs:
  ./run_private_ai_bot.sh collect_investai_ml_data_v4.py
EOF
