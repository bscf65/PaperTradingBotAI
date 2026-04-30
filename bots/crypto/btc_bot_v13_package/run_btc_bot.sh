#!/usr/bin/env bash
set -euo pipefail

show_help() {
cat <<'EOH'
run_btc_bot.sh - activate ~/btc-bot/.venv and run the BTC/ETH/SOL bot or analyzer

Usage:
  ./run_btc_bot.sh [SCRIPT_FILE] [SCRIPT_ARGS...]

Default SCRIPT_FILE:
  btc_eth_sol_coinbase_paper_bot_v13.py

Examples:
  ./run_btc_bot.sh --help
  ./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --help
  ./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/aggressive_100.json --once
  ./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/aggressive_100.json --reset
  ./run_btc_bot.sh analyze_bot_performance_v13.py

Notes:
  - This runner does not place trades.
  - The v13 bot uses Coinbase public market data only.
  - Default products: BTC-USD, ETH-USD, SOL-USD.
  - v13 supports JSON config files in ~/btc-bot/configs/.
  - It only activates the Python virtual environment and runs the selected script.
EOH
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    show_help
    exit 0
fi

BOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$BOT_DIR"

SCRIPT_FILE="${1:-btc_eth_sol_coinbase_paper_bot_v13.py}"
if [[ $# -gt 0 ]]; then
    shift
fi

if [[ ! -f ".venv/bin/activate" ]]; then
    echo "ERROR: Virtual environment not found at: $BOT_DIR/.venv"
    echo "Run: bash setup_btc_bot.sh"
    exit 1
fi

if [[ ! -f "$SCRIPT_FILE" ]]; then
    echo "ERROR: Script file not found: $BOT_DIR/$SCRIPT_FILE"
    echo "Available files:"
    ls -la
    exit 1
fi

source ".venv/bin/activate"

echo "Activated virtual environment: $(which python)"
echo "Running: python $SCRIPT_FILE $*"
echo "------------------------------------------------------------"
python "$SCRIPT_FILE" "$@"
