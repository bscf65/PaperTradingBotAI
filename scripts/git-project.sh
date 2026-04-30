#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec git --git-dir="$PROJECT_ROOT/.git-real" --work-tree="$PROJECT_ROOT" "$@"
