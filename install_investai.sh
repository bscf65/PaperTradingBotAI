#!/usr/bin/env bash
set -euo pipefail

# InvestAI Unified Installer — DRAFT
# Builds one clean ProjectMain folder for local-only paper-trading bot research.
# Confirmed root:
#   /home/bscf/Documents/InvestAI/AIBots Project/ProjectMain

PROJECT_ROOT_DEFAULT="/home/bscf/Documents/InvestAI/AIBots Project/ProjectMain"
PROJECT_ROOT="${INVESTAI_PROJECT_ROOT:-$PROJECT_ROOT_DEFAULT}"
SOURCE_ZIP_DIR="${INVESTAI_SOURCE_ZIP_DIR:-$(pwd)}"
DRY_RUN=0
ONLY="all"

usage() {
  cat <<USAGE
Usage: $0 [--dry-run] [--only crypto|options|quantum|privateai|control|all] [--source-zips DIR]
Default root: $PROJECT_ROOT_DEFAULT
Dashboard: http://127.0.0.1:8765/
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --source-zips) SOURCE_ZIP_DIR="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unknown argument: $1"; usage; exit 1 ;;
  esac
done

run() { if [[ "$DRY_RUN" -eq 1 ]]; then printf 'DRY-RUN: '; printf '%q ' "$@"; printf '\n'; else "$@"; fi; }
say() { echo "[InvestAI] $*"; }
warn() { echo "[InvestAI WARNING] $*" >&2; }
fail() { echo "[InvestAI ERROR] $*" >&2; exit 1; }

copy_file() {
  local src="$1" dst="$2"
  [[ -f "$src" ]] || { warn "Missing file, skipping: $src"; return 0; }
  run mkdir -p "$(dirname "$dst")"
  run cp -f "$src" "$dst"
  say "Copied $(basename "$src") -> $dst"
}

copy_tree_contents() {
  local src_dir="$1" dst_dir="$2"
  [[ -d "$src_dir" ]] || { warn "Missing directory, skipping: $src_dir"; return 0; }
  run mkdir -p "$dst_dir"
  if [[ "$DRY_RUN" -eq 1 ]]; then echo "DRY-RUN: cp -a '$src_dir/.' '$dst_dir/'"; else cp -a "$src_dir/." "$dst_dir/"; fi
  say "Copied contents of $src_dir -> $dst_dir"
}

latest_zip() {
  local pattern="$1"
  find "$PROJECT_ROOT/zips" -maxdepth 1 -type f -name "$pattern" -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {print $2}'
}

extract_zip() {
  local label="$1" pattern="$2" zip_path extract_dir
  zip_path="$(latest_zip "$pattern" || true)"
  if [[ -z "$zip_path" ]]; then warn "No ZIP found for $label using pattern: $pattern"; return 1; fi
  extract_dir="$PROJECT_ROOT/pkgs/extracted/$label"
  say "Extracting $label from $zip_path"
  run rm -rf "$extract_dir"
  run mkdir -p "$extract_dir"
  if [[ "$DRY_RUN" -eq 1 ]]; then echo "DRY-RUN: unzip -q '$zip_path' -d '$extract_dir'"; else unzip -q "$zip_path" -d "$extract_dir"; fi
  printf '%s\n' "$extract_dir"
}

find_package_dir_containing() {
  local extract_dir="$1" required_file="$2"
  find "$extract_dir" -type f -name "$required_file" -printf '%h\n' | sort | head -1
}

setup_base_tree() {
  say "Creating ProjectMain tree: $PROJECT_ROOT"
  run mkdir -p \
    "$PROJECT_ROOT/bots/crypto" "$PROJECT_ROOT/bots/options" \
    "$PROJECT_ROOT/bots/quantum-ai" "$PROJECT_ROOT/bots/private-ai" \
    "$PROJECT_ROOT/control-center" \
    "$PROJECT_ROOT/configs/crypto" "$PROJECT_ROOT/configs/options" \
    "$PROJECT_ROOT/configs/quantum-ai" "$PROJECT_ROOT/configs/private-ai" \
    "$PROJECT_ROOT/logs/crypto" "$PROJECT_ROOT/logs/options" \
    "$PROJECT_ROOT/logs/quantum-ai" "$PROJECT_ROOT/logs/private-ai" \
    "$PROJECT_ROOT/data/raw" "$PROJECT_ROOT/data/processed" "$PROJECT_ROOT/data/ml" \
    "$PROJECT_ROOT/reports/performance" "$PROJECT_ROOT/scripts" \
    "$PROJECT_ROOT/zips" "$PROJECT_ROOT/downloads" \
    "$PROJECT_ROOT/pkgs/extracted" "$PROJECT_ROOT/pkgs/archive"
}

copy_zips_into_project() {
  say "Copying package ZIPs from: $SOURCE_ZIP_DIR"
  [[ -d "$SOURCE_ZIP_DIR" ]] || fail "Source ZIP folder not found: $SOURCE_ZIP_DIR"
  shopt -s nullglob
  local copied=0
  for z in "$SOURCE_ZIP_DIR"/*.zip; do
    run cp -f "$z" "$PROJECT_ROOT/zips/$(basename "$z")"
    copied=$((copied + 1))
  done
  shopt -u nullglob
  [[ "$copied" -gt 0 ]] && say "Copied $copied ZIP file(s) into $PROJECT_ROOT/zips" || warn "No ZIP files found in $SOURCE_ZIP_DIR"
}

install_shared_venv() {
  say "Creating/updating shared Python virtual environment"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN: python3 -m venv '$PROJECT_ROOT/.venv'"
    echo "DRY-RUN: '$PROJECT_ROOT/.venv/bin/python' -m pip install --upgrade pip setuptools wheel pandas numpy requests yfinance"
    return 0
  fi
  if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then python3 -m venv "$PROJECT_ROOT/.venv"; fi
  "$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$PROJECT_ROOT/.venv/bin/python" -m pip install pandas numpy requests yfinance
}

link_bot_runtime() {
  local bot_dir="$1" log_dir="$2" cfg_dir="$3"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "DRY-RUN: replace $bot_dir/{logs,configs,.venv} with symlinks"
  else
    rm -rf "$bot_dir/logs" "$bot_dir/configs" "$bot_dir/.venv"
    ln -s "$log_dir" "$bot_dir/logs"
    ln -s "$cfg_dir" "$bot_dir/configs"
    ln -s "$PROJECT_ROOT/.venv" "$bot_dir/.venv"
  fi
}

install_crypto() {
  local extract_dir pkg bot_dir cfg_dir log_dir
  extract_dir="$(extract_zip crypto 'btc_bot*_package.zip')" || return 0
  pkg="$(find_package_dir_containing "$extract_dir" 'btc_eth_sol_coinbase_paper_bot_v17.py')"
  [[ -n "$pkg" ]] || { warn "Crypto package missing bot file"; return 0; }
  bot_dir="$PROJECT_ROOT/bots/crypto"; cfg_dir="$PROJECT_ROOT/configs/crypto"; log_dir="$PROJECT_ROOT/logs/crypto"
  copy_file "$pkg/btc_eth_sol_coinbase_paper_bot_v17.py" "$bot_dir/btc_eth_sol_coinbase_paper_bot_v17.py"
  copy_file "$pkg/analyze_bot_performance_v17.py" "$bot_dir/analyze_bot_performance_v17.py"
  copy_file "$pkg/run_btc_bot.sh" "$bot_dir/run_btc_bot.sh"
  copy_file "$pkg/README.md" "$bot_dir/README_v17.md"
  copy_tree_contents "$pkg/configs" "$cfg_dir"
  link_bot_runtime "$bot_dir" "$log_dir" "$cfg_dir"
  run chmod +x "$bot_dir"/*.py "$bot_dir"/*.sh
}

install_options() {
  local extract_dir pkg bot_dir cfg_dir log_dir
  extract_dir="$(extract_zip options 'options_bot*_package.zip')" || return 0
  pkg="$(find_package_dir_containing "$extract_dir" 'options_etf_paper_bot_v4.py')"
  [[ -n "$pkg" ]] || { warn "Options package missing bot file"; return 0; }
  bot_dir="$PROJECT_ROOT/bots/options"; cfg_dir="$PROJECT_ROOT/configs/options"; log_dir="$PROJECT_ROOT/logs/options"
  copy_file "$pkg/options_etf_paper_bot_v4.py" "$bot_dir/options_etf_paper_bot_v4.py"
  copy_file "$pkg/analyze_options_performance_v4.py" "$bot_dir/analyze_options_performance_v4.py"
  copy_file "$pkg/run_options_bot.sh" "$bot_dir/run_options_bot.sh"
  copy_file "$pkg/README.md" "$bot_dir/README.md"
  copy_tree_contents "$pkg/configs" "$cfg_dir"
  link_bot_runtime "$bot_dir" "$log_dir" "$cfg_dir"
  run chmod +x "$bot_dir"/*.py "$bot_dir"/*.sh
}

install_quantum() {
  local extract_dir pkg bot_dir cfg_dir log_dir
  extract_dir="$(extract_zip quantum 'quantum_ai_bot*_package.zip')" || return 0
  pkg="$(find_package_dir_containing "$extract_dir" 'quantum_ai_paper_bot_v2.py')"
  [[ -n "$pkg" ]] || { warn "Quantum package missing bot file"; return 0; }
  bot_dir="$PROJECT_ROOT/bots/quantum-ai"; cfg_dir="$PROJECT_ROOT/configs/quantum-ai"; log_dir="$PROJECT_ROOT/logs/quantum-ai"
  copy_file "$pkg/quantum_ai_paper_bot_v2.py" "$bot_dir/quantum_ai_paper_bot_v2.py"
  copy_file "$pkg/analyze_quantum_ai_performance_v2.py" "$bot_dir/analyze_quantum_ai_performance_v2.py"
  copy_file "$pkg/run_quantum_ai_bot.sh" "$bot_dir/run_quantum_ai_bot.sh"
  copy_file "$pkg/README.md" "$bot_dir/README.md"
  copy_tree_contents "$pkg/configs" "$cfg_dir"
  link_bot_runtime "$bot_dir" "$log_dir" "$cfg_dir"
  run chmod +x "$bot_dir"/*.py "$bot_dir"/*.sh
}

install_privateai() {
  local extract_dir pkg bot_dir cfg_dir log_dir
  extract_dir="$(extract_zip privateai 'private_ai_bot*_package.zip')" || return 0
  pkg="$(find_package_dir_containing "$extract_dir" 'private_ai_paper_bot_v4.py')"
  [[ -n "$pkg" ]] || { warn "PrivateAI package missing bot file"; return 0; }
  bot_dir="$PROJECT_ROOT/bots/private-ai"; cfg_dir="$PROJECT_ROOT/configs/private-ai"; log_dir="$PROJECT_ROOT/logs/private-ai"
  copy_file "$pkg/private_ai_paper_bot_v4.py" "$bot_dir/private_ai_paper_bot_v4.py"
  copy_file "$pkg/analyze_private_ai_performance_v4.py" "$bot_dir/analyze_private_ai_performance_v4.py"
  copy_file "$pkg/collect_investai_ml_data_v4.py" "$bot_dir/collect_investai_ml_data_v4.py"
  copy_file "$pkg/run_private_ai_bot.sh" "$bot_dir/run_private_ai_bot.sh"
  copy_file "$pkg/README.md" "$bot_dir/README.md"
  copy_tree_contents "$pkg/configs" "$cfg_dir"
  link_bot_runtime "$bot_dir" "$log_dir" "$cfg_dir"
  run chmod +x "$bot_dir"/*.py "$bot_dir"/*.sh
}

install_control_center() {
  local zip_path extract_dir pkg
  zip_path="$(latest_zip 'investai_control_center*_package.zip' || true)"
  if [[ -z "$zip_path" ]]; then
    warn "No control-center ZIP found. Dashboard wrapper will be created, but control-center files are not installed yet."
    return 0
  fi
  extract_dir="$PROJECT_ROOT/pkgs/extracted/control-center"
  run rm -rf "$extract_dir"; run mkdir -p "$extract_dir"
  if [[ "$DRY_RUN" -eq 1 ]]; then echo "DRY-RUN: unzip -q '$zip_path' -d '$extract_dir'"; else unzip -q "$zip_path" -d "$extract_dir"; fi
  pkg="$(find "$extract_dir" -type f -name 'start_control_center_firefox.sh' -printf '%h\n' | sort | head -1 || true)"
  [[ -n "$pkg" ]] && copy_tree_contents "$pkg" "$PROJECT_ROOT/control-center" || copy_tree_contents "$extract_dir" "$PROJECT_ROOT/control-center"
}

write_investai_control_script() {
  local dst="$PROJECT_ROOT/investai.sh"
  say "Writing master control script: $dst"
  [[ "$DRY_RUN" -eq 1 ]] && { echo "DRY-RUN: write $dst"; return 0; }
  cat > "$dst" <<'CONTROL_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
usage() { cat <<USAGE
Usage:
  ./investai.sh start crypto|options|quantum|privateai [extra args...]
  ./investai.sh start all
  ./investai.sh analyze crypto|options|quantum|privateai|all
  ./investai.sh dashboard
  ./investai.sh status
  ./investai.sh tree
Dashboard URL: http://127.0.0.1:8765/
USAGE
}
require_python() { [[ -x "$PYTHON" ]] || { echo "ERROR: Missing shared venv python: $PYTHON" >&2; exit 1; }; }
run_py() { local dir="$1" py_file="$2"; shift 2; require_python; cd "$dir"; exec "$PYTHON" "$py_file" "$@"; }
start_bot() {
  local bot="$1"; shift || true
  case "$bot" in
    crypto) run_py "$PROJECT_ROOT/bots/crypto" "btc_eth_sol_coinbase_paper_bot_v17.py" "$@" ;;
    options) run_py "$PROJECT_ROOT/bots/options" "options_etf_paper_bot_v4.py" "$@" ;;
    quantum|quantum-ai) run_py "$PROJECT_ROOT/bots/quantum-ai" "quantum_ai_paper_bot_v2.py" "$@" ;;
    privateai|private-ai) run_py "$PROJECT_ROOT/bots/private-ai" "private_ai_paper_bot_v4.py" "$@" ;;
    all) echo "Start each bot in its own terminal first so failures are visible."; exit 2 ;;
    *) echo "ERROR: Unknown bot: $bot" >&2; usage; exit 1 ;;
  esac
}
analyze_bot() {
  local bot="$1"; shift || true
  case "$bot" in
    crypto) run_py "$PROJECT_ROOT/bots/crypto" "analyze_bot_performance_v17.py" --log-dir "$PROJECT_ROOT/logs/crypto" "$@" ;;
    options) run_py "$PROJECT_ROOT/bots/options" "analyze_options_performance_v4.py" "$@" ;;
    quantum|quantum-ai) run_py "$PROJECT_ROOT/bots/quantum-ai" "analyze_quantum_ai_performance_v2.py" "$@" ;;
    privateai|private-ai) run_py "$PROJECT_ROOT/bots/private-ai" "analyze_private_ai_performance_v4.py" "$@" ;;
    all) "$0" analyze crypto || true; "$0" analyze options || true; "$0" analyze quantum || true; "$0" analyze privateai || true ;;
    *) echo "ERROR: Unknown analysis target: $bot" >&2; usage; exit 1 ;;
  esac
}
start_dashboard() {
  local cc="$PROJECT_ROOT/control-center"
  cd "$cc"
  if [[ -x "./start_control_center_firefox.sh" ]]; then exec ./start_control_center_firefox.sh; fi
  if [[ -f "./app.py" ]]; then require_python; echo "Starting control center at http://127.0.0.1:8765/"; exec "$PYTHON" ./app.py --host 127.0.0.1 --port 8765; fi
  echo "ERROR: Control center files are not installed yet." >&2
  echo "Expected: $cc/start_control_center_firefox.sh or $cc/app.py" >&2
  exit 1
}
status() {
  echo "Project root: $PROJECT_ROOT"; echo "Python:       $PYTHON"; echo "Dashboard:    http://127.0.0.1:8765/"; echo
  for d in "$PROJECT_ROOT/bots/crypto" "$PROJECT_ROOT/bots/options" "$PROJECT_ROOT/bots/quantum-ai" "$PROJECT_ROOT/bots/private-ai" "$PROJECT_ROOT/control-center"; do [[ -d "$d" ]] && echo "OK   $d" || echo "MISS $d"; done
}
cmd="${1:-}"
case "$cmd" in
  start) shift; [[ $# -ge 1 ]] || { usage; exit 1; }; start_bot "$@" ;;
  analyze) shift; [[ $# -ge 1 ]] || { usage; exit 1; }; analyze_bot "$@" ;;
  dashboard) start_dashboard ;;
  status) status ;;
  tree) find "$PROJECT_ROOT" -maxdepth 3 -type d | sort ;;
  -h|--help|help|"") usage ;;
  *) echo "ERROR: Unknown command: $cmd" >&2; usage; exit 1 ;;
esac
CONTROL_SCRIPT
  chmod +x "$dst"
}

write_project_readme() {
  local dst="$PROJECT_ROOT/README_unified_project.md"
  say "Writing unified README: $dst"
  [[ "$DRY_RUN" -eq 1 ]] && { echo "DRY-RUN: write $dst"; return 0; }
  cat > "$dst" <<PROJECT_README
# InvestAI Unified ProjectMain

Local-only paper-trading research project.

Root:

\`\`\`text
$PROJECT_ROOT
\`\`\`

Dashboard:

\`\`\`text
http://127.0.0.1:8765/
\`\`\`

Common commands:

\`\`\`bash
./investai.sh status
./investai.sh dashboard
./investai.sh start crypto --config configs/aggressive_100.json --once
./investai.sh start options --config configs/two_way_default.json --once
./investai.sh start quantum --config configs/quantum_ai_100.json --once
./investai.sh start privateai --config configs/private_ai_100.json --once
./investai.sh analyze all
\`\`\`
PROJECT_README
}

main() {
  case "$ONLY" in all|crypto|options|quantum|privateai|control) ;; *) fail "Unknown --only value: $ONLY" ;; esac
  setup_base_tree
  copy_zips_into_project
  install_shared_venv
  case "$ONLY" in
    all) install_crypto; install_options; install_quantum; install_privateai; install_control_center ;;
    crypto) install_crypto ;; options) install_options ;; quantum) install_quantum ;; privateai) install_privateai ;; control) install_control_center ;;
  esac
  write_investai_control_script
  write_project_readme
  say "Done."
  echo "Next: cd '$PROJECT_ROOT' && ./investai.sh status"
  echo "Dashboard URL: http://127.0.0.1:8765/"
}
main "$@"
