# TradeFarm broadcast VM launcher — backend + stream Tauri only.
# OBS captures the Tauri window. The dashboard runs on a separate
# machine and points at this VM's IP for remote control.
Set-Location -LiteralPath $PSScriptRoot
npm run broadcast
