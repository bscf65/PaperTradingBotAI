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

bot_root() {
  case "$1" in
    crypto) echo "$PROJECT_ROOT/bots/crypto" ;;
    options) echo "$PROJECT_ROOT/bots/options" ;;
    quantum|quantum-ai) echo "$PROJECT_ROOT/bots/quantum-ai" ;;
    privateai|private-ai) echo "$PROJECT_ROOT/bots/private-ai" ;;
    *) return 1 ;;
  esac
}

script_candidates() {
  local root="$1" kind="$2" file base rel
  [[ -d "$root" ]] || return 0

  while IFS= read -r -d '' file; do
    base="${file##*/}"
    rel="${file#"$root"/}"

    case "$rel" in
      .venv/*|venv/*|__pycache__/*|logs/*|configs/*) continue ;;
      */.venv/*|*/venv/*|*/__pycache__/*|*/logs/*|*/configs/*) continue ;;
    esac

    case "$kind:$base" in
      start:*[Bb]ot*.py) [[ "$base" != analyze_* ]] && printf '%s\n' "$file" ;;
      analyze:analyze*.py) printf '%s\n' "$file" ;;
    esac
  done < <(find "$root" -type f -name '*.py' -print0)
}

resolve_script() {
  local root="$1" kind="$2" label="$3" candidates count
  [[ -d "$root" ]] || { echo "ERROR: Missing $label directory: $root" >&2; exit 1; }

  candidates="$(script_candidates "$root" "$kind" | sort)"
  count="$(printf '%s\n' "$candidates" | sed '/^$/d' | wc -l | tr -d ' ')"

  case "$count" in
    0)
      echo "ERROR: No $kind Python entry file found under: $root" >&2
      exit 1
      ;;
    1)
      printf '%s\n' "$candidates"
      ;;
    *)
      echo "ERROR: Multiple $kind Python entry files found under: $root" >&2
      printf '%s\n' "$candidates" >&2
      echo "Remove or rename stale candidates so the launcher can choose safely." >&2
      exit 1
      ;;
  esac
}

run_script() {
  local script="$1"
  local bot="${2:-}"
  shift
  if [[ -n "$bot" ]]; then
    shift
  fi
  require_python
  if [[ -n "$bot" ]]; then
    export INVESTAI_LOG_DIR="$(log_dir_for_bot "$bot")"
    mkdir -p "$INVESTAI_LOG_DIR"
  fi
  cd "$(dirname -- "$script")"
  exec "$PYTHON" "$(basename -- "$script")" "$@"
}

log_dir_for_bot() {
  case "$1" in
    crypto) echo "$PROJECT_ROOT/logs/crypto" ;;
    options) echo "$PROJECT_ROOT/logs/options" ;;
    quantum|quantum-ai) echo "$PROJECT_ROOT/logs/quantum-ai" ;;
    privateai|private-ai) echo "$PROJECT_ROOT/logs/private-ai" ;;
    *) return 1 ;;
  esac
}

start_bot() {
  local bot="$1"; shift || true
  case "$bot" in
    all) echo "Start each bot in its own terminal first so failures are visible."; exit 2 ;;
    crypto|options|quantum|quantum-ai|privateai|private-ai)
      run_script "$(resolve_script "$(bot_root "$bot")" start "$bot")" "$bot" "$@"
      ;;
    *) echo "ERROR: Unknown bot: $bot" >&2; usage; exit 1 ;;
  esac
}
analyze_bot() {
  local bot="$1"; shift || true
  case "$bot" in
    all) "$0" analyze crypto || true; "$0" analyze options || true; "$0" analyze quantum || true; "$0" analyze privateai || true ;;
    crypto|options|quantum|quantum-ai|privateai|private-ai)
      run_script "$(resolve_script "$(bot_root "$bot")" analyze "$bot")" "$bot" "$@"
      ;;
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
