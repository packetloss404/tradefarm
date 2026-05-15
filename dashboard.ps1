# TradeFarm operator dashboard launcher — Vite-only.
# Reads web/.env.local for TRADEFARM_BACKEND to point at a remote VM,
# or defaults to 127.0.0.1:8000 for a local backend.
Set-Location -LiteralPath $PSScriptRoot
npm run dashboard
