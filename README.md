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
