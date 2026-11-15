"""Multinomial logit mode choice (car, public transport, other), calibrated to aggregate mode shares.

Utilities for an origin-destination pair (i, j), times in minutes, distance in km:
    V_car   = asc_car + b_time * t_car_ij + b_priv * private_i + b_central * central_j
    V_pt    =           b_time * g_pt_ij
    V_other = asc_other + b_dist_other * d_ij
P_m = exp(V_m) / sum_k exp(V_k).

private_i = share of zone i's residents in condominiums, other apartments and landed housing (Census 2020);
central_j = 1 if zone j is in URA's Central Area.

Calibration maximises the (pseudo) log-likelihood of observed mode counts on two margins at once: by planning
area of residence and by planning area of workplace, each modelled share being the trip-weighted average of the
OD-level probabilities.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

MODES = ("car", "pt", "other")
PARAMS = ("asc_car", "asc_other", "b_time", "b_priv", "b_central", "b_dist_other")


def probabilities(V: np.ndarray) -> np.ndarray:
    """Softmax over the first axis."""
    V = np.asarray(V, dtype=float)
    e = np.exp(V - V.max(axis=0, keepdims=True))
    return e / e.sum(axis=0, keepdims=True)


def utilities(theta, t_car, g_pt, dist, private, central) -> np.ndarray:
    asc_car, asc_other, b_time, b_priv, b_central, b_dist = theta
    v_car = asc_car + b_time * t_car + b_priv * private[:, None] + b_central * central[None, :]
    v_pt = b_time * g_pt
    v_other = asc_other + b_dist * dist
    return np.stack([v_car, v_pt, np.broadcast_to(v_other, v_car.shape)])


def group_shares(T: np.ndarray, P: np.ndarray, group: np.ndarray, n_groups: int, axis: int) -> np.ndarray:
    """Mode shares by group of origins (axis=0) or destinations (axis=1). Returns (n_groups, n_modes)."""
    flows = (P * T[None, :, :]).sum(axis=2 - axis)  # (modes, zones)
    out = np.zeros((n_groups, P.shape[0]))
    ok = group >= 0
    for m in range(P.shape[0]):
        out[:, m] = np.bincount(group[ok], weights=flows[m][ok], minlength=n_groups)
    tot = out.sum(axis=1, keepdims=True)
    return np.divide(out, tot, out=np.zeros_like(out), where=tot > 0)


def log_likelihood(theta, T, X, obs_res, res_group, obs_work, work_group) -> float:
    P = probabilities(utilities(theta, *X))
    ll = 0.0
    for obs, grp, axis in ((obs_res, res_group, 0), (obs_work, work_group, 1)):
        if obs is None:
            continue
        S = group_shares(T, P, grp, obs.shape[0], axis)
        ll += float(np.sum(obs * np.log(np.clip(S, 1e-300, None))))
    return ll


def calibrate(T, X, obs_res, res_group, obs_work, work_group, x0=None):
    """Maximum (pseudo) likelihood estimates. Returns (theta, log-likelihood, optimiser result)."""
    if x0 is None:
        x0 = np.array([0.0, -1.0, -0.05, 1.0, -0.5, 0.0])
    res = minimize(lambda th: -log_likelihood(th, T, X, obs_res, res_group, obs_work, work_group), x0=x0,
                   method="BFGS", options={"gtol": 1e-6, "maxiter": 2000})
    return res.x, -float(res.fun), res
