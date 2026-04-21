"""Walk-forward backtest for trained per-symbol LSTM models.

Replays EOD bars in order, predicts with data ≤ t only, simulates the
LstmAgent decision rule (full-notional long/flat), and reports summary stats.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from tradefarm.agents.features import featurize, make_windows
from tradefarm.agents.lstm_model import FittedModel, load
from tradefarm.data.eodhd import EodhdClient
from tradefarm.data.universe import default_universe

HISTORY_DAYS = 365 * 2
ENTER_CONF = 0.40
TRADING_DAYS = 252


async def _fetch(symbol: str) -> pd.DataFrame | None:
    client = EodhdClient()
    end = date.today()
    start = end - timedelta(days=HISTORY_DAYS)
    df = await client.get_eod(symbol, start=start, end=end)
    if df.empty:
        return None
    return df.sort_values("date").reset_index(drop=True)


def _predict_series(fitted: FittedModel, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For every bar with enough history, return (indices-into-df, pred_class, max_prob).

    Each prediction at position i uses only feature rows up to i (no leak), because
    featurize is a pure per-row transform and we feed windows that end at i.
    """
    X_flat, _ = featurize(df)
    seq_len = fitted.model.cfg.seq_len
    X_win, _ = make_windows(X_flat, np.zeros(len(X_flat), dtype=np.int64), seq_len=seq_len)
    if len(X_win) == 0:
        return np.empty(0, dtype=int), np.empty(0, dtype=int), np.empty(0, dtype=float)

    # featurize drops rows where next_ret is NaN (the last bar). Windows start at
    # the seq_len-th feature row, which corresponds to df index (seq_len - 1).
    df_start = seq_len - 1
    preds = np.empty(len(X_win), dtype=int)
    max_probs = np.empty(len(X_win), dtype=float)
    for i, w in enumerate(X_win):
        p = fitted.predict(w)
        preds[i] = p.direction
        max_probs[i] = max(p.direction_probs)
    idx = np.arange(df_start, df_start + len(X_win))
    return idx, preds, max_probs


def _simulate(df: pd.DataFrame, idx: np.ndarray, preds: np.ndarray, max_probs: np.ndarray) -> dict:
    """Apply the LstmAgent rule bar-by-bar. Decision at bar t earns return t→t+1."""
    close = df["adjusted_close"].astype(float).values
    has_long = False
    equity = 1.0
    equity_curve = [equity]
    trade_returns: list[float] = []
    entry_px = 0.0
    n_trades = 0

    # Decide at idx[k] using the prediction made with data ≤ idx[k]; realize return
    # between close[idx[k]] and close[idx[k]+1]. Skip the last bar (no next close).
    for k, t in enumerate(idx):
        if t + 1 >= len(close):
            break
        pred = int(preds[k])
        mp = float(max_probs[k])

        # Decision rule (matches LstmAgent, full-notional):
        # go long when predicted class = up and max_prob >= 0.40;
        # flatten when predicted class = down and has_long; otherwise hold.
        if pred == 2 and mp >= ENTER_CONF and not has_long:
            has_long = True
            entry_px = close[t]
            n_trades += 1
        elif pred == 0 and has_long:
            trade_returns.append(close[t] / entry_px - 1.0)
            has_long = False

        bar_ret = (close[t + 1] / close[t] - 1.0) if has_long else 0.0
        equity *= 1.0 + bar_ret
        equity_curve.append(equity)

    # Close any still-open position at the final close we advanced to.
    if has_long and len(idx) > 0:
        last_t = int(idx[-1])
        final_t = min(last_t + 1, len(close) - 1)
        trade_returns.append(close[final_t] / entry_px - 1.0)

    eq = np.array(equity_curve, dtype=float)
    rets = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])

    total_return_pct = (eq[-1] - 1.0) * 100.0
    n_bars = max(len(rets), 1)
    cagr_pct = ((eq[-1]) ** (TRADING_DAYS / n_bars) - 1.0) * 100.0 if eq[-1] > 0 else -100.0
    sharpe = float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS)) if rets.std() > 0 else 0.0

    running_peak = np.maximum.accumulate(eq)
    drawdown = (eq - running_peak) / running_peak
    max_drawdown_pct = float(drawdown.min() * 100.0) if len(drawdown) else 0.0

    wins = [r for r in trade_returns if r > 0]
    win_rate = (len(wins) / len(trade_returns)) if trade_returns else 0.0
    avg_trade_return_pct = (float(np.mean(trade_returns)) * 100.0) if trade_returns else 0.0

    return {
        "total_return_pct": round(total_return_pct, 3),
        "cagr_pct": round(cagr_pct, 3),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_drawdown_pct, 3),
        "win_rate": round(win_rate, 3),
        "n_trades": int(n_trades),
        "avg_trade_return_pct": round(avg_trade_return_pct, 3),
        "n_bars": int(n_bars),
    }


async def _backtest_async(symbol: str) -> dict:
    fitted = load(symbol)
    if fitted is None:
        return {"symbol": symbol, "error": "no_model"}
    df = await _fetch(symbol)
    if df is None or len(df) < fitted.model.cfg.seq_len + 2:
        return {"symbol": symbol, "error": "insufficient_history"}
    idx, preds, max_probs = _predict_series(fitted, df)
    if len(idx) == 0:
        return {"symbol": symbol, "error": "no_windows"}
    stats = _simulate(df, idx, preds, max_probs)
    return {"symbol": symbol, **stats}


def backtest_symbol(symbol: str) -> dict:
    """Load the trained model, replay last ~2y of EOD bars, return summary stats."""
    return asyncio.run(_backtest_async(symbol))


def _print_universe_table(results: list[dict]) -> None:
    ok = [r for r in results if "error" not in r]
    ok.sort(key=lambda r: r.get("sharpe", float("-inf")), reverse=True)
    header = f"{'symbol':<8}{'sharpe':>8}{'total%':>10}{'cagr%':>10}{'maxdd%':>10}{'win':>7}{'n_tr':>6}{'avg%':>8}"
    print(header)
    print("-" * len(header))
    for r in ok:
        print(
            f"{r['symbol']:<8}"
            f"{r['sharpe']:>8.2f}"
            f"{r['total_return_pct']:>10.2f}"
            f"{r['cagr_pct']:>10.2f}"
            f"{r['max_drawdown_pct']:>10.2f}"
            f"{r['win_rate']:>7.2f}"
            f"{r['n_trades']:>6d}"
            f"{r['avg_trade_return_pct']:>8.2f}"
        )
    skipped = [r for r in results if "error" in r]
    if skipped:
        print("\nskipped:")
        for r in skipped:
            print(f"  {r['symbol']}: {r['error']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="Backtest a single symbol, e.g. SPY")
    g.add_argument("--universe", action="store_true", help="Backtest every default-universe symbol")
    args = parser.parse_args()

    if args.symbol:
        print(json.dumps(backtest_symbol(args.symbol), indent=2))
        return

    async def run_all() -> list[dict]:
        out = []
        for s in default_universe():
            out.append(await _backtest_async(s))
        return out

    results = asyncio.run(run_all())
    _print_universe_table(results)


if __name__ == "__main__":
    main()
