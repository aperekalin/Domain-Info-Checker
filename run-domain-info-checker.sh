#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <input.csv>"
  exit 2
fi

CSV_FILE="$1"
if [[ ! -f "$CSV_FILE" ]]; then
  echo "Error: file not found: $CSV_FILE"
  exit 2
fi

if [[ -z "${WHOISXMLAPI_API_KEY:-}" ]]; then
  echo "Error: WHOISXMLAPI_API_KEY is not set."
  echo "Run like:"
  echo "  WHOISXMLAPI_API_KEY=\"your_key\" $0 domains.csv"
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv-domain-info-checker"

# Prefer Homebrew python3 if present, otherwise fall back to python3 in PATH.
if [[ -x "/opt/homebrew/bin/python3" ]]; then
  PYTHON_BIN="/opt/homebrew/bin/python3"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Error: python3 not found. Install Python 3 (Homebrew recommended)."
  exit 2
fi

# Create venv if missing
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# Ensure pip exists in the venv (mac-safe). Some venvs may be created without pip.
python -m ensurepip --upgrade >/dev/null 2>&1 || true

# Install dependencies (doesn't require a pip executable in PATH)
python -m pip install --upgrade pip >/dev/null
python -m pip install requests >/dev/null

# Run the checker
python "${SCRIPT_DIR}/domain_info_checker.py" "$CSV_FILE"