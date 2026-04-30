#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="$HOME/btc-bot"
SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$TARGET_DIR/logs"
mkdir -p "$TARGET_DIR/configs"

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

copy_if_different "$SRC_DIR/btc_eth_sol_coinbase_paper_bot_v13.py" "$TARGET_DIR/btc_eth_sol_coinbase_paper_bot_v13.py"
copy_if_different "$SRC_DIR/analyze_bot_performance_v13.py" "$TARGET_DIR/analyze_bot_performance_v13.py"
copy_if_different "$SRC_DIR/run_btc_bot.sh" "$TARGET_DIR/run_btc_bot.sh"
copy_if_different "$SRC_DIR/README.md" "$TARGET_DIR/README_v13.md"

if [[ -d "$SRC_DIR/configs" ]]; then
    mkdir -p "$TARGET_DIR/configs"
    for cfg in "$SRC_DIR"/configs/*.json; do
        if [[ -f "$cfg" ]]; then
            copy_if_different "$cfg" "$TARGET_DIR/configs/$(basename "$cfg")"
        fi
    done
fi

cd "$TARGET_DIR"

if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
    echo "Created virtual environment: $TARGET_DIR/.venv"
else
    echo "Virtual environment already exists: $TARGET_DIR/.venv"
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install requests pandas numpy

chmod +x btc_eth_sol_coinbase_paper_bot_v13.py analyze_bot_performance_v13.py run_btc_bot.sh

if ! command -v notify-send >/dev/null 2>&1; then
    echo "Note: notify-send was not found. Absolute-stop popup may not appear."
    echo "On Kali/Debian, you can usually install it with: sudo apt install -y libnotify-bin"
fi

echo "Setup complete."
echo "Bot folder: $TARGET_DIR"
echo
cat <<'EOH'
Try:
  cd ~/btc-bot
  ./run_btc_bot.sh --help
  ./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --help
  ./run_btc_bot.sh btc_eth_sol_coinbase_paper_bot_v13.py --config configs/aggressive_100.json --once
  nano configs/all_flags_template.json
  ./run_btc_bot.sh analyze_bot_performance_v13.py
EOH
