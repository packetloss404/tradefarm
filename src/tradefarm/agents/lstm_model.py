"""Tiny LSTM classifier: 3-class direction + 1 confidence head."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

MODELS_DIR = Path("models")


@dataclass
class ModelConfig:
    n_features: int
    seq_len: int = 30
    hidden: int = 64
    num_layers: int = 2
    dropout: float = 0.2


class LstmDirectionModel(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.lstm = nn.LSTM(
            input_size=cfg.n_features,
            hidden_size=cfg.hidden,
            num_layers=cfg.num_layers,
            batch_first=True,
            dropout=cfg.dropout if cfg.num_layers > 1 else 0.0,
        )
        self.dir_head = nn.Linear(cfg.hidden, 3)
        self.conf_head = nn.Linear(cfg.hidden, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        out, _ = self.lstm(x)
        last = out[:, -1, :]
        return self.dir_head(last), torch.sigmoid(self.conf_head(last)).squeeze(-1)


@dataclass
class Prediction:
    direction: int  # 0=down, 1=flat, 2=up
    direction_probs: tuple[float, float, float]
    confidence: float


@dataclass
class FittedModel:
    model: LstmDirectionModel
    feature_mean: np.ndarray
    feature_std: np.ndarray

    def predict(self, window: np.ndarray) -> Prediction:
        """window shape (seq_len, F). Standardizes, runs forward, returns Prediction."""
        if window.ndim != 2 or window.shape[0] != self.model.cfg.seq_len:
            raise ValueError(f"expected (seq_len={self.model.cfg.seq_len}, F), got {window.shape}")
        std = (window - self.feature_mean) / np.where(self.feature_std == 0, 1, self.feature_std)
        x = torch.from_numpy(std.astype(np.float32)).unsqueeze(0)
        self.model.eval()
        with torch.no_grad():
            logits, conf = self.model(x)
        probs = torch.softmax(logits, dim=-1).squeeze(0).cpu().numpy()
        return Prediction(
            direction=int(probs.argmax()),
            direction_probs=(float(probs[0]), float(probs[1]), float(probs[2])),
            confidence=float(conf.item()),
        )


def model_path(symbol: str) -> Path:
    return MODELS_DIR / f"{symbol}.pt"


def save(symbol: str, fitted: FittedModel) -> Path:
    MODELS_DIR.mkdir(exist_ok=True)
    path = model_path(symbol)
    torch.save(
        {
            "cfg": fitted.model.cfg.__dict__,
            "state_dict": fitted.model.state_dict(),
            "feature_mean": fitted.feature_mean,
            "feature_std": fitted.feature_std,
        },
        path,
    )
    return path


def load(symbol: str) -> FittedModel | None:
    path = model_path(symbol)
    if not path.exists():
        return None
    blob = torch.load(path, map_location="cpu", weights_only=False)
    cfg = ModelConfig(**blob["cfg"])
    model = LstmDirectionModel(cfg)
    model.load_state_dict(blob["state_dict"])
    return FittedModel(model=model, feature_mean=blob["feature_mean"], feature_std=blob["feature_std"])
