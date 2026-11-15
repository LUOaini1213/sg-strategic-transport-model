"""Junction tools: growth factors from modelled link flows, turning flows by Furness, and a signal capacity check.

Signal check (critical flow-ratio method, Webster 1958, Road Research Technical Paper 39):
    y_i = q_i / s_i per approach; a phase's ratio is the largest y among the approaches it serves.
    Y = sum of phase ratios, L = phases x lost time per phase.
    Optimum cycle C0 = (1.5 L + 5) / (1 - Y), limited to [C_min, C_max].
    Effective green of phase p: g_p = (C - L) y_p / Y.  Degree of saturation X_i = q_i C / (s_i g_p).
    Webster's delay per vehicle (s):
        d = C (1 - lam)^2 / (2 (1 - lam X)) + X^2 / (2 q (1 - X)) - 0.65 (C / q^2)^(1/3) X^(2 + 5 lam),
    with lam = g / C and q in vehicles per second; undefined for X >= 1.
"""
from __future__ import annotations

import math

import numpy as np


def furness_turns(seed: np.ndarray, in_totals, out_totals, tol: float = 1e-10, max_iter: int = 1000):
    """Scale a seed turning matrix (approaches x exits, zeros for banned turns) to the in and out totals."""
    T = np.asarray(seed, dtype=float).copy()
    a = np.asarray(in_totals, dtype=float)
    b = np.asarray(out_totals, dtype=float) * (a.sum() / max(np.sum(out_totals), 1e-12))
    for _ in range(max_iter):
        r = T.sum(1)
        T *= np.divide(a, r, out=np.zeros_like(a), where=r > 0)[:, None]
        c = T.sum(0)
        T *= np.divide(b, c, out=np.zeros_like(b), where=c > 0)[None, :]
        if np.max(np.abs(T.sum(1) - a)) <= tol * max(a.max(), 1.0):
            break
    return T


def webster_cycle(Y: float, L: float, c_min: float, c_max: float) -> float:
    if Y >= 1.0:
        return c_max
    return float(min(max((1.5 * L + 5.0) / (1.0 - Y), c_min), c_max))


def webster_delay(C: float, g: float, q_veh_h: float, X: float) -> float:
    if X >= 1.0 or q_veh_h <= 0:
        return float("nan")
    lam = g / C
    q = q_veh_h / 3600.0
    return float(C * (1 - lam) ** 2 / (2 * (1 - lam * X)) + X ** 2 / (2 * q * (1 - X))
                 - 0.65 * (C / q ** 2) ** (1.0 / 3.0) * X ** (2 + 5 * lam))


def bearing_deg(x0, y0, x1, y1) -> float:
    return math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360.0


def phase_plan(bearings: list[float], tol: float = 45.0) -> list[list[int]]:
    """Group approaches into phases: approaches pointing in roughly opposite directions run together."""
    left = list(range(len(bearings)))
    phases = []
    while left:
        i = left.pop(0)
        grp = [i]
        for j in list(left):
            d = abs((bearings[i] - bearings[j] + 180.0) % 360.0 - 180.0)
            if abs(d - 180.0) <= tol:
                grp.append(j)
                left.remove(j)
                break
        phases.append(grp)
    return phases


def signal_check(q, s, bearings, lost_per_phase: float, c_min: float, c_max: float) -> dict:
    """Critical-ratio check of one signalised junction. q, s in pcu/h per approach."""
    q = np.asarray(q, dtype=float)
    s = np.asarray(s, dtype=float)
    y = q / s
    phases = phase_plan(list(bearings))
    yp = [max(y[i] for i in p) for p in phases]
    Y = float(sum(yp))
    L = lost_per_phase * len(phases)
    C = webster_cycle(Y, L, c_min, c_max)
    X = np.zeros_like(q)
    g_of = np.zeros_like(q)
    delay = np.zeros_like(q)
    for p, ypp in zip(phases, yp):
        g = (C - L) * ypp / Y if Y > 0 else (C - L) / len(phases)
        for i in p:
            g_of[i] = g
            X[i] = q[i] * C / (s[i] * g) if g > 0 else np.inf
            delay[i] = webster_delay(C, g, q[i], X[i])
    return {"phases": phases, "Y": Y, "lost_time_s": L, "cycle_s": C, "green_s": g_of, "X": X, "delay_s": delay,
            "y": y}
