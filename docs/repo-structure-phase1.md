# ATH_BEM Repo Structure Phase 1

## Target Positioning

這個 repo 的第一階段定位是：

- source repo
- bootstrap scripts
- local machine config
- external workspace

也就是說，repo 內應該只保留：

- 原始碼
- 設定範本
- 啟動入口
- 文件
- bootstrap / doctor 腳本

而執行時產生的 mesh、workspace、solver outputs、temporary diagnostics，應逐步搬到 repo 外部 workspace。

## Current Inventory

### Source code

- `ath-2025-06/ath_gui/`
- `ath-2025-06/bem_solver/`
- `ath-2025-06/optimizer/`
- `ath-2025-06/export/`
- `ath-2025-06/lib/`
- `ath-2025-06/scripts/`
- `requirements-windows.txt`
- `requirements-wsl.txt`

### Runtime / workspace artifacts

- repo root 的 `Autima_1/`, `Autima_1_5/`, `Autima_1_75/`, `Autima_1_8/`, `Tritonia-M/`, `bempp/`, `test/`
- `ath-2025-06/projects/`
- `ath-2025-06/_symmetry_smoke/`
- `ath-2025-06/_tmp_diag/`
- `ath-2025-06/_tmp_plot_quality/`
- `ath-2025-06/athpreview/test/`
- `ath-2025-06/athpreview/_preview_test/`

### Machine-specific settings

- `config/toolchain.local.json` future local file
- `.env` future local file
- `ath-2025-06/ath.cfg` runtime global config materialization point
- `ath-2025-06/ath_gui/ath.cfg` legacy duplicate config
- sample cfg / txt 中仍存在的本機路徑字串

### Toolchain / external binaries

- `ath-2025-06/ath.exe`
- WSL Python venv / `bempp-cl`
- gmsh / gnuplot / vtk / local Python

## Recommended Structure

```text
ATH_BEM/
├─ ath-2025-06/              # app source tree
├─ .env.example
├─ config/
│  ├─ toolchain.local.json.example
│  ├─ templates/
│  └─ drivers/
├─ scripts/
│  ├─ bootstrap/
│  └─ doctor/
├─ docs/
├─ requirements-windows.txt
└─ requirements-wsl.txt
```

## Phase 1 Changes

- 新增 `config/toolchain.local.json.example`
- 新增 `config/templates/ath.global.template.cfg`
- 新增 `scripts/bootstrap/`
- 新增 `scripts/doctor/`
- 新增 `docs/`
- 將 runtime path resolution 改為可由 local config / env override 控制
- 將 workspace 預設位置改為使用者資料目錄下的外部 workspace
- 保留現有 GUI / CLI 入口，不引入 installer / exe packaging

目前 phase 4 已將新流程收斂成：

- `workspace_root/projects/<case>/runs/...`
- `workspace_root/studies/optuna/...`
- `workspace_root/logs`
- `workspace_root/temp`

這代表新產生的 runtime outputs 不再預設寫回 repo。

## Next Files To Rehome Later

- repo root `Autima_*`, `Tritonia-M`, `bempp`, `test`
- `ath-2025-06/projects/`
- `ath-2025-06/_symmetry_smoke/`
- `ath-2025-06/_tmp_diag/`
- `ath-2025-06/_tmp_plot_quality/`
- `ath-2025-06/ath_gui/ath.cfg`
- 所有 sample config 中的 machine-specific absolute paths
