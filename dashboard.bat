@echo off
REM TradeFarm operator dashboard launcher — Vite-only.
REM Reads web/.env.local for TRADEFARM_BACKEND to point at a remote VM,
REM or defaults to 127.0.0.1:8000 for a local backend.
cd /d "%~dp0"
npm run dashboard
pause
