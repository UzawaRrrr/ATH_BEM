#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

TOOLCHAIN_CONFIG="${ATH_TOOLCHAIN_CONFIG:-${ATH_MACHINE_CONFIG:-${REPO_ROOT}/config/toolchain.local.json}}"
if [[ ! -f "${TOOLCHAIN_CONFIG}" && -f "${REPO_ROOT}/config/machine.local.json" ]]; then
  TOOLCHAIN_CONFIG="${REPO_ROOT}/config/machine.local.json"
fi

JSON_WSL_VENV=""
if [[ -f "${TOOLCHAIN_CONFIG}" ]]; then
  JSON_WSL_VENV="$(python3 - "${TOOLCHAIN_CONFIG}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)
print(str(payload.get("wsl_venv", "")).strip())
PY
)"
fi

VENV_PATH="${1:-${ATH_WSL_VENV:-${JSON_WSL_VENV:-$HOME/venvs/bempp-wsl}}}"
REQ_FILE="${REPO_ROOT}/requirements-wsl.txt"

if [[ ! -f "${REQ_FILE}" ]]; then
  echo "Requirements file not found: ${REQ_FILE}" >&2
  exit 1
fi

if [[ ! -f "${TOOLCHAIN_CONFIG}" && ! -f "${ENV_FILE}" ]]; then
  echo "No local WSL toolchain config found; using repo-safe defaults."
  echo "Tip: run the Windows bootstrap with -InitLocalConfig if you want editable local templates."
fi

if [[ ! -x "${VENV_PATH}/bin/python" ]]; then
  echo "Creating WSL venv at ${VENV_PATH}"
  python3 -m venv "${VENV_PATH}"
fi

"${VENV_PATH}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_PATH}/bin/python" -m pip install -r "${REQ_FILE}"

echo ""
echo "Running WSL environment doctor..."
( cd "${REPO_ROOT}" && "${VENV_PATH}/bin/python" -m ath_bem doctor wsl --venv "${VENV_PATH}" --check-solver-cli )

echo ""
echo "WSL bootstrap complete."
echo "Venv: ${VENV_PATH}"
echo "Requirements: ${REQ_FILE}"
echo "Default external workspace (if not overridden): \${XDG_DATA_HOME:-~/.local/share}/ath_bem/workspace"
echo "Verify later with:"
echo "  (cd ${REPO_ROOT} && ${VENV_PATH}/bin/python -m ath_bem doctor wsl --venv ${VENV_PATH} --check-solver-cli)"
