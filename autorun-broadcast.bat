@echo off
REM TradeFarm broadcast VM — unattended auto-restart wrapper.
REM Wraps `npm run broadcast` (api + stream Tauri, no dashboard).
REM OBS captures the Tauri window; the operator's workstation dashboard
REM points at this VM's IP for remote control.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0autorun.ps1" -Target broadcast
pause
