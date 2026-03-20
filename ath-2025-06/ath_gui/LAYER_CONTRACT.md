# ATH GUI Layer Contract

這份文件是後續開發的硬性規範，目標是讓功能分層可維護、可檢查、可擴充。

## 1) 分層定義

- `ath_gui/domain/`
  - 規格、資料結構、純業務規則。
  - 不碰 UI、不碰流程執行器、不直接操作外部程式。
- `ath_gui/infrastructure/`
  - 外部介接：檔案 I/O、BEM bridge、mesh/result 讀取、preview 資料轉換。
- `ath_gui/presentation/`
  - 呈現與互動元件：Tk/Canvas/OpenGL 繪製與視圖元件。
- `ath_gui/application/`
  - 流程協調器（controllers/use-cases），串接 domain + infrastructure + presentation。
- `ath_gui/app.py`
  - 組裝層（composition root），建立視窗、注入 controllers、啟動程式。

## 2) 允許依賴方向

- `domain` -> `domain`
- `infrastructure` -> `domain`, `infrastructure`
- `presentation` -> `domain`, `presentation`
- `application` -> `domain`, `infrastructure`, `presentation`, `application`
- `app/self_test/tools`（組裝層）可依賴上述各層

禁止事項：
- 低層反向依賴高層（例如 `domain` 匯入 `presentation`）。
- 各層直接依賴 root legacy shim（例如 `ath_gui/specs.py` 這類舊入口）。

## 3) Root 檔案策略

`ath_gui/` 根目錄只保留：
- `app.py`, `self_test.py`, `__init__.py`
- 向後相容 shim（短小、僅 re-export）

任何新功能都必須放進對應 layer 資料夾，不可直接塞進 root。

## 4) 開發檢查

提供自動檢查器：
- `python ath_config_gui.py --check-layering`
- `python -c "from ath_gui.tools.check_layering import check_layering, format_layering_report; r=check_layering(); print(format_layering_report(r)); raise SystemExit(0 if r.ok else 1)"`

自測也會包含 layer 檢查，確保分層不回退。
