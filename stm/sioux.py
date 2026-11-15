"""Verification of the assignment code on the Sioux Falls network (bstabler/TransportationNetworks).

The repository's README for Sioux Falls gives the best known solution: link flows in SiouxFalls_flow.tntp with an
average excess cost of 3.9e-15 and an optimal Beckmann objective of 42.31335287107440 (in units of 10^5). The files
are downloaded by scripts/fetch_data.py --only sioux_falls (they are for academic research use and are not
redistributed here).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import tntp
from .assignment import assign, equilibrium_gap

BEST_KNOWN_OBJECTIVE_1E5 = 42.31335287107440
RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "sioux_falls"


def available(raw: Path = RAW) -> bool:
    return all((raw / f).exists() for f in ("SiouxFalls_net.tntp", "SiouxFalls_trips.tntp", "SiouxFalls_flow.tntp"))


def verify(raw: Path = RAW) -> dict:
    net = tntp.read_net(raw / "SiouxFalls_net.tntp")
    od = tntp.read_trips(raw / "SiouxFalls_trips.tntp", 24)
    pub = tntp.read_flow(raw / "SiouxFalls_flow.tntp")
    N = tntp.network(net)
    z = np.arange(24)
    out = {"links": int(N.graph.n_links), "zones": 24, "demand": float(od.sum()),
           "published_objective_1e5": BEST_KNOWN_OBJECTIVE_1E5,
           "published_flows_objective_1e5": N.objective(pub["volume"]) / 1e5,
           "published_flows_relative_gap": equilibrium_gap(N, pub["volume"], z, z, od)["relative_gap"],
           "published_tstt": float(np.dot(pub["volume"], N.time(pub["volume"])))}
    for method, target in (("bfw", 1e-4), ("fw", 1e-4), ("bfw", 1e-6)):
        r = assign(N, z, z, od, method=method, rgap_target=target, max_iter=50000)
        diff = np.abs(r.flow - pub["volume"])
        out[f"{method}_{target:.0e}"] = {
            "iterations": r.iterations, "relative_gap": r.relative_gap, "converged": r.converged,
            "objective_1e5": r.objective / 1e5,
            "objective_rel_diff": (r.objective / 1e5 - BEST_KNOWN_OBJECTIVE_1E5) / BEST_KNOWN_OBJECTIVE_1E5,
            "tstt": r.tstt, "max_abs_flow_diff": float(diff.max()),
            "max_rel_flow_diff": float((diff / pub["volume"]).max()),
            "mean_abs_flow_diff": float(diff.mean())}
    return out
