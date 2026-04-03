# 異地 Clone 快速開始

## 目標

這份流程給「新機器第一次 clone `ATH_BEM`」使用。完成後應可：

- 建立 Windows orchestration / GUI 環境
- 建立 WSL solver 環境
- 使用 local config 管理本機差異
- 從 repo root 啟動 GUI、optimizer、doctor
- 將 outputs 寫到 external workspace

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

- 建立本機 `.venv`
- 安裝 Windows 端依賴
- 建立 `config/toolchain.local.json` 與 `.env` 範本
- 執行 runtime / Windows doctor

## 3. Bootstrap WSL

在 WSL 內進到同一份 repo：

```bash
cd /mnt/d/python/ATH_BEM
bash scripts/bootstrap/bootstrap_wsl.sh
```

## 4. 檢查 Local Config

視需要調整：

- `config/toolchain.local.json`
- `.env`

常見可調整項目：

- `windows_venv`
- `python_exe`
- `wsl_venv`
- `solver_path`
- `ath_exe`
- `workspace_root`

若留白，會使用 repo-safe 預設值：

- Windows workspace: `%LOCALAPPDATA%\\ATH_BEM\\workspace`
- Linux / WSL workspace: `${XDG_DATA_HOME:-~/.local/share}/ath_bem/workspace`

## 5. 驗證

Windows:

```powershell
python -m ath_bem doctor runtime
python -m ath_bem doctor windows --run-self-test
python -m ath_bem doctor optimizer
```

WSL:

```bash
~/venvs/bempp-wsl/bin/python -m ath_bem doctor wsl --venv ~/venvs/bempp-wsl --check-solver-cli
```

## 6. 啟動

GUI:

```powershell
python -m ath_bem gui
```

Optimizer:

```powershell
python -m ath_bem optimizer --recipe ath-2025-06/projects/optuna_smoke_recipe3.json --trials 1
```

## 7. Outputs 在哪裡

預設 external workspace 結構：

- `workspace/projects/<case>/runs/<run_id>/...`
- `workspace/studies/optuna/<study_name>/...`
- `workspace/logs`
- `workspace/temp`

repo 本身不應再是預設輸出位置。

