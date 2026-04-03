# 目前仍有限制的項目

## 平台與工具鏈

- GUI 與 `ath.exe` 仍以 Windows 為主要執行環境，尚未支援原生 Linux / macOS GUI 工作流。
- 建議 solver 拓樸仍是 `Windows GUI + WSL solver venv`；目前不是完整的跨平台單一 Python 環境。
- bootstrap 假設機器上已安裝可用的 Python 3 與 WSL，不負責安裝這些基礎工具。

## 外部依賴

- `ath.exe` 仍是 repo 內既有二進位，沒有獨立的 toolchain acquisition 流程。
- `gmsh`、`vtk`、`bempp-cl` 等依賴仍由 pip / 既有環境條件取得，沒有更高層的 capability discovery。
- WSL 端仍可能受到本機 WSL / PATH 狀態影響；例如目前可見的 `wsl: Failed to translate ...` 警告雖不阻塞，但仍屬環境噪音。

## Repo 狀態

- repo 內仍保留一些 legacy runtime artifacts，例如 `Autima_*`、`Tritonia-M`、`bempp/`、`ath-2025-06/_symmetry_smoke/`。
- 這些 historical artifacts 已不再是新流程的預設輸出位置，但仍尚未完全自 repo 追蹤內容中清出。

## 設定管理

- local config 目前仍是 path-centric 設定，還不是完整 schema 驗證或 UI 化設定流程。
- `config/machine.local.json` 仍保留為 legacy fallback，相容舊環境但不再是主流程。

## 啟動與封裝

- 專案目前是 source-tree launcher 模式，不是正式 packaging / installer。
- 這符合當前目標，但也表示使用者仍需從 repo root 與對應 Python 環境啟動。

