# Bootstrap Guide

## 1. Clone Repo

```powershell
git clone <repo-url> ATH_BEM
cd ATH_BEM
```

## 2. Bootstrap Windows

```powershell
pwsh ./scripts/bootstrap/bootstrap_windows.ps1 -InitLocalConfig
```

這會：

- 建立 `.venv`
- 安裝 [requirements-win.txt](d:/python/ATH_BEM/requirements-win.txt)
- 可選建立 `config/toolchain.local.json` 與 `.env`
- 執行 runtime / Windows doctor

若你要跳過驗證：

```powershell
pwsh ./scripts/bootstrap/bootstrap_windows.ps1 -SkipChecks
```

## 3. Bootstrap WSL

在 WSL 裡進到同一個 repo：

```bash
cd /mnt/d/python/ATH_BEM
bash scripts/bootstrap/bootstrap_wsl.sh
```

若想指定 venv 路徑：

```bash
bash scripts/bootstrap/bootstrap_wsl.sh ~/venvs/bempp-wsl
```

這會：

- 建立 solver venv
- 安裝 [requirements-wsl.txt](d:/python/ATH_BEM/requirements-wsl.txt)
- 執行 WSL doctor 與 solver CLI 檢查

## 4. Local Config

若 Windows bootstrap 時使用了 `-InitLocalConfig`，會產生：

- `config/toolchain.local.json`
- `.env`

請依本機狀況調整：

- `windows_venv`
- `ath_exe`
- `ath_runtime_dir`
- `ath_global_config`
- `workspace_root`
- `logs_root`
- `temp_root`
- `wsl_venv`
- `solver_path`

若 `workspace_root` 留白，預設會使用使用者資料目錄，而不是 repo 旁邊的資料夾：

- Windows: `%LOCALAPPDATA%\\ATH_BEM\\workspace`
- Linux / WSL: `${XDG_DATA_HOME:-~/.local/share}/ath_bem/workspace`

衍生輸出會落在：

- `<workspace_root>/projects/<case>/runs/...`
- `<workspace_root>/studies/optuna/...`
- `<workspace_root>/logs`
- `<workspace_root>/temp`

更完整的 repo / workspace 分工見 [workspace.md](d:/python/ATH_BEM/docs/workspace.md)。

## 5. Verify

Windows:

```powershell
python -m ath_bem doctor runtime
python -m ath_bem doctor windows --run-self-test
python -m ath_bem gui --self-test
```

WSL:

```bash
~/venvs/bempp-wsl/bin/python -m ath_bem doctor wsl --venv ~/venvs/bempp-wsl --check-solver-cli
```

## 6. Launch

```powershell
python -m ath_bem gui
# 或使用 wrapper
ath-2025-06\run_ath_gui.bat
pwsh ./scripts/launch_gui.ps1
```
