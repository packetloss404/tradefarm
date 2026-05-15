@echo off
REM TradeFarm — unattended auto-restart wrapper. Double-click from Explorer.
REM Survives Tauri exits, desktop sleep, and other OS-level nudges.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0autorun.ps1"
pause
