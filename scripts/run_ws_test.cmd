@echo off
chcp 65001 >nul
cd /d "%~dp0.."
".venv\Scripts\python.exe" "bridge\ws_test.py" %* > "logs\ws_test.log" 2>&1
