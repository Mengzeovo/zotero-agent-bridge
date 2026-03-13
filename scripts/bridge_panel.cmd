@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
where pythonw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  start "" pythonw "%SCRIPT_DIR%bridge_panel.py" %*
) else (
  start "" python "%SCRIPT_DIR%bridge_panel.py" %*
)
