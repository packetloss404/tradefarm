# REPO_REVIEW_NOTES.md — working notes

Scratchpad for the full-repo review. Final report lives in `REPO_REVIEW.md`.

## Inventory
- Python backend: `src/tradefarm/**` ~17.9k LOC. uv project (`pyproject.toml`, `uv.lock`).
- Two React 19 + Vite 6 + Tailwind v4 + TS 5.6 frontends: `web/` (operator dashboard), `stream/` (Tauri/OBS broadcast overlay).
- Tauri shell in `stream/src-tauri/`.
- Tests: 62 files under `tests/` (pytest, asyncio auto).
- CI: `.github/workflows/ci.yml` (python lint+format+test; web/stream typecheck+build).
- Launchers: Windows-only `.bat`/`.ps1` (start/autorun/broadcast/dashboard).
- Docs: README, RUNBOOK, ROADMAP, CHANGELOG, CLAUDE.md.

## Git hygiene checks (verified)
- `.env` NOT tracked. `tradefarm.db` NOT tracked. Good.
- 432 tracked files. ~36 PNGs tracked, ~28 are debug screenshots under docs/screenshots/2026-05-17/.
- `dev/` has duplicated design-handoff trees + `dev/_archive/` dead plans.

## Verified-by-direct-read findings
- C2: `storage/repo.py:57` `record_trade(...)` has NO `broker_order_id` param/column write → the UNIQUE-on-broker_order_id dedup story is inert. CONFIRMED.
- BUG: `orchestrator/broadcast_os.py:251` `getattr(sm, "state", "active")` — `ScheduledMoment` has no `state` field → always "active". CONFIRMED.
- H1: `api/main.py:135-136` auth middleware short-circuits when `api_shared_secret` empty (default) → all POSTs open. CONFIRMED.
- H2: `api/main.py:165-174` CORS `allow_origin_regex` allows all of 10/8, 192.168/16, 172.16-31 on any port. CONFIRMED.
- Auth check uses `hmac.compare_digest` (timing-safe). CONFIRMED good.

## Subagent reports captured (see REPO_REVIEW.md for synthesis)
1. Backend architecture/orchestrator — god-object Orchestrator, fire-and-forget start tasks, predictions reset off-by-one, broadcast_slot dead state field.
2. Execution/risk/data/storage/agents — C1 reconciled-flip avg_price corruption, C2 inert dedup, float money, LLM parse validation gap.
3. Frontend — 60fps AgentWorldXL re-render loop, no ESLint, dead/destructive UI controls, shipped mock data, duplicated cross-app modules, a11y gaps.
4. Security — open-by-default mutations, broad LAN CORS, minimax_base_url SSRF; many positives (parameterized SQL, list-form subprocess, path-traversal guards, secret masking).
5. Tests/CI/DX/deps — strong execution tests, no agent/feature tests, no frontend tests, mypy declared-but-unrun, pandas 3.x loose pin, 4 lockfiles, Windows-only launchers, no Docker.
