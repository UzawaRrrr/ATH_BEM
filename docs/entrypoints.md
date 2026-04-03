# Source-Tree Entrypoints

## Recommended Repo-Root Entrypoints

完成 bootstrap 後，建議先 `cd` 到 repo root，再使用這些標準入口：

### GUI

```powershell
python -m ath_bem gui
```

Windows 也可用 wrapper：

```powershell
ath-2025-06\run_ath_gui.bat
# 或
pwsh ./scripts/launch_gui.ps1
```

### Optimizer

```powershell
python -m ath_bem optimizer --recipe ath-2025-06/projects/optuna_smoke_recipe3.json --trials 1
```

若你已進到 `ath-2025-06/`，也可以用 package-style 相容入口：

```powershell
python -m optimizer --recipe projects/optuna_smoke_recipe3.json --trials 1
```

### Doctor / Checks

```powershell
python -m ath_bem doctor runtime
python -m ath_bem doctor windows --run-self-test
python -m ath_bem doctor optimizer
```

WSL:

```bash
~/venvs/bempp-wsl/bin/python -m ath_bem doctor wsl --venv ~/venvs/bempp-wsl --check-solver-cli
```

## Compatibility Layer

下列舊入口仍保留，但現在屬於相容層：

- `ath-2025-06/run_ath_gui.bat`
- `ath-2025-06/ath_config_gui.py`
- `ath-2025-06/scripts/run_optuna.py`
- `ath-2025-06/scripts/check_optimizer_env.py`

新的建議做法是優先使用 `python -m ath_bem ...`，因為它從 repo root 出發，較不依賴特定工作目錄或某台機器的既有 `.venv` 位置。
