"""Doubly constrained gravity model, deterrence functions, calibration and trip-length statistics.

T_ij = A_i O_i B_j D_j f(c_ij),  A_i = 1 / sum_j B_j D_j f_ij,  B_j = 1 / sum_i A_i O_i f_ij  (Furness balancing).

Deterrence functions (c in km):
    exponential  f = exp(-b c)
    gamma        f = c^a exp(-b c)      (also called combined or Tanner)

For the gamma function the maximum-likelihood conditions in a doubly constrained model are that the modelled
mean of c and the modelled mean of ln c equal the observed ones; ``calibrate_gamma_moments`` solves those two
equations. ``calibrate_exponential_mean`` solves the single mean-cost condition (Hyman's condition).
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import brentq, least_squares, minimize


def deterrence(c, kind: str, a: float = 0.0, b: float = 0.0):
    c = np.asarray(c, dtype=float)
    if kind == "exponential":
        return np.exp(-b * c)
    if kind == "gamma":
        return np.power(c, a) * np.exp(-b * c)
    if kind == "power":
        return np.power(c, -a)
    raise ValueError(f"unknown deterrence function {kind}")


def furness(origins, destinations, f, tol: float = 1e-9, max_iter: int = 5000):
    """Balance T = A O B D f to the row totals ``origins`` and column totals ``destinations``.
    Returns (T, iterations, max relative error). Destinations are rescaled to the origin total first."""
    O = np.asarray(origins, dtype=float)
    D = np.asarray(destinations, dtype=float)
    f = np.asarray(f, dtype=float)
    if O.sum() <= 0 or D.sum() <= 0:
        raise ValueError("trip ends must have positive totals")
    D = D * (O.sum() / D.sum())
    B = np.ones_like(D)
    err = np.inf
    it = 0
    for it in range(1, max_iter + 1):
        s = f @ (B * D)
        A = np.divide(1.0, s, out=np.zeros_like(s), where=s > 0)
        r = (A * O) @ f
        B = np.divide(1.0, r, out=np.zeros_like(r), where=r > 0)
        T = (A * O)[:, None] * f * (B * D)[None, :]
        rows, cols = T.sum(1), T.sum(0)
        er = np.max(np.abs(rows - O)[O > 0] / O[O > 0]) if (O > 0).any() else 0.0
        ec = np.max(np.abs(cols - D)[D > 0] / D[D > 0]) if (D > 0).any() else 0.0
        err = max(er, ec)
        if err < tol:
            break
    return T, it, err


def mean_cost(T, c) -> float:
    return float((T * c).sum() / T.sum())


def mean_log_cost(T, c) -> float:
    return float((T * np.log(c)).sum() / T.sum())


def tld(T, c, bin_km: float = 1.0, max_km: float = 60.0):
    """Trip-length distribution: (bin edges, trips per bin). Trips beyond max_km go into the last bin."""
    edges = np.arange(0.0, max_km + bin_km, bin_km)
    cc = np.minimum(np.asarray(c, dtype=float), max_km - 1e-9)
    h, _ = np.histogram(cc, bins=edges, weights=np.asarray(T, dtype=float))
    return edges, h


def coincidence_ratio(p_obs, p_mod) -> float:
    """sum_k min(P_obs,k, P_mod,k) / sum_k max(P_obs,k, P_mod,k) on proportions; 1 = identical distributions."""
    p = np.asarray(p_obs, dtype=float)
    q = np.asarray(p_mod, dtype=float)
    p, q = p / p.sum(), q / q.sum()
    return float(np.minimum(p, q).sum() / np.maximum(p, q).sum())


def gravity(origins, destinations, c, kind: str, a: float = 0.0, b: float = 0.0, tol: float = 1e-9):
    T, it, err = furness(origins, destinations, deterrence(c, kind, a, b), tol=tol)
    return T


def calibrate_exponential_mean(origins, destinations, c, target_mean: float, tol: float = 1e-9):
    """b such that the modelled mean cost equals target_mean (Hyman's condition)."""

    def resid(b):
        return mean_cost(gravity(origins, destinations, c, "exponential", b=b, tol=tol), c) - target_mean

    lo, hi = 1e-4, 5.0
    while resid(lo) < 0:      # mean too short even with almost no deterrence: widen
        lo /= 10
        if lo < 1e-9:
            raise ValueError("target mean cost longer than the no-deterrence mean")
    return float(brentq(resid, lo, hi, xtol=1e-10))


def calibrate_gamma_moments(origins, destinations, c, target_mean: float, target_mean_log: float,
                            x0=(0.0, 0.3), tol: float = 1e-9):
    """(a, b) of f = c^a exp(-b c) such that the modelled mean of c and of ln c match the targets."""

    def resid(p):
        T = gravity(origins, destinations, c, "gamma", p[0], p[1], tol=tol)
        return [mean_cost(T, c) / target_mean - 1.0, mean_log_cost(T, c) - target_mean_log]

    sol = least_squares(resid, x0=np.array(x0, dtype=float), xtol=1e-12, ftol=1e-12, gtol=1e-12)
    return float(sol.x[0]), float(sol.x[1]), float(np.max(np.abs(sol.fun)))


def calibrate_gamma_aggregate(origins, destinations, c, row_group, col_group, observed, x0=(0.0, 0.2),
                              tol: float = 1e-9):
    """(a, b) maximising the multinomial log-likelihood of an observed matrix that is only known for groups of
    zones: observed[g, h] counts trips from row group g to column group h. Zones with group -1 are ignored on
    that side (the modelled trips are still balanced to all trip ends).
    Returns (a, b, log-likelihood, modelled grouped matrix)."""
    rg = np.asarray(row_group)
    cg = np.asarray(col_group)
    G, H = observed.shape
    Rm = np.zeros((G, len(rg)))
    Rm[rg[rg >= 0], np.where(rg >= 0)[0]] = 1.0
    Cm = np.zeros((len(cg), H))
    Cm[np.where(cg >= 0)[0], cg[cg >= 0]] = 1.0
    N = np.asarray(observed, dtype=float)

    def grouped(p):
        T = gravity(origins, destinations, c, "gamma", p[0], p[1], tol=tol)
        return Rm @ T @ Cm

    def nll(p):
        M = grouped(p)
        P = M / M.sum()
        with np.errstate(divide="ignore"):
            return -float(np.sum(N[N > 0] * np.log(P[N > 0])))

    res = minimize(nll, x0=np.array(x0, dtype=float), method="Nelder-Mead",
                   options={"xatol": 1e-7, "fatol": 1e-6, "maxiter": 4000})
    return float(res.x[0]), float(res.x[1]), -float(res.fun), grouped(res.x)
