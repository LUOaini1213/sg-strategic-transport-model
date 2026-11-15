"""Comparison statistics for modelled against observed flows or matrices."""
from __future__ import annotations

import numpy as np


def geh(modelled, observed):
    """GEH = sqrt(2 (M - C)^2 / (M + C)) for hourly flows; 0 where both are 0."""
    m = np.asarray(modelled, dtype=float)
    c = np.asarray(observed, dtype=float)
    s = m + c
    return np.sqrt(np.divide(2.0 * (m - c) ** 2, s, out=np.zeros_like(s), where=s > 0))


def r_squared(modelled, observed) -> float:
    """Square of the Pearson correlation between modelled and observed values."""
    m = np.asarray(modelled, dtype=float).ravel()
    c = np.asarray(observed, dtype=float).ravel()
    if m.size < 2 or np.std(m) == 0 or np.std(c) == 0:
        return float("nan")
    return float(np.corrcoef(m, c)[0, 1] ** 2)


def srmse(modelled, observed) -> float:
    """Standardised root mean square error: RMSE / mean(observed)."""
    m = np.asarray(modelled, dtype=float).ravel()
    c = np.asarray(observed, dtype=float).ravel()
    return float(np.sqrt(np.mean((m - c) ** 2)) / np.mean(c))


def share_within(values, limit) -> float:
    v = np.asarray(values, dtype=float)
    return float(np.mean(v < limit)) if v.size else float("nan")
