"""Static user-equilibrium traffic assignment: BPR link costs, Frank-Wolfe and bi-conjugate Frank-Wolfe.

Link performance (Bureau of Public Roads 1964 form):  t(x) = t0 * (1 + alpha * (x / c) ** beta).
Links with alpha = 0 (centroid connectors) have constant cost.

Beckmann objective:  Z(x) = sum_a  integral_0^x_a t_a(w) dw
                          = sum_a  t0_a * (x_a + alpha_a * c_a / (beta_a + 1) * (x_a / c_a) ** (beta_a + 1)).

Convergence measure (computed every iteration from an all-or-nothing load y at the current costs):
    TSTT = sum_a x_a t_a(x_a)      SPTT = sum_rs q_rs u_rs = sum_a y_a t_a(x_a)
    relative gap = (TSTT - SPTT) / SPTT,   average excess cost = (TSTT - SPTT) / sum_rs q_rs.

Directions:
    FW   d = y - x.
    BFW  bi-conjugate direction of Mitradjieva & Lindberg (2013, Transportation Science 47(2), 280-293): the
         target s_k is a convex combination of y_k and the two previous targets, chosen to be conjugate to the
         two previous directions with respect to the diagonal Hessian of Z at x_k. If the combination is not a
         descent direction the step falls back to plain FW.
Line search: bisection on dZ/dlambda along x + lambda d, lambda in [0, 1].
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .paths import Graph, aon


def bpr_time(t0, cap, x, alpha, beta):
    x = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(alpha > 0, x / cap, 0.0)
    return t0 * (1.0 + alpha * r ** beta)


def bpr_derivative(t0, cap, x, alpha, beta):
    """dt/dx."""
    x = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(alpha > 0, x / cap, 0.0)
        out = np.where(alpha > 0, t0 * alpha * beta / cap * r ** (beta - 1.0), 0.0)
    return out


def bpr_integral(t0, cap, x, alpha, beta):
    """integral_0^x t(w) dw."""
    x = np.asarray(x, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(alpha > 0, x / cap, 0.0)
        extra = np.where(alpha > 0, alpha * cap / (beta + 1.0) * r ** (beta + 1.0), 0.0)
    return t0 * (x + extra)


@dataclass
class Network:
    """A road network ready for assignment. Costs are in hours (or any time unit), capacities in pcu/h."""

    graph: Graph
    t0: np.ndarray
    capacity: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray

    def time(self, x):
        return bpr_time(self.t0, self.capacity, x, self.alpha, self.beta)

    def derivative(self, x):
        return bpr_derivative(self.t0, self.capacity, x, self.alpha, self.beta)

    def objective(self, x):
        return float(np.sum(bpr_integral(self.t0, self.capacity, x, self.alpha, self.beta)))


@dataclass
class AssignmentResult:
    flow: np.ndarray
    time: np.ndarray
    iterations: int
    relative_gap: float
    average_excess_cost: float
    tstt: float
    sptt: float
    objective: float
    history: list = field(default_factory=list)
    converged: bool = False
    snapshots: dict = field(default_factory=dict)   # {gap: (iteration, flows)} at the first iteration with rg <= gap


def line_search(net: Network, x: np.ndarray, d: np.ndarray, tol: float = 1e-12, max_iter: int = 200) -> float:
    """lambda in [0, 1] minimising Z(x + lambda d), by bisection on g(lambda) = sum_a t_a(x + lambda d) d_a."""

    def g(lam):
        return float(np.dot(net.time(x + lam * d), d))

    if g(0.0) >= 0.0:
        return 0.0
    if g(1.0) <= 0.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if g(mid) < 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def relative_gap(tstt: float, sptt: float) -> float:
    return (tstt - sptt) / sptt


def descent_or_fw(t: np.ndarray, x: np.ndarray, s: np.ndarray, y: np.ndarray):
    """Keep the target s if s - x is a descent direction at link costs t; otherwise fall back to the FW target y.
    Returns (target, restarted)."""
    if float(np.dot(t, s - x)) >= 0.0:
        return y, True
    return s, False


def _bfw_target(net: Network, x, y, s1, s2, tau, delta=1e-4):
    """Bi-conjugate target s_k (Mitradjieva & Lindberg 2013, section 3.2), with tau the previous step length."""
    h = net.derivative(x)  # diagonal Hessian of Z at x
    d_fw = y - x
    d1 = s1 - x                                  # previous direction, seen from x_k
    d2 = tau * s1 + (1.0 - tau) * s2 - x         # the one before, seen from x_k
    den_mu = float(np.dot(d2 * h, s2 - s1))
    mu = -float(np.dot(d2 * h, d_fw)) / den_mu if den_mu != 0.0 else 0.0
    mu = max(0.0, mu)
    den_nu = float(np.dot(d1 * h, d1))
    nu = (-float(np.dot(d1 * h, d_fw)) / den_nu if den_nu != 0.0 else 0.0) + mu * tau / max(1.0 - tau, delta)
    nu = max(0.0, nu)
    b0 = 1.0 / (1.0 + mu + nu)
    return b0 * y + nu * b0 * s1 + mu * b0 * s2


def assign(net: Network, origins, dest_nodes, demand, method: str = "bfw", rgap_target: float = 1e-4,
           max_iter: int = 2000, x0: np.ndarray | None = None, verbose: bool = False,
           snapshot_gaps: tuple = ()) -> AssignmentResult:
    """User-equilibrium assignment of demand[o, d] from node origins[o] to node dest_nodes[d].
    snapshot_gaps: looser gaps at which a copy of the flows is kept (first iteration that reaches each)."""
    if method not in ("fw", "bfw"):
        raise ValueError("method must be 'fw' or 'bfw'")
    demand = np.asarray(demand, dtype=float)
    total = float(demand.sum())
    if x0 is None:
        x, _ = aon(net.graph, net.t0, origins, dest_nodes, demand)
    else:
        x = np.asarray(x0, dtype=float).copy()
    s1 = s2 = None
    tau = 0.0
    history = []
    snapshots: dict = {}
    rg = np.inf
    it = 0
    tstt = sptt = np.nan
    for it in range(1, max_iter + 1):
        t = net.time(x)
        y, sptt = aon(net.graph, t, origins, dest_nodes, demand)
        tstt = float(np.dot(x, t))
        rg = relative_gap(tstt, sptt)
        history.append(rg)
        for sg in snapshot_gaps:
            if sg not in snapshots and rg <= sg:
                snapshots[sg] = (it, x.copy())
        if verbose and (it % 25 == 0 or it < 5):
            print(f"  iter {it:4d}  relative gap {rg:.3e}")
        if rg <= rgap_target:
            break
        if method == "bfw" and s1 is not None and s2 is not None and 0.0 < tau < 1.0:
            s = _bfw_target(net, x, y, s1, s2, tau)
        elif method == "bfw" and s1 is not None and 0.0 < tau < 1.0:
            # conjugate (CFW) step for the second iteration
            h = net.derivative(x)
            d1 = s1 - x
            den = float(np.dot(d1 * h, y - s1))
            a = float(np.dot(d1 * h, y - x)) / den if den != 0.0 else 0.0
            a = min(max(a, 0.0), 1.0 - 1e-4)
            s = a * s1 + (1.0 - a) * y
        else:
            s = y
        s, restarted = descent_or_fw(t, x, s, y)
        if restarted:  # not a descent direction: restart with FW
            s1 = s2 = None
        d = s - x
        lam = line_search(net, x, d)
        x = x + lam * d
        s2, s1, tau = s1, s, lam
    t = net.time(x)
    return AssignmentResult(flow=x, time=t, iterations=it, relative_gap=float(rg),
                            average_excess_cost=float((tstt - sptt) / total) if total > 0 else 0.0,
                            tstt=float(tstt), sptt=float(sptt), objective=net.objective(x), history=history,
                            converged=bool(rg <= rgap_target), snapshots=snapshots)


def equilibrium_gap(net: Network, flow: np.ndarray, origins, dest_nodes, demand) -> dict:
    """Independent check of a flow vector: relative gap from one all-or-nothing load at the flow's own costs."""
    t = net.time(flow)
    _, sptt = aon(net.graph, t, origins, dest_nodes, demand)
    tstt = float(np.dot(flow, t))
    return {"tstt": tstt, "sptt": sptt, "relative_gap": relative_gap(tstt, sptt)}
