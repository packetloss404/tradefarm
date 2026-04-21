"""Train per-symbol LSTM direction models. CLI entry:

    uv run python -m tradefarm.agents.lstm_train --symbol SPY
    uv run python -m tradefarm.agents.lstm_train --universe       # train all default-universe symbols
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta

import numpy as np
import structlog
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from tradefarm.agents.features import featurize, make_windows
from tradefarm.agents.lstm_model import FittedModel, LstmDirectionModel, ModelConfig, save
from tradefarm.data.eodhd import EodhdClient
from tradefarm.data.universe import default_universe

log = structlog.get_logger()

SEQ_LEN = 30
BATCH = 64
EPOCHS = 30
LR = 1e-3
HISTORY_DAYS = 365 * 5
PATIENCE = 5


async def fetch_history(symbol: str) -> np.ndarray | None:
    client = EodhdClient()
    end = date.today()
    start = end - timedelta(days=HISTORY_DAYS)
    df = await client.get_eod(symbol, start=start, end=end)
    if df.empty or len(df) < SEQ_LEN + 50:
        log.warning("history_too_short", symbol=symbol, rows=len(df))
        return None
    return df


def _make_loaders(X: np.ndarray, y: np.ndarray) -> tuple[DataLoader, DataLoader, np.ndarray, np.ndarray]:
    split = int(len(X) * 0.8)
    X_tr, X_va = X[:split], X[split:]
    y_tr, y_va = y[:split], y[split:]
    feature_mean = X_tr.reshape(-1, X_tr.shape[-1]).mean(axis=0)
    feature_std = X_tr.reshape(-1, X_tr.shape[-1]).std(axis=0)
    feature_std[feature_std == 0] = 1.0

    def std(a):
        return (a - feature_mean) / feature_std

    tr = DataLoader(
        TensorDataset(torch.from_numpy(std(X_tr).astype(np.float32)), torch.from_numpy(y_tr)),
        batch_size=BATCH, shuffle=True,
    )
    va = DataLoader(
        TensorDataset(torch.from_numpy(std(X_va).astype(np.float32)), torch.from_numpy(y_va)),
        batch_size=BATCH, shuffle=False,
    )
    return tr, va, feature_mean.astype(np.float32), feature_std.astype(np.float32)


def _conf_target(probs: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    """Confidence target = probability the model assigns to the true class."""
    return probs.gather(1, y.unsqueeze(1)).squeeze(1).detach()


def _class_weights(y: np.ndarray, n_classes: int = 3) -> torch.Tensor:
    """Inverse-frequency class weights, normalized to mean 1.0. Missing classes get weight 1."""
    counts = np.bincount(y, minlength=n_classes).astype(np.float64)
    inv = np.where(counts > 0, 1.0 / np.maximum(counts, 1.0), 1.0)
    inv = inv * (n_classes / inv.sum())  # normalize so weights average to 1
    return torch.from_numpy(inv.astype(np.float32))


async def train_one(symbol: str) -> bool:
    df = await fetch_history(symbol)
    if df is None:
        return False

    X_flat, y_flat = featurize(df)
    X, y = make_windows(X_flat, y_flat, seq_len=SEQ_LEN)
    if len(X) < 100:
        log.warning("not_enough_windows", symbol=symbol, n=len(X))
        return False

    tr_loader, va_loader, mean, std_ = _make_loaders(X, y)

    split = int(len(X) * 0.8)
    y_tr = y[:split]
    counts = np.bincount(y_tr, minlength=3).astype(int)
    total = int(counts.sum()) or 1
    weights = _class_weights(y_tr)
    log.info(
        "class_distribution",
        symbol=symbol,
        down=int(counts[0]), flat=int(counts[1]), up=int(counts[2]),
        pct_down=round(counts[0] / total, 3),
        pct_flat=round(counts[1] / total, 3),
        pct_up=round(counts[2] / total, 3),
        weights=[round(float(w), 3) for w in weights.tolist()],
    )

    cfg = ModelConfig(n_features=X.shape[-1], seq_len=SEQ_LEN)
    model = LstmDirectionModel(cfg)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    ce = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.05)
    bce = nn.BCELoss()

    best_va = float("inf")
    bad = 0
    for epoch in range(1, EPOCHS + 1):
        model.train()
        tr_loss = 0.0
        for xb, yb in tr_loader:
            opt.zero_grad()
            logits, conf = model(xb)
            probs = torch.softmax(logits, dim=-1)
            loss = ce(logits, yb) + 0.2 * bce(conf, _conf_target(probs, yb))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tr_loss += loss.item() * len(yb)
        tr_loss /= len(tr_loader.dataset)

        model.eval()
        va_loss = 0.0
        correct = 0
        total = 0
        with torch.no_grad():
            for xb, yb in va_loader:
                logits, conf = model(xb)
                probs = torch.softmax(logits, dim=-1)
                loss = ce(logits, yb) + 0.2 * bce(conf, _conf_target(probs, yb))
                va_loss += loss.item() * len(yb)
                correct += (logits.argmax(-1) == yb).sum().item()
                total += len(yb)
        va_loss /= len(va_loader.dataset)
        va_acc = correct / total

        log.info("epoch", symbol=symbol, e=epoch, tr=round(tr_loss, 4), va=round(va_loss, 4), va_acc=round(va_acc, 3))
        if va_loss < best_va - 1e-4:
            best_va = va_loss
            bad = 0
            save(symbol, FittedModel(model=model, feature_mean=mean, feature_std=std_))
        else:
            bad += 1
            if bad >= PATIENCE:
                log.info("early_stop", symbol=symbol, epoch=epoch)
                break

    return True


async def main_async(symbols: list[str]) -> None:
    for s in symbols:
        log.info("training", symbol=s)
        ok = await train_one(s)
        log.info("trained" if ok else "skipped", symbol=s)


def main() -> None:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="Train a single symbol, e.g. SPY")
    g.add_argument("--universe", action="store_true", help="Train every default-universe symbol")
    args = parser.parse_args()
    syms = [args.symbol] if args.symbol else default_universe()
    asyncio.run(main_async(syms))


if __name__ == "__main__":
    main()
