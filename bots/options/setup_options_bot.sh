#!/usr/bin/env bash
set -euo pipefail

# Options Bot v4 installer for Fraser's InvestAI/ETF download folder.
# Expected download/unzip root:
#   /home/bscf/Documents/InvestAI/ETF
# Working bot install/update folder:
#   /home/bscf/options-bot
#
# You can also pass the source/package folder explicitly:
#   bash setup_options_bot.sh /path/to/options_bot_v4_investai_etf_package

DEFAULT_DOWNLOAD_ROOT="/home/bscf/Documents/InvestAI/ETF"
PACKAGE_NAME="options_bot_v4_investai_etf_package"
BOT_DIR="$HOME/options-bot"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ge 1 ]]; then
  SOURCE_DIR="$1"
elif [[ -f "$SCRIPT_DIR/options_etf_paper_bot_v4.py" ]]; then
  SOURCE_DIR="$SCRIPT_DIR"
elif [[ -d "$DEFAULT_DOWNLOAD_ROOT/$PACKAGE_NAME" ]]; then
  SOURCE_DIR="$DEFAULT_DOWNLOAD_ROOT/$PACKAGE_NAME"
else
  SOURCE_DIR="$SCRIPT_DIR"
fi

SOURCE_DIR="$(realpath "$SOURCE_DIR")"

if [[ ! -f "$SOURCE_DIR/options_etf_paper_bot_v4.py" ]]; then
  echo "ERROR: Could not find options_etf_paper_bot_v4.py in: $SOURCE_DIR"
  echo
  echo "Expected layout:"
  echo "  $DEFAULT_DOWNLOAD_ROOT/$PACKAGE_NAME/options_etf_paper_bot_v4.py"
  echo
  echo "Try:"
  echo "  cd $DEFAULT_DOWNLOAD_ROOT"
  echo "  unzip options_bot_v4_investai_etf_package.zip"
  echo "  cd $PACKAGE_NAME"
  echo "  bash setup_options_bot.sh"
  exit 1
fi

echo "Source package folder: $SOURCE_DIR"
echo "Install/update folder:  $BOT_DIR"

mkdir -p "$BOT_DIR" "$BOT_DIR/configs" "$BOT_DIR/logs"

copy_file() {
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

copy_file "$SOURCE_DIR/options_etf_paper_bot_v4.py" "$BOT_DIR/options_etf_paper_bot_v4.py"
copy_file "$SOURCE_DIR/analyze_options_performance_v4.py" "$BOT_DIR/analyze_options_performance_v4.py"
copy_file "$SOURCE_DIR/run_options_bot.sh" "$BOT_DIR/run_options_bot.sh"
copy_file "$SOURCE_DIR/README.md" "$BOT_DIR/README.md"

if [[ -d "$SOURCE_DIR/configs" ]]; then
  cp -r "$SOURCE_DIR/configs/." "$BOT_DIR/configs/"
  echo "Copied configs/."
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

chmod +x run_options_bot.sh options_etf_paper_bot_v4.py analyze_options_performance_v4.py

cat <<DONE

Setup complete.
Bot folder: $BOT_DIR
Download/package root expected at: $DEFAULT_DOWNLOAD_ROOT

Try:
  cd $BOT_DIR
  ./run_options_bot.sh options_etf_paper_bot_v4.py --config configs/scan_only_with_news.json --once

Then, for paper simulation:
  ./run_options_bot.sh options_etf_paper_bot_v4.py --config configs/two_way_default.json --reset
DONE
