@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."
set "LAUNCH_PY="

if exist "%REPO_ROOT%\.env" (
  for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%REPO_ROOT%\.env") do (
    if not "%%~A"=="" set "%%~A=%%~B"
  )
)

if defined ATH_PYTHON (
  if exist "%ATH_PYTHON%" (
    set "LAUNCH_PY=%ATH_PYTHON%"
  )
)
if not defined LAUNCH_PY if defined ATH_PYTHON (
  if exist "%REPO_ROOT%\%ATH_PYTHON%" (
    set "LAUNCH_PY=%REPO_ROOT%\%ATH_PYTHON%"
  )
)
if not defined LAUNCH_PY if defined ATH_WINDOWS_VENV (
  if exist "%ATH_WINDOWS_VENV%\Scripts\python.exe" (
    set "LAUNCH_PY=%ATH_WINDOWS_VENV%\Scripts\python.exe"
  )
)
if not defined LAUNCH_PY if defined ATH_WINDOWS_VENV (
  if exist "%REPO_ROOT%\%ATH_WINDOWS_VENV%\Scripts\python.exe" (
    set "LAUNCH_PY=%REPO_ROOT%\%ATH_WINDOWS_VENV%\Scripts\python.exe"
  )
)
if not defined LAUNCH_PY if exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
  set "LAUNCH_PY=%REPO_ROOT%\.venv\Scripts\python.exe"
)

if defined LAUNCH_PY (
    pushd "%REPO_ROOT%" >nul
    "%LAUNCH_PY%" -m ath_bem gui %*
    set "EXITCODE=%errorlevel%"
    popd >nul
    exit /b %EXITCODE%
)

where py >nul 2>nul
if not errorlevel 1 (
  pushd "%REPO_ROOT%" >nul
  py -3 -m ath_bem gui %*
  set "EXITCODE=%errorlevel%"
  popd >nul
  exit /b %EXITCODE%
)
where python >nul 2>nul
if not errorlevel 1 (
  pushd "%REPO_ROOT%" >nul
  python -m ath_bem gui %*
  set "EXITCODE=%errorlevel%"
  popd >nul
  exit /b %EXITCODE%
)
where pwsh >nul 2>nul
if not errorlevel 1 (
  pwsh -ExecutionPolicy Bypass -File "%REPO_ROOT%\scripts\launch_gui.ps1" %*
  exit /b %errorlevel%
)

echo Python launcher not found for ATH_BEM.
echo Please run:
echo   powershell -ExecutionPolicy Bypass -File scripts\bootstrap\bootstrap_windows.ps1 -InitLocalConfig
exit /b 1
