"""Render package.

Public exports:
    headless   - 16:9 headless clip capture (per-beat .webm)
    stitch     - crossfade concatenation of headless clips -> silent_reel.mp4
    mix        - silent_reel + VO + music -> reel.mp4
    shorts     - 9:16 vertical composition of headless clips for YT Shorts
    pipeline   - 8-step VOD chain runner

The autonomy team owns `pipeline.py`; the content team (this sprint)
owns `shorts.py` + the public symbol re-export below.
"""

from __future__ import annotations

# Re-export the shorts public surface so callers can do
# `from tradefarm.render.shorts import compose_session, ShortsResult, ...`
# without caring about the package layout. The headless module is
# already imported by render.pipeline; we don't re-export it here to
# avoid a circular import.
from tradefarm.render.shorts import (  # noqa: E402,F401
    DEFAULT_BASE_SHORT_SECONDS,
    DEFAULT_MAX_DURATION,
    DEFAULT_TOP_N,
    DEFAULT_VERTICAL,
    ShortsJob,
    ShortsResult,
    build_ffmpeg_argv,
    compose_session,
    plan_jobs,
)
