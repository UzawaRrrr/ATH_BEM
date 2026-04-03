# Repo And Workspace

## Separation

`ATH_BEM` 現在區分成兩個角色：

- repo: source tree、文件、bootstrap、設定範本
- workspace: 實際執行輸出、study artifacts、logs、temp

repo 可以 clone 到任何路徑；workspace 則應該是外部可寫資料目錄，不跟 source tree 混在一起。

## Default Workspace Root

`workspace_root` 的決定順序是：

1. 作業系統環境變數
2. repo root 的 `.env`
3. `config/toolchain.local.json`
4. legacy `config/machine.local.json`
5. repo-safe 預設值

預設值：

- Windows: `%LOCALAPPDATA%\\ATH_BEM\\workspace`
- Linux / WSL: `${XDG_DATA_HOME:-~/.local/share}/ath_bem/workspace`

## Derived Layout

程式會從 `workspace_root` 派生這些目錄：

- `projects/`
  - `projects/<case>/runs/<run_id>/input|ath|bempp|meta`
- `studies/`
  - `studies/optuna/<study_name>/best_trial.json|study_config.json|trials.json`
- `logs/`
- `temp/`

## What Stays In Repo

repo 內保留：

- `ath-2025-06/` source code
- `config/templates/` template config
- `config/drivers/` sample driver profiles
- `ath-2025-06/doc/` sample cfg
- `ath-2025-06/projects/*.json` legacy sample recipes

repo 不應再作為預設輸出位置。

## Migration Intent

目前 repo 裡仍有一些 historical runtime artifacts，例如：

- `Autima_*`
- `Tritonia-M`
- `bempp/`
- `ath-2025-06/_symmetry_smoke/`
- `ath-2025-06/_tmp_diag/`
- `ath-2025-06/_tmp_plot_quality/`

這些現在視為 legacy reference data。新的 GUI / bootstrap / Optuna 流程，預設都應寫到 external workspace。
