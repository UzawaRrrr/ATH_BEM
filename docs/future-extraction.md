# 未來若要支援更多平台或工具鏈，建議再抽離的層

## 1. Toolchain Provider Layer

目前 `ath.exe`、Windows Python、WSL venv、solver entry 仍是以路徑設定為主。
下一步可抽成 toolchain provider layer，讓系統辨識：

- Windows local Python
- WSL Python
- Conda env
- Docker / container solver
- remote solver service

這樣可把「如何找到工具」從 GUI / optimizer / bootstrap 中再分離一次。

## 2. Runtime Config Schema Layer

目前 local config 已集中，但還是偏自由格式的 JSON / `.env`。
未來可加入：

- 結構化 schema
- 型別驗證
- 版本升級策略
- config migration / doctor autofix

這樣跨機器交接時會更穩定。

## 3. External Binary Acquisition Layer

目前 repo 內仍直接依賴現成的 `ath.exe`。
若之後要支援更多機器或 CI，可考慮抽離：

- binary manifest
- checksum / version check
- optional download / sync workflow
- cache location policy

仍不一定要做 installer，但可以讓 toolchain 取得方式更可控。

## 4. Solver Service Boundary

現在 solver 還是透過本機 bridge 呼叫 CLI。
若未來要支援更多平台，可考慮把 solver 抽成更穩定的 service boundary：

- CLI contract normalization
- job spec schema
- result artifact schema
- optional background worker / RPC service

這樣 GUI / optimizer / batch 都能共享更穩定的求解介面。

## 5. Template / Fixture / Artifact Separation

目前 repo 內仍混有 sample recipe、fixture、legacy artifacts。
若要再往前走，建議更明確分成：

- `templates/`
- `samples/`
- `fixtures/`
- external workspace outputs

這樣文件、測試、實際執行資料會更容易維護。

## 6. Packaging Boundary For Python Entry Points

現在已經有 `python -m ath_bem ...` 的 source-tree 入口。
若之後要支援更多平台，可進一步抽成輕量 packaging boundary，例如：

- `pyproject.toml`
- console scripts
- optional editable install

但這應該是為了入口一致性與維護，不是為了改成 installer。

