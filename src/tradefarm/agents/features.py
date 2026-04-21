"""Feature engineering for the LSTM brain.

Strict no-leak: every feature at row t uses only data from rows <= t.
Output is a (T, F) float32 array of features and a (T,) int64 array of class
labels for the next-`horizon`-day cumulative return: 0=down, 1=flat, 2=up.

Horizon knob: `horizon=1` predicts next-day return with base threshold +/-0.5%
(original behavior). Larger horizons predict the cumulative return over the
next `horizon` trading days. The up/down threshold scales as
BASE_THRESHOLD * sqrt(horizon) so class balance is preserved (returns scale
roughly with sqrt(time) under a random-walk assumption).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

UP_THRESHOLD = 0.005
DOWN_THRESHOLD = -0.005
_EPS = 1e-9

FEATURE_NAMES = (
    "ret_1d",
    "ret_5d",
    "ret_10d",
    "rsi_14",
    "atr14_norm",
    "vol_z_20",
    "macd_hist",
    "bb_pct",
    "high20_dist",
    "low20_dist",
    "realized_vol_20",
    "mom_z_5_60",
    "gap_open",
    "range_pos",
    "vwap20_ratio",
    "dow_sin",
    "dow_cos",
    "moy_sin",
    "moy_cos",
)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0) / 100.0  # rescale to 0..1


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def featurize(df: pd.DataFrame, *, horizon: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Returns (X, y). Trims rows with insufficient history.

    `horizon` is the number of trading days ahead the label predicts
    (cumulative return). Threshold scales as BASE * sqrt(horizon).
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")

    df = df.sort_values("date").reset_index(drop=True).copy()
    close = df["adjusted_close"].astype(float)
    open_ = df["open"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    dates = pd.to_datetime(df["date"])

    feats = pd.DataFrame(index=df.index)
    feats["ret_1d"] = close.pct_change(1)
    feats["ret_5d"] = close.pct_change(5)
    feats["ret_10d"] = close.pct_change(10)
    feats["rsi_14"] = _rsi(close, 14)

    atr = _atr(high, low, close, 14)
    feats["atr14_norm"] = (atr / close).clip(0, 0.2)

    vol_mean = volume.rolling(20, min_periods=5).mean()
    vol_std = volume.rolling(20, min_periods=5).std().replace(0, np.nan)
    feats["vol_z_20"] = ((volume - vol_mean) / vol_std).clip(-3, 3).fillna(0)

    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    feats["macd_hist"] = ((macd - macd_signal) / close).clip(-0.05, 0.05)

    rolling_mean = close.rolling(20, min_periods=5).mean()
    rolling_std = close.rolling(20, min_periods=5).std().replace(0, np.nan)
    upper = rolling_mean + 2 * rolling_std
    lower = rolling_mean - 2 * rolling_std
    feats["bb_pct"] = ((close - lower) / (upper - lower)).clip(-0.5, 1.5).fillna(0.5)

    high20 = close.rolling(20, min_periods=5).max()
    low20 = close.rolling(20, min_periods=5).min()
    feats["high20_dist"] = ((close - high20) / close).clip(-0.5, 0.5)
    feats["low20_dist"] = ((close - low20) / close).clip(-0.5, 0.5)

    # --- New features (appended; strict no-leak: only data up to t) ---

    # Realized vol: 20-day std of log returns (annualization left to the model).
    log_ret = np.log(close / close.shift(1))
    feats["realized_vol_20"] = (
        log_ret.rolling(20, min_periods=5).std().clip(0, 0.2).fillna(0)
    )

    # Self-referenced momentum: z-score of 5d return vs trailing 60d distribution.
    ret5 = close.pct_change(5)
    ret5_mean_60 = ret5.rolling(60, min_periods=20).mean()
    ret5_std_60 = ret5.rolling(60, min_periods=20).std().replace(0, np.nan)
    feats["mom_z_5_60"] = ((ret5 - ret5_mean_60) / ret5_std_60).clip(-3, 3).fillna(0)

    # Overnight gap: open_t / close_{t-1} - 1.
    feats["gap_open"] = (open_ / close.shift(1) - 1.0).clip(-0.2, 0.2).fillna(0)

    # Close position in daily range: (close-low)/(high-low+eps), 0..1.
    feats["range_pos"] = ((close - low) / (high - low + _EPS)).clip(0, 1).fillna(0.5)

    # Rolling 20d VWAP, ratio to close - 1.
    pv = close * volume
    vwap20 = (
        pv.rolling(20, min_periods=5).sum() / volume.rolling(20, min_periods=5).sum().replace(0, np.nan)
    )
    feats["vwap20_ratio"] = (close / vwap20 - 1.0).clip(-0.2, 0.2).fillna(0)

    # Calendar encodings (deterministic; do not leak future info).
    dow = dates.dt.dayofweek.astype(float)  # 0..6
    moy = (dates.dt.month.astype(float) - 1.0)  # 0..11
    feats["dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    feats["dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    feats["moy_sin"] = np.sin(2 * np.pi * moy / 12.0)
    feats["moy_cos"] = np.cos(2 * np.pi * moy / 12.0)

    feats = feats[list(FEATURE_NAMES)].fillna(0).astype(np.float32)

    # Label: cumulative return over the next `horizon` trading days.
    future_close = close.shift(-horizon)
    horizon_ret = (future_close / close) - 1.0

    scale = float(np.sqrt(horizon))
    up_thr = UP_THRESHOLD * scale
    down_thr = DOWN_THRESHOLD * scale

    y = pd.Series(1, index=df.index, dtype=np.int64)
    y[horizon_ret <= down_thr] = 0
    y[horizon_ret >= up_thr] = 2

    valid = ~horizon_ret.isna()
    return feats.values[valid.values], y.values[valid.values]


def make_windows(
    X: np.ndarray,
    y: np.ndarray,
    seq_len: int = 30,
    *,
    horizon: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Slide a window over (T, F) -> (N, seq_len, F); labels at the end of each window.

    `horizon` is accepted for API symmetry with `featurize`; labels are
    already horizon-aligned by `featurize`, so this simply mirrors the
    end-of-window indexing. Kept as a keyword arg for forward-compat.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    n = len(X) - seq_len + 1
    if n <= 0:
        return np.empty((0, seq_len, X.shape[1]), dtype=np.float32), np.empty((0,), dtype=np.int64)
    out_x = np.stack([X[i : i + seq_len] for i in range(n)], axis=0)
    out_y = y[seq_len - 1 : seq_len - 1 + n]
    return out_x, out_y


def latest_window(X: np.ndarray, seq_len: int = 30) -> np.ndarray | None:
    """Just the most-recent (seq_len, F) window for inference. None if too few rows."""
    if len(X) < seq_len:
        return None
    return X[-seq_len:]
