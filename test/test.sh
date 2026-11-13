#!/usr/bin/env bash
#
# test/test.sh — oMLX Prompt Shrink test runner (single file).
#
# Usage:
#
#   ./test/test.sh                 # install dev deps, then ruff + pytest
#   ./test/test.sh --lint          # ruff only, no tests
#   ./test/test.sh --no-install    # skip `pip install -r requirements-dev.txt`
#   ./test/test.sh --only test/omlx_prompt_shrink_tests.py::test_trim_leaves_short_lists_untouched
#                                  # run one file or one test (repeatable)
#   ./test/test.sh --help          # show this help
#
# The interpreter is the project `.venv` when present, otherwise `python3`
# (override with the PYTHON environment variable).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN_LINT=1
RUN_TESTS=1
INSTALL=1
ONLY=()

usage() {
    sed -n '3,16p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lint) RUN_TESTS=0 ;;
        --no-install) INSTALL=0 ;;
        --only) shift; ONLY+=("${1:-}") ;;
        -h | --help) usage; exit 0 ;;
        *)
            echo "unknown flag: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
else
    PY="${PYTHON:-python3}"
fi

if [[ "$INSTALL" == 1 ]]; then
    echo "== install =="
    "$PY" -m pip install -q -r requirements-dev.txt
fi

if [[ "$RUN_LINT" == 1 ]]; then
    echo "== ruff =="
    "$PY" -m ruff check .
fi

if [[ "$RUN_TESTS" == 1 ]]; then
    echo "== pytest =="
    if [[ ${#ONLY[@]} -gt 0 ]]; then
        "$PY" -m pytest -q "${ONLY[@]}"
    else
        "$PY" -m pytest -q
    fi
fi
