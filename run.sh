#!/usr/bin/env bash
#
# run.sh - Bootstrap and launch MailGuard.
#
# Responsibilities:
#   1. Verify Python >= 3.11 is available.
#   2. Create (or reuse) a local virtual environment.
#   3. Install/upgrade dependencies.
#   4. Execute the MailGuard CLI, forwarding all arguments.
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11

log() { printf '[run.sh] %s\n' "$1"; }
die() { printf '[run.sh] ERROR: %s\n' "$1" >&2; exit 1; }

find_python() {
    for candidate in python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

check_python_version() {
    local py="$1"
    "$py" - <<EOF
import sys
major, minor = sys.version_info[:2]
sys.exit(0 if (major, minor) >= (${MIN_PYTHON_MAJOR}, ${MIN_PYTHON_MINOR}) else 1)
EOF
}

PYTHON_BIN="$(find_python)" || die "No suitable python3 interpreter found on PATH."
check_python_version "$PYTHON_BIN" || die "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required. Found: $("$PYTHON_BIN" --version)"
log "Using interpreter: $("$PYTHON_BIN" --version)"

if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment at ${VENV_DIR}"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

log "Installing/upgrading dependencies"
pip install --quiet --upgrade pip
pip install --quiet -r "${PROJECT_ROOT}/requirements.txt"
pip install --quiet -e "${PROJECT_ROOT}"

log "Launching MailGuard"
exec python -m cli.main "$@"
