# Doctor Scripts

建議在 bootstrap 後使用這些檢查腳本：

- `doctor_runtime.py`
  - 檢查 repo / runtime layout / `.env` / `toolchain.local.json` 解析結果
- `check_windows_env.py`
  - 檢查 Windows 端 Python 模組與可選 self-test
- `check_wsl_env.py`
  - 在 WSL 內檢查 solver Python 環境與 `solver_cli.py --help`

舊的最佳化環境檢查腳本仍保留在：

- `ath-2025-06/scripts/check_optimizer_env.py`

現在建議優先用 `scripts/doctor/` 下的新入口，因為它們和 repo root bootstrap 流程是一致的。

repo root 的標準啟動方式則是：

- `python -m ath_bem doctor runtime`
- `python -m ath_bem doctor windows --run-self-test`
- `python -m ath_bem doctor wsl --check-solver-cli`
- `python -m ath_bem doctor optimizer`
