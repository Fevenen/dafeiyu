@echo off
setlocal
cd /d "%~dp0"
set "ELECTRON_RUN_AS_NODE="
set "PYTHONIOENCODING=utf-8"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run the installation instructions first.
  exit /b 1
)
".venv\Scripts\python.exe" -m bridge.launcher %*
exit /b %errorlevel%
