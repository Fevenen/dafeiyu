@echo off
setlocal
if not defined PET_ROOT set "PET_ROOT=%~dp0..\..\pet"
cd /d "%PET_ROOT%"
".venv\Scripts\python.exe" -m bridge.pet_chat %*
