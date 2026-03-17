#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "[FAIL] python/python3 not found in PATH"
    exit 1
  fi
fi

echo "[INFO] Root directory: ${ROOT_DIR}"
echo "[INFO] Python binary: ${PYTHON_BIN}"

if [[ -n "${WSL_DISTRO_NAME:-}" ]] && [[ -d "${VENV_DIR}" ]] && [[ ! -f "${VENV_DIR}/bin/activate" ]] && [[ -f "${VENV_DIR}/Scripts/activate" ]]; then
  VENV_DIR="${ROOT_DIR}/.venv_wsl"
  echo "[WARN] Detected Windows virtual environment at .venv while running in WSL."
  echo "[INFO] Using WSL virtual environment at ${VENV_DIR} instead."
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[INFO] Creating virtual environment at ${VENV_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  echo "[INFO] Reusing existing virtual environment at ${VENV_DIR}"
fi

if [[ -f "${VENV_DIR}/bin/activate" ]]; then
  source "${VENV_DIR}/bin/activate"
  ACTIVATE_PATH="${VENV_DIR}/bin/activate"
elif [[ -f "${VENV_DIR}/Scripts/activate" ]]; then
  source "${VENV_DIR}/Scripts/activate"
  ACTIVATE_PATH="${VENV_DIR}/Scripts/activate"
else
  echo "[FAIL] Could not find activation script inside ${VENV_DIR}"
  exit 1
fi
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r "${ROOT_DIR}/requirements.txt"

if [[ "${INSTALL_DEV:-0}" == "1" ]] && [[ -f "${ROOT_DIR}/requirements-dev.txt" ]]; then
  python -m pip install -r "${ROOT_DIR}/requirements-dev.txt"
fi

mkdir -p "${ROOT_DIR}/logs" "${ROOT_DIR}/outputs" "${ROOT_DIR}/outputs/mesh" "${ROOT_DIR}/outputs/solver" "${ROOT_DIR}/outputs/tmp"

if [[ ! -f "${ROOT_DIR}/config/local_paths.yaml" ]] && [[ -f "${ROOT_DIR}/config/local_paths.example.yaml" ]]; then
  cp "${ROOT_DIR}/config/local_paths.example.yaml" "${ROOT_DIR}/config/local_paths.yaml"
  echo "[INFO] Created config/local_paths.yaml from example"
fi

if [[ "${INSTALL_ATH:-0}" == "1" ]]; then
  echo "[INFO] Installing ATH from official release"
  python "${ROOT_DIR}/scripts/install_ath.py"
fi

echo "[INFO] Running dependency check (mock mode baseline)"
python "${ROOT_DIR}/scripts/check_dependencies.py" --mode mock || true

echo "[DONE] Bootstrap complete."
echo "[NEXT] source ${ACTIVATE_PATH}"
echo "[NEXT] python scripts/smoke_test.py --mode mock"
