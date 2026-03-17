@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" goto run_venv
where py >nul 2>nul && goto run_py
goto run_python

:run_venv
echo [INFO] Using project venv: %SCRIPT_DIR%.venv\Scripts\python.exe
"%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%scripts\run_gui.py" %*
goto done

:run_py
echo [INFO] Using launcher: py -3
py -3 "%SCRIPT_DIR%scripts\run_gui.py" %*
goto done

:run_python
echo [INFO] Using PATH python
python "%SCRIPT_DIR%scripts\run_gui.py" %*

:done
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] GUI exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
