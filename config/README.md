# Config Layout

這個目錄現在用來放兩種內容：

- repo 可追蹤的設定範本
- 少量可追蹤的 example config

目前建議：

- `toolchain.local.json.example`
  - clone 後複製成 `toolchain.local.json`
  - 只放本機路徑與 workspace/solver 拓樸
- `templates/`
  - 放可重建的設定範本
- `drivers/`
  - 放可追蹤的 driver profile 範例

另外，repo root 的 `.env.example` 可作為 launcher / shell override。
建議角色分工：

- `config/toolchain.local.json`
  - 結構化本機設定
- `.env`
  - shell / launcher override

若 `workspace_root` / `logs_root` / `temp_root` 留白，程式會使用 repo-safe 的使用者資料目錄預設：

- Windows: `%LOCALAPPDATA%\\ATH_BEM\\workspace`
- Linux / WSL: `${XDG_DATA_HOME:-~/.local/share}/ath_bem/workspace`

目前仍混有一些 legacy runtime artifacts，例如：

- `ABEC_FreeStanding/`

這些內容後續應逐步移出 repo 設定區，轉成：

- external workspace runtime data
- 或真正的 template/example fixture
