"""
Prediction quality metrics shared by training (model selection) and evaluation.

Frames must have columns: season, week, actual, sleeper_proj, and the
prediction column being scored.
"""

from typing import Dict

import numpy as np
import pandas as pd

# Startable players: Sleeper projects at least this many PPR points
START_POOL_MIN_PROJ = 5.0
# A start/sit decision only matters if the two actual scores differ this much
DECISION_MARGIN = 3.0


def start_sit_accuracy(df: pd.DataFrame, pred_col: str) -> float:
    """
    Pairwise ranking accuracy on meaningful start/sit decisions.

    Among startable players in the same week, for every pair whose actual
    scores differ by >= DECISION_MARGIN, how often the higher scorer was
    ranked first. Ties in the prediction count half.
    """
    correct, total = 0.0, 0
    pool = df[df['sleeper_proj'] >= START_POOL_MIN_PROJ]
    for _, week in pool.groupby(['season', 'week']):
        actual = week['actual'].to_numpy(dtype=float)
        pred = week[pred_col].to_numpy(dtype=float)
        diff_actual = actual[:, None] - actual[None, :]
        diff_pred = pred[:, None] - pred[None, :]
        decisions = np.triu(np.abs(diff_actual) >= DECISION_MARGIN, k=1)
        if not decisions.any():
            continue
        agree = np.sign(diff_actual[decisions]) == np.sign(diff_pred[decisions])
        tie = diff_pred[decisions] == 0
        correct += agree.sum() + 0.5 * tie.sum()
        total += decisions.sum()
    return correct / total if total else float('nan')


def score(df: pd.DataFrame, pred_col: str) -> Dict[str, float]:
    """MAE, RMSE and start/sit accuracy for one prediction column."""
    error = df[pred_col] - df['actual']
    return {
        'mae': float(error.abs().mean()),
        'rmse': float(np.sqrt((error ** 2).mean())),
        'start_sit': float(start_sit_accuracy(df, pred_col)),
    }


def interval_coverage(actual, low, high) -> float:
    """Share of actual values inside [low, high]."""
    actual, low, high = (np.asarray(a, dtype=float) for a in (actual, low, high))
    return float(np.mean((actual >= low) & (actual <= high)))


def conformal_adjustment(actual, low, high, coverage: float) -> float:
    """
    Split-conformal correction for a quantile interval (CQR).

    Conformity score per calibration row: how far the actual value fell
    outside [low, high] (negative when inside). Widening every interval by
    the finite-sample (1 - alpha) quantile of these scores gives intervals
    that contain the truth with probability >= coverage on exchangeable data.
    A negative result narrows intervals that were too wide.
    """
    actual, low, high = (np.asarray(a, dtype=float) for a in (actual, low, high))
    scores = np.maximum(low - actual, actual - high)
    n = len(scores)
    if n == 0:
        return 0.0
    level = min(1.0, np.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method='higher'))
