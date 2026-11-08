@echo off
rem Start everything the desktop pet needs:
rem   SnowLuma (QQ bridge) -> backend -> reminder scheduler -> DSH watcher -> Electron client
rem Place this file in the Open-LLM-VTuber (pet) root directory.
cd /d "%~dp0"

set "ELECTRON_RUN_AS_NODE="
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

set "APP=%~dp0pet-web\release\1.2.1\win-unpacked\open-llm-vtuber-electron.exe"
set "SNOWLUMA=%~dp0..\v0\SnowLuma"
set "PETWS=%~dp0..\pet_workspace"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] venv not found: %PY%
    pause
    exit /b 1
)

rem Electron client is optional: browser works too
set "HAS_APP=1"
if not exist "%APP%" (
    set "HAS_APP=0"
    echo [INFO] Electron client not found - will open the web UI in your browser instead.
)

rem ---- 1. SnowLuma (QQ bridge) ----
if exist "%SNOWLUMA%\launcher.bat" (
    powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','\"%SNOWLUMA%\launcher.bat\"' -WorkingDirectory '%SNOWLUMA%' -WindowStyle Minimized }"
    powershell -NoProfile -Command "for($i=0;$i -lt 40;$i++){ if(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue){ exit 0 }; Start-Sleep -Milliseconds 1000 }; exit 1"
    if not errorlevel 1 (echo [OK] SnowLuma ready on 127.0.0.1:3000) else (echo [WARN] SnowLuma not ready after 40s - QQ features will fail)
) else (
    echo [WARN] SnowLuma not found: %SNOWLUMA%
)

rem ---- 2. backend ----
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 12393 -State Listen -ErrorAction SilentlyContinue)) { Start-Process -FilePath '%PY%' -ArgumentList 'run_server.py' -WorkingDirectory '%CD%' -WindowStyle Minimized }"
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){ if(Get-NetTCPConnection -LocalPort 12393 -State Listen -ErrorAction SilentlyContinue){ exit 0 }; Start-Sleep -Milliseconds 1000 }; exit 1"
if not errorlevel 1 (echo [OK] Backend ready on 127.0.0.1:12393) else (echo [WARN] Backend not ready after 60s)

rem ---- 3. reminder scheduler ----
powershell -NoProfile -Command "if (-not (Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*reminder_daemon.py*' })) { Start-Process -FilePath '%PY%' -ArgumentList 'bridge\reminder_daemon.py' -WorkingDirectory '%CD%' -WindowStyle Hidden -RedirectStandardOutput '%CD%\logs\daemon.out' -RedirectStandardError '%CD%\logs\daemon.err' }"
echo [OK] Reminder scheduler checked

rem ---- 4. DSH watcher (turn DSH replies into pet speech) ----
if exist "%PETWS%" (
    powershell -NoProfile -Command "if (-not (Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*dsh_watch.py*' })) { Start-Process -FilePath '%PY%' -ArgumentList '-u','bridge\dsh_watch.py','--dir','%PETWS%' -WorkingDirectory '%CD%' -WindowStyle Hidden -RedirectStandardOutput '%CD%\logs\watch.out' -RedirectStandardError '%CD%\logs\watch.err' }"
    echo [OK] DSH watcher started
) else (
    echo [WARN] pet_workspace not found, DSH watcher skipped
)

rem ---- 5. desktop client (Electron if present, otherwise browser) ----
if "%HAS_APP%"=="1" (
    powershell -NoProfile -Command "if (-not (Get-Process | Where-Object { $_.ProcessName -match 'open-llm' })) { Start-Process -FilePath '%APP%' -WorkingDirectory '%~dp0pet-web\release\1.2.1\win-unpacked' }"
    echo [OK] Desktop client checked
) else (
    echo [OK] Opening web UI: http://127.0.0.1:12393
    start "" "http://127.0.0.1:12393"
)
exit /b 0