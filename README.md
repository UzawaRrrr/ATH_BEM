# ATH 聲學仿真套件 (ATH Acoustic Simulation Suite)

用於設計與模擬**聲學蛇皭和導波器**的完整工程軟體。提供圖形化配置界面、實時 3D 預覽，以及高效的邊界元素法 (BEM) 聲學求解器。

## 核心功能
- 🎨 **視覺化配置**：直觀的 GUI（支持中文）編輯蛇皭幾何、邊界條件和網格
- 🔍 **實時預覽**：基於 VTK 的 3D 模型與網格即時可視化
- 📊 **聲學仿真**：使用 empp-cl 基於邊界元素法計算外部 Helmholtz 方程
- 📈 **結果分析**：輸出頻域聲壓級 (SPL) 和指向性極座標圖 (Polar Diagram)

## 專案結構

```
ath-2025-06/                    # 主應用目錄
├── ath_config_gui.py          # 應用入口
├── run_ath_gui.bat            # Windows 啟動腳本
│
├── ath_gui/                   # GUI 層（5層架構的表現層）
│   ├── app.py                 # Tkinter 主應用程式
│   ├── opengl_preview.py      # 3D 預覽渲染
│   ├── bem_bridge.py          # BEM 求解器介面
│   ├── bem_specs.py           # BEM 參數設定 UI
│   ├── bem_results.py         # 結果顯示 UI
│   └── [其他 UI 模組]
│
├── bem_solver/                # 聲學求解器
│   ├── solver_core.py         # BEM 核心演算法（基於 bempp-cl）
│   ├── symmetry.py            # 對稱性最佳化（減少計算量）
│   ├── postprocess.py         # SPL 與極座標計算
│   ├── export_results.py      # 結果匯出
│   └── [其他求解工具]
│
├── tests/                     # 測試套件
├── doc/                       # 文件與配置範例 (Autima_*.cfg)
└── export/                    # 匯出腳本

其他目錄 (Autima_*/, bempp/)  # 數據儲存與計算結果
```

## 架構特色
- **5層清潔架構**：Domain → Infrastructure → Application → Presentation → Composition Root
- **自動層級驗證**：	ools/check_layering.py 確保依賴符合架構規則
- **對稱性優化**：利用平面鏡像原理降低網格尺寸，加快計算速度（2-4 倍）

## 工作流程

1. **設計** → 加載 .cfg 配置，在 GUI 中編輯蛇皭輪廓
2. **預覽** → 實時 3D 渲染與網格檢查
3. **配置仿真** → 設定 BEM 參數（頻率、邊界條件、對稱性）
4. **運行求解** → 通過 WSL 橋接調用 Linux 求解器
5. **分析結果** → 查看 SPL 頻率響應和指向性極座標

### Run All 一鍵流程（原本模式）

- 在既有 `BEM` 分頁工具列新增 `Run All 一鍵流程`。
- `Run All` 會自動執行：`ATH -> mesh inspect -> group auto mapping -> BEM -> result loading`。
- 每次執行會建立可回溯 workspace：
  - `ath-2025-06/projects/<case>/runs/<run_id>/input|ath|bempp|meta`
- 你可維持原本欄位填寫習慣，不需要切換到額外模式。
- 舊手動流程（`Run ATH / Inspect Mesh / Run BEM / Reload Results`）維持不變。

## Optuna Objective Scoring Layer

- `ath-2025-06/optimizer/` 提供一套 headless objective/scoring 核心，專門給自動化與 Optuna 使用，不改動既有 GUI 行為。
- 既有流程仍負責 `ATH -> mesh -> solver -> postprocess`；新的 objective 層只負責把已解析結果轉成單一 scalar score，並保留子分數給 trial attrs / debug。
- 目前版本是 pure Optuna 單一目標評分；尚未包含 PCA、多目標 optimizer、surrogate model 或 dashboard。

### Driver-Constrained Preflight Layer

現在 `optimizer/` 另外加入一層專門給 headless study 使用的前置層：

- `driver_profile.py`
  - 定義單體固定物理條件，例如 throat、法蘭、出口角與最短轉接長度。
- `design_space.py`
  - 不再直接讓 Optuna 在鬆散 raw recipe fields 上亂搜，而是先把 unit-space 變數 decode 成該單體專用的設計空間。
- `feasibility.py`
  - 在寫 ATH cfg、跑 mesh、跑 BEM 之前，先判斷幾何是否與單體/產品限制相容。

這樣最佳化流程會變成：

`normalized vars -> design space decode -> activation rules -> feasibility -> recipe -> case runner`

好處是很直接的：

- 固定 throat 的 driver 不會再被最佳化器拿去亂改 throat。
- mouth width / height 會先受 driver throat 比例、target coverage、baffle 寬高與 depth 限制。
- 幾何明顯不合理的 trial 會在 expensive pipeline 前就 hard fail，避免浪費 study budget。

### Driver Profile JSON

範例檔放在：

- `config/drivers/example_compression_driver.json`

最小格式如下：

```json
{
  "driver_id": "jbl_2409h",
  "name": "JBL 2409H",
  "driver_type": "compression_driver",
  "throat_diameter_mm": 25.0,
  "min_adapter_length_mm": 8.0,
  "preferred_min_mouth_to_throat_ratio": 3.0,
  "preferred_max_coverage_deg": 110.0
}
```

若 study 沒有明確提供 `driver_profile` / `product_constraints`，`study_runner` 會先從 base recipe 推估 fallback 約束，讓既有 GUI/CLI 流程維持可用；但正式最佳化仍建議提供明確 JSON 與產品尺寸限制。

### Study Runner 用法

```python
from pathlib import Path

from ath_gui.domain.design_recipe import DesignRecipe
from optimizer.driver_profile import ProductConstraints, load_driver_profile
from optimizer.study_runner import OptunaStudyConfig, run_optuna_study

base_recipe = DesignRecipe.from_dict(...)
driver_profile = load_driver_profile(Path("config/drivers/example_compression_driver.json"))
product_constraints = ProductConstraints(
    max_baffle_width_mm=280.0,
    max_baffle_height_mm=220.0,
    max_depth_mm=240.0,
    target_bw_h_deg=90.0,
    target_bw_v_deg=60.0,
    target_low_freq_hz=1000.0,
)

config = OptunaStudyConfig(
    trials=20,
    stage="final",
    driver_profile=driver_profile,
    product_constraints=product_constraints,
    enqueue_base=True,
)

result = run_optuna_study(
    base_recipe=base_recipe,
    case_runner=case_runner,
    config=config,
)
```

執行時 study runner 會先：

- 建立 `driver_profile + product_constraints + design_space`
- 先 enqueue 一組 driver-aware baseline seed
- 先做 `validate_params_against_design_space(...)`
- 再做 `validate_recipe_against_driver(...)`
- 若 hard fail，直接回傳 catastrophic pre-score penalty，不呼叫 case runner
- 若只有 soft issues，則把 soft penalty 加到最終 objective 前面

### 分層責任

- `case runner`：執行既有 ATH / mesh / BEM / postprocess 自動化流程，回傳 `CaseResult`。
- `result bridge`：把 `CaseResult` 或既有 dict bundle 轉成 `PolarData + GeometryStatus`。
- `objective/scorer`：只負責計算 scalar objective 與 component scores。

case runner 不直接回傳 `PolarData`，是為了把「流程輸出」與「聲學評分模型」解耦。這樣同一份 run artifacts 可以重跑不同 scorer，也讓 legacy fallback 與 canonical payload 可以共存。

### Canonical Artifacts

- `optimizer_payload.npz`
- `optimizer_status.json`

bridge 會優先讀這兩個 canonical artifacts。`optimizer_payload.npz` 由 `np.savez_compressed` 儲存 scorer 所需陣列；`optimizer_status.json` 則保存 mesh / geometry / solver 狀態，不把複雜狀態硬塞進 npz。

### Legacy Fallback Artifacts

- `summary.json`
- `mesh_info.json`
- `polar.csv`
- `solution.npz`

若 canonical payload 不存在，bridge 會回退到 legacy artifacts。這讓現有流程不需要一次重寫，也能先用 bridge 進 Optuna。

### 最小用法

```python
from optimizer.objective import optuna_objective_wrapper
from optimizer.score_defaults import build_default_objective_config

config = build_default_objective_config(stage="final")

def objective(trial):
    return optuna_objective_wrapper(
        trial,
        case_runner=case_runner,
        config=config,
    )
```

若你只想在本地 smoke test scorer，可執行：

```bash
cd ath-2025-06
python -m optimizer.demo
python -m optimizer.demo --mode bridge
python -m optimizer.demo --mode study
```

### 建議執行環境

- 建議拓樸是 `Windows 本地 .venv + WSL solver venv`。
- 本地 `.venv` 負責：
  - `ath.exe`
  - workspace / manifest / bridge
  - Optuna / objective scorer
- WSL venv 負責：
  - `bempp-cl`
  - `meshio`
  - `scipy`
  - `gmsh`

原因很直接：`ath.exe` 是 Windows 程式，而既有 BEM 流程本來就已經是 Windows -> WSL bridge。這樣可以最大化重用現有 pipeline，也避免把整個 GUI/ATH 執行鏈硬搬進 WSL。

可先用 doctor 檢查環境：

```bash
cd ath-2025-06
..\.venv\Scripts\python.exe scripts/check_optimizer_env.py
```

若 doctor 顯示 `Recommended topology: hybrid`，就表示建議的最佳化環境已就緒。

### Headless Runner 與正式 Optuna 入口

- `optimizer.headless_case_runner.HeadlessCaseRunner`
  - 重用既有 `ATH -> mesh inspect -> group mapping -> BEM` 流程
  - 回傳 `CaseResult`
  - 會在 workspace `bempp/` 根目錄輸出合併後的 `optimizer_payload.npz` / `optimizer_status.json`
- `scripts/run_optuna.py`
  - 正式 CLI 入口
  - 會建立 study、呼叫 headless runner、寫出 `best_trial.json` 與 `trials.json`
- `optimizer.study_runner`
  - CLI 與 GUI 共用的 study orchestration service
  - 統一處理 Optuna sampler、trial event、study artifact 落地

如果 `design_recipe.json` 只是高階 recipe，而完整幾何細節存在某份已驗證的 `horn.cfg`，請把那份 `horn.cfg` 當 base template 傳入。這很重要，因為 `DesignRecipe` 只覆蓋部分 ATH 欄位，最佳化通常應該在一份「已知可生成幾何」的 base horn state 上做相對調整。

最小實跑範例：

```bash
cd ath-2025-06
..\.venv\Scripts\python.exe scripts/run_optuna.py ^
  --recipe projects/optuna_smoke_recipe3.json ^
  --base-horn-cfg projects/config/runs/20260330_043549/input/horn.cfg ^
  --trials 1 ^
  --stage coarse ^
  --planes XZ ^
  --study-name optuna_cli_smoke ^
  --study-dir projects/optuna_cli_smoke_artifacts
```

實務上正式最佳化時，通常建議：

- `--planes XZ YZ`：讓 scorer 取得 H/V 兩個平面
- `--stage coarse` 先找方向，再切到 `refine` / `final`
- `--base-horn-cfg` 指向一份已成功跑過的 `input/horn.cfg`
- `--recipe` 指向對應的 `design_recipe.json`

### GUI 內建最佳化控制

- GUI 現在新增左側 `Optimize` 分頁與右側 `Study` 工作區。
- `Optimize` 分頁只負責 study/control 參數：
  - stage
  - trials
  - planes
  - study name / dir / storage / seed
  - target beamwidth
- BEM backend、WSL venv、conda/local solver 等執行環境設定，仍沿用既有 `BEM` 分頁欄位，不重複維護第二套設定。
- 按下 `開始最佳化` 後，GUI 會：
  - 取目前 GUI 的 horn/global/BEM state 當 base template
  - 由 `OptimizationController` 建立 headless runner
  - 呼叫 `optimizer.study_runner.run_optuna_study(...)`
  - 即時把 trial log、best score、best params 寫到 `Study` 頁面
- `套用最佳結果` 會把 best trial 中可直接映射到 `DesignRecipe` 的欄位回寫到目前 GUI，方便再手動微調或直接 `Run All`。

這裡刻意沒有讓 case runner 直接回傳 `PolarData`。GUI / CLI / batch pipeline 都只需要產生 `CaseResult + artifacts`；bridge 與 scorer 仍維持可替換，這樣 legacy outputs、canonical payload 與未來其他評分器可以共存。

### Component 物理意義

- `coverage`: 追蹤目標離軸曲線，或在無 target curve 時改用 beamwidth tracking。
- `cd`: constant directivity 穩定度，量測各角度在頻帶內是否維持一致的相對衰減。
- `hom`: HOM / diffraction proxy，由角度單調性違反、角向粗糙度、頻向粗糙度與 edge kink 合成。
- `room`: on-axis、listening window、sound power 的平滑度代理，偏向室內主觀可聽結果。
- `di`: DI 與 beamwidth 的頻向平滑度，避免 directivity index 劇烈抖動。
- `load`: throat reflection / radiation efficiency 等負載代理的保留介面；無資料時會標記 unavailable 並回傳 0。
- `geom` / `hard`: 幾何品質與 catastrophic fail 懲罰，將 mesh/solver/geometry 錯誤與平滑度指標明確分層。

## 技術棧
- **GUI**：Tkinter、matplotlib、VTK
- **求解器**：bempp-cl (OpenCL 加速)、NumPy、SciPy
- **網格**：Gmsh、meshio (.msh 格式)
- **配置**：YAML/JSON（.cfg 和 job.json）
- **整合**：Windows GUI ↔ WSL2 Bash 子進程

## 快速開始

```bash
# 啟動 GUI
python ath-2025-06/ath_config_gui.py
# 或
.\run_ath_gui.bat
```

1. 加載範例配置（doc/Autima_*.cfg）
2. 在 GUI 中調整蛇皭參數
3. 預覽 3D 模型
4. 配置 BEM 求解參數並執行仿真
5. 查看頻域響應和指向性結果
