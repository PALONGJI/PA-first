@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 set "PY_CMD=py"

if not defined PY_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
  echo Python was not found.
  echo Install Python or add it to PATH, then try again.
  pause
  exit /b 1
)

echo Running claim analysis program...
%PY_CMD% app_gui.py > output\run.log 2>&1
if errorlevel 1 (
  echo.
  echo Execution failed. Check this log file:
  echo %~dp0output\run.log
  start "" notepad "%~dp0output\run.log"
  pause
  exit /b 1
)
exit /b 0
