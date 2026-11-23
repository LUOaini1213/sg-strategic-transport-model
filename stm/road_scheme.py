"""A stylised road scheme inside the existing network: more lanes on one direction of one named road.

The scheme is ILLUSTRATIVE (config/road_scheme.json). The corridor is picked from the model's own results by a
stated rule, the with-scheme network is assigned with the same demand as the do-minimum, and the pair is passed to
stm/appraisal.py, so that a road project and the rail line are appraised on the same basis.

Demand is fixed: the model has no feedback from road times to destination or mode choice. Only routes change.
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import logit as L
from .assignment import Network

REPO = Path(__file__).resolve().parents[1]
DIRECTIONS = {"southbound": (1, -1.0), "northbound": (1, 1.0), "westbound": (0, -1.0), "eastbound": (0, 1.0)}


def load_config(repo: Path = REPO) -> dict:
    return json.loads((repo / "config" / "road_scheme.json").read_text(encoding="utf-8"))


def v(entry):
    return entry["value"]


def heading(links: pd.DataFrame, node_xy: np.ndarray, direction: str) -> np.ndarray:
    """True for links that run in the given compass direction (end node beyond the start node on that axis)."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {sorted(DIRECTIONS)}")
    axis, sign = DIRECTIONS[direction]
    a = links.a.values - 1
    b = links.b.values - 1
    return sign * (node_xy[b, axis] - node_xy[a, axis]) > 0


def select_links(links: pd.DataFrame, node_xy: np.ndarray, rc: dict) -> np.ndarray:
    """Links of the scheme: the named road, the given class, the given direction."""
    s = rc["scheme"]
    m = (links.name.values == v(s["road_name"])) & (links.highway.values == v(s["highway"]))
    m &= heading(links, node_xy, v(s["direction"]))
    if not m.any():
        raise ValueError("the road scheme selects no link")
    return m


def corridor_ranking(lf: pd.DataFrame, vc_column: str, threshold: float) -> pd.DataFrame:
    """Named roads (by OpenStreetMap name and class) ranked by directed km above a volume/capacity threshold."""
    d = lf[lf.name.astype(str) != ""].copy()
    d["over"] = d.length_km * (d[vc_column] > threshold)
    d["vc_km"] = d.length_km * d[vc_column]
    g = d.groupby(["name", "highway"], as_index=False).agg(
        directed_km=("length_km", "sum"), km_over_threshold=("over", "sum"), vc_km=("vc_km", "sum"),
        max_vc=(vc_column, "max"), links=("length_km", "size"))
    g["mean_vc_km_weighted"] = g.vc_km / g.directed_km
    g = g.drop(columns="vc_km")
    return g.sort_values(["km_over_threshold", "name", "highway"], ascending=[False, True, True],
                         kind="mergesort").reset_index(drop=True)


def widen(rm, mask: np.ndarray, added_lanes: float, capacity_per_lane: dict):
    """A copy of the road model with ``added_lanes`` more lanes on the selected road links. Capacity rises by the
    per-lane capacity of each link's class; free-flow times and everything else stay as they are."""
    mask = np.asarray(mask, dtype=bool)
    if mask.size != rm.n_road_links:
        raise ValueError("the mask must have one entry per road link")
    links = rm.links.copy()
    add = added_lanes * links.highway.map(capacity_per_lane).astype(float).values * mask
    links["lanes"] = links.lanes.values + added_lanes * mask
    links["capacity"] = links.capacity.values + add
    cap = rm.net.capacity.copy()
    cap[: rm.n_road_links] = cap[: rm.n_road_links] + add
    net = Network(graph=rm.net.graph, t0=rm.net.t0, capacity=cap, alpha=rm.net.alpha, beta=rm.net.beta)
    return replace(rm, net=net, links=links)


def car_probability_after_time_change(theta, t_car, dt_min, g_pt, dist, private, central, industrial) -> np.ndarray:
    """Car probability of the mode-choice model when car times change by ``dt_min`` minutes (negative = faster).
    A first-round response only: the new car trips are not assigned, so the times do not react to them."""
    return L.probabilities(L.utilities(theta, t_car + dt_min, g_pt, dist, private, central, industrial))[0]


def appraisal_config(ac: dict, rc: dict) -> dict:
    """The appraisal parameters of the rail line with the road scheme's scenario names and costs."""
    out = copy.deepcopy(ac)
    out["scheme"]["do_something"] = {"value": v(rc["scheme"]["name"]), "label": "ASSUMPTION"}
    out["costs"] = copy.deepcopy(rc["costs"])
    return out


def summarise(rm0, rm1, mask: np.ndarray, flow0: np.ndarray, flow1: np.ndarray, threshold: float) -> dict:
    """What the scheme does to the corridor and to the network (road links only; flows in pcu per peak hour)."""
    n = rm0.n_road_links
    km = rm0.links.length_km.values
    f0, f1 = flow0[:n], flow1[:n]
    c0, c1 = rm0.links.capacity.values, rm1.links.capacity.values
    t0, t1 = rm0.net.time(flow0)[:n], rm1.net.time(flow1)[:n]
    vc0, vc1 = f0 / c0, f1 / c1
    k = km[mask]

    def corridor(f, vc, t):
        return {"vehicle_km": float(np.dot(f[mask], k)), "mean_vc_km_weighted": float(np.dot(vc[mask], k) / k.sum()),
                "max_vc": float(vc[mask].max()), "km_over_threshold": float(k[vc[mask] > threshold].sum()),
                "mean_speed_kmh_flow_weighted": float(np.dot(f[mask], k) / np.dot(f[mask], t[mask]))}

    def network(f, vc, t):
        return {"vehicle_km": float(np.dot(f, km)), "vehicle_hours": float(np.dot(f, t)),
                "km_over_threshold": float(km[vc > threshold].sum())}

    other = ~mask
    d = f1 - f0
    return {"links": int(mask.sum()), "directed_km": float(k.sum()),
            "lanes_before_min": float(rm0.links.lanes.values[mask].min()),
            "lanes_before_max": float(rm0.links.lanes.values[mask].max()),
            "lane_km_added": float(np.dot(rm1.links.lanes.values[mask] - rm0.links.lanes.values[mask], k)),
            "capacity_added_share": float(c1[mask].sum() / c0[mask].sum() - 1.0),
            "corridor_without": corridor(f0, vc0, t0), "corridor_with": corridor(f1, vc1, t1),
            "network_without": network(f0, vc0, t0), "network_with": network(f1, vc1, t1),
            "corridor_traffic_growth": float(np.dot(f1[mask], k) / np.dot(f0[mask], k) - 1.0),
            "other_links_vc_down_by_0_05": int(np.sum(other & (vc1 - vc0 <= -0.05))),
            "other_links_vc_up_by_0_05": int(np.sum(other & (vc1 - vc0 >= 0.05))),
            "vehicle_km_moved_off_other_roads": float(-np.dot(d[other], km[other]))}
