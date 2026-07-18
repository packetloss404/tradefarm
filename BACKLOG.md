# Backlog

## Portfolio audit backlog — 2026-07-17
_Findings from a 2026-07-17 code audit, preserved for later._

### Later / deferred
- **[low/L]** Some dramatic-beat kinds (near_miss, chapter_change, promotion, llm_bet, agent_rivalry, leaderboard_shift) deferred to v1
  - Fix: session/beats.py:29-33 documents these can't score because required data (LSTM probs as events, market data, multi-session history) isn't in the manifest yet. Real roadmap work: extend the runner to emit that data first, then add scorers. Disclosed v0 deferral, not a bug.
- **[low/M]** Deliberately loose pandas>=2.2 pin; venv on 3.0.2 with CoW-default + removed APIs, untested
  - Fix: pyproject.toml:23 — the round-4 NOTE flags real untested pandas-3.x drift. Either pin pandas>=2.2,<3.0 and rebuild/relock the venv, then run the 536-test suite to confirm green; OR explicitly adopt 3.x by fixing the CoW/removed-API breakages and dropping the note. Single-dev tool so low urgency, but it's a genuine latent break on next `uv lock --upgrade`.

### Known limitations (deliberate — not planned)
- TTS has a 'silence' fallback; real backends only if env keys present
