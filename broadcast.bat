@echo off
REM TradeFarm broadcast VM launcher — backend + stream Tauri only.
REM OBS captures the Tauri window. The dashboard runs on a separate
REM machine and points at this VM's IP for remote control.
cd /d "%~dp0"
npm run broadcast
pause
