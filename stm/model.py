"""Model building blocks: inputs, trip ends, the road network with zone connectors, car and public-transport skims.

All distances are kilometres, link costs in the road network are hours, generalised public-transport times are
minutes. Zones are MP2019 subzones (index 0..331 = zone id - 1).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from .assignment import Network
from .paths import Graph, skim

REPO = Path(__file__).resolve().parents[1]
INPUTS = REPO / "data" / "inputs"
NON_WORKPLACE = ("Total", "Other Planning Areas or Outside Singapore", "No Fixed Location for Work", "Works from Home")
REGIONS = ("CENTRAL REGION", "EAST REGION", "NORTH REGION", "NORTH-EAST REGION", "WEST REGION")


def v(cfg_entry):
    """Value of a labelled config entry."""
    return cfg_entry["value"]


def load_config(repo: Path = REPO) -> dict:
    return {"model": json.loads((repo / "config" / "model.json").read_text(encoding="utf-8")),
            "rail": json.loads((repo / "config" / "rail.json").read_text(encoding="utf-8"))}


def load_inputs(inputs: Path = INPUTS) -> dict:
    r = {}
    r["zones"] = pd.read_csv(inputs / "zones.csv")
    r["pop"] = pd.read_csv(inputs / "census2020_population_subzone.csv")
    r["dwelling"] = pd.read_csv(inputs / "census2020_population_dwelling_subzone.csv")
    r["mode_res"] = pd.read_csv(inputs / "census2020_mode_residence_pa.csv")
    r["workplace"] = pd.read_csv(inputs / "census2020_workplace_region_mode.csv")
    r["landuse"] = pd.read_csv(inputs / "landuse_subzone.csv")
    r["tengah"] = pd.read_csv(inputs / "tengah_parcels.csv")
    r["nodes"] = pd.read_csv(inputs / "road_nodes.csv")
    r["links"] = pd.read_csv(inputs / "road_links.csv", keep_default_na=False, na_values={"lanes_tag": [""],
                                                                                         "maxspeed_tag_kmh": [""]})
    r["lta_stations"] = pd.read_csv(inputs / "lta_station_positions.csv")
    r["osm_station_codes"] = pd.read_csv(inputs / "rail_stations_osm.csv", keep_default_na=False)
    r["osm_station_names"] = pd.read_csv(inputs / "rail_station_names_osm.csv", keep_default_na=False)
    for ym in ("202607", "202608"):
        r[f"bus_od_{ym}"] = pd.read_csv(inputs / f"bus_od_{ym}.csv")
        r[f"bus_hourly_{ym}"] = pd.read_csv(inputs / f"bus_hourly_{ym}.csv")
        r[f"bus_stop_tld_{ym}"] = pd.read_csv(inputs / f"bus_stop_tld_{ym}.csv")
    return r


# ---------------------------------------------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------------------------------------------
def zone_table(inp: dict) -> pd.DataFrame:
    z = inp["zones"].merge(inp["pop"], on="zone", how="left").merge(
        inp["dwelling"][["zone", "condo_other_apartments", "landed"]], on="zone", how="left")
    z = z.fillna({"pop_total": 0, "pop_15plus": 0, "pop_15_64": 0, "pop_20_64": 0, "condo_other_apartments": 0,
                  "landed": 0})
    z["private_share"] = np.where(z.pop_total > 0, (z.condo_other_apartments + z.landed) / z.pop_total.clip(lower=1),
                                  0.0)
    z["central"] = (z.central_area == "Y").astype(float)
    return z.sort_values("zone").reset_index(drop=True)


def job_weights(inp: dict, cfg: dict, nz: int) -> np.ndarray:
    g = cfg["model"]["generation"]
    w = v(g["job_weight_per_m2_gfa"])
    pr = v(g["plot_ratio_defaults"])
    lu = inp["landuse"]
    gfa = lu.gfa_numeric_gpr_m2 + lu.site_area_gpr_lnd_m2 * pr["LND"] + lu.site_area_gpr_other_code_m2 * pr["other_codes"]
    wt = gfa * lu.lu_desc.map(w).fillna(0.0)
    return np.bincount(lu.zone.values - 1, weights=wt.values, minlength=nz)


def pa_title(name: str) -> str:
    return name.strip().upper()


def trip_ends_2020(inp: dict, cfg: dict, z: pd.DataFrame) -> dict:
    """Daily commuting trip ends (employed residents with a fixed workplace in a named planning area, who
    travel to work) before the attendance and peak-hour factors."""
    nz = len(z)
    wp = inp["workplace"]
    named = wp[~wp.workplace.isin(NON_WORKPLACE)]
    trav = named[named["mode"].isin(["pt", "car_taxi", "other"]) & (named.region_of_residence != "TOTAL")]
    N = trav.pivot_table(index="region_of_residence", columns="workplace", values="persons", aggfunc="sum").fillna(0)
    N = N.loc[list(REGIONS)]
    P_region = N.sum(axis=1)
    A_pa = N.sum(axis=0)

    # productions: region totals -> planning areas of residence (residence table) -> subzones (residents 20-64)
    mr = inp["mode_res"].set_index("planning_area")
    w_res = (mr["Total"] - mr["NoTransportRequired"]).astype(float)
    pa_region = z.groupby("planning_area").region.first()
    pa_pop = z.groupby("planning_area").pop_20_64.sum()
    listed = {pa_title(p) for p in w_res.index if p not in ("Total", "Others")}
    unknown = listed - set(pa_region.index)
    if unknown:
        raise ValueError(f"residence planning areas not in MP2019: {sorted(unknown)}")
    others = [p for p in pa_region.index if p not in listed]
    w_pa = pd.Series(0.0, index=pa_region.index)
    for p in w_res.index:
        if p not in ("Total", "Others"):
            w_pa[pa_title(p)] = w_res[p]
    share_o = pa_pop[others] / pa_pop[others].sum()
    w_pa[others] = w_res["Others"] * share_o
    prod_pa = pd.Series(0.0, index=pa_region.index)
    for reg in REGIONS:
        m = pa_region == reg
        prod_pa[m] = P_region[reg] * w_pa[m] / w_pa[m].sum()
    pw = cfg["model"]["generation"]["production_weight"]["value"]
    sz_w = z[pw].astype(float)
    pa_tot_w = z.groupby("planning_area")[pw].transform("sum").astype(float)
    O = np.where(pa_tot_w > 0, prod_pa.reindex(z.planning_area).values * sz_w / pa_tot_w.clip(lower=1e-9), 0.0)

    # attractions: named workplace planning areas -> subzones by job weight (by area if a PA has none)
    jw = job_weights(inp, cfg, nz)
    D = np.zeros(nz)
    for p, tot in A_pa.items():
        m = (z.planning_area == pa_title(p)).values
        if not m.any():
            raise ValueError(f"workplace planning area {p} not in MP2019")
        wts = jw[m] if jw[m].sum() > 0 else z.area_km2.values[m]
        D[m] = tot * wts / wts.sum()
    region_idx = {r: k for k, r in enumerate(REGIONS)}
    wp_names = [pa_title(p) for p in N.columns]
    wp_idx = {p: k for k, p in enumerate(wp_names)}
    return {"O": O, "D": D, "N_region_workplace": N.values, "regions": list(REGIONS), "workplaces": wp_names,
            "zone_region": z.region.map(region_idx).values.astype(int),
            "zone_workplace": z.planning_area.map(wp_idx).fillna(-1).values.astype(int),
            "job_weight": jw, "production_by_pa": prod_pa, "residence_others": others}


def peak_hour_share(inp: dict, cfg: dict, ym: str = "202607") -> float:
    h = inp[f"bus_hourly_{ym}"].set_index("hour").weekday_trips_month_total
    lo, hi = v(cfg["model"]["period"]["morning_window"])
    pk = v(cfg["model"]["period"]["am_peak_hour"])
    return float(h[pk] / h.loc[lo:hi].sum())


# ---------------------------------------------------------------------------------------------------------------
# road network
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class RoadModel:
    net: Network
    n_road_nodes: int
    n_road_links: int
    origins: np.ndarray      # zone source node index per zone
    dests: np.ndarray        # zone sink node index per zone
    links: pd.DataFrame      # road links with model attributes
    length_km: np.ndarray    # all links incl. connectors


def road_model(inp: dict, cfg: dict, z: pd.DataFrame) -> RoadModel:
    a = cfg["model"]["assignment"]
    L = inp["links"].copy()
    nodes = inp["nodes"]
    n = len(nodes)
    cls = L.highway
    L["lanes"] = L.lanes_tag.fillna(cls.map(v(a["lanes_default"]))).astype(float).clip(lower=1)
    L["speed_limit_kmh"] = L.maxspeed_tag_kmh.fillna(cls.map(v(a["speed_default_kmh"]))).astype(float)
    L["ff_speed_kmh"] = L.speed_limit_kmh * cls.map(v(a["free_flow_speed_factor"]))
    L["capacity"] = L.lanes * cls.map(v(a["capacity_per_lane"]))
    L["length_km"] = L.length_m / 1000.0
    L["t0_h"] = L.length_km / L.ff_speed_kmh
    tail = (L.a.values - 1).astype(np.int64)
    head = (L.b.values - 1).astype(np.int64)
    # connectors from each zone centroid to its nearest nodes on non-motorway roads
    motor = cls.isin(["motorway", "motorway_link"]).values
    ok_nodes = np.zeros(n, dtype=bool)
    ok_nodes[tail[~motor]] = True
    ok_nodes[head[~motor]] = True
    cand = np.where(ok_nodes)[0]
    xy = nodes[["x", "y"]].values
    tree = cKDTree(xy[cand])
    k = int(v(a["connectors_per_zone"]))
    dd, ii = tree.query(z[["x", "y"]].values, k=k)
    nz = len(z)
    src = n + np.arange(nz)
    snk = n + nz + np.arange(nz)
    ct, ch, cl = [], [], []
    for zi in range(nz):
        for d, j in zip(np.atleast_1d(dd[zi]), np.atleast_1d(ii[zi])):
            node = cand[j]
            km = max(d, 1.0) / 1000.0 * v(a["connector_detour"])
            ct += [src[zi], node]
            ch += [node, snk[zi]]
            cl += [km, km]
    ct, ch, cl = np.array(ct), np.array(ch), np.array(cl)
    t_all = np.concatenate([tail, ct])
    h_all = np.concatenate([head, ch])
    g = Graph(t_all, h_all, n + 2 * nz)
    t0 = np.concatenate([L.t0_h.values, cl / v(a["connector_speed_kmh"])])
    cap = np.concatenate([L.capacity.values, np.full(cl.size, np.inf)])
    alpha = np.concatenate([np.full(len(L), v(a["bpr_alpha"])), np.zeros(cl.size)])
    beta = np.concatenate([np.full(len(L), v(a["bpr_beta"])), np.ones(cl.size)])
    net = Network(graph=g, t0=t0, capacity=cap, alpha=alpha, beta=beta)
    return RoadModel(net=net, n_road_nodes=n, n_road_links=len(L), origins=src, dests=snk, links=L,
                     length_km=np.concatenate([L.length_km.values, cl]))


def car_skims(rm: RoadModel, cfg: dict, link_time_h: np.ndarray | None = None):
    """Free-flow (or given) time in minutes and distance in km between zones, with intrazonal values."""
    t = rm.net.t0 if link_time_h is None else link_time_h
    th, dk = skim(rm.net.graph, t, rm.origins, rm.dests, rm.length_km)
    tmin = th * 60.0
    f = v(cfg["model"]["distribution"]["intrazonal_factor"])
    nz = len(rm.origins)
    d = dk.copy()
    off = d + np.diag(np.full(nz, np.inf))
    near = off.min(axis=1)
    d[np.arange(nz), np.arange(nz)] = f * near
    tm = tmin.copy()
    tm[np.arange(nz), np.arange(nz)] = d[np.arange(nz), np.arange(nz)] / v(cfg["model"]["assignment"]["connector_speed_kmh"]) * 60.0
    if not np.all(np.isfinite(d)):
        raise ValueError("unreachable zone pairs in the road skim")
    return tm, d


# ---------------------------------------------------------------------------------------------------------------
# public transport
# ---------------------------------------------------------------------------------------------------------------
def _station_positions(inp: dict, rail: dict, lines: dict, jrl: bool):
    lta = inp["lta_stations"].set_index("station")
    osm_c = inp["osm_station_codes"].set_index("code")
    osm_n = inp["osm_station_names"].assign(key=lambda d: d.name.str.upper()).drop_duplicates("key").set_index("key")
    over = rail["lta_name_overrides"]
    inter = rail["jrl"]["existing_interchanges"]
    pos = {}
    for lname, ln in lines.items():
        suffix = ln.get("lta_suffix", "MRT")
        for code, name in ln["stations"]:
            if code in pos:
                continue
            if code in inter:
                key = inter[code]
            elif code in over:
                key = over[code]
            else:
                key = f"{name.upper()} {suffix} STATION"
            if key in lta.index:
                pos[code] = (float(lta.loc[key, "x"]), float(lta.loc[key, "y"]), "lta")
            elif jrl and code in osm_c.index:
                pos[code] = (float(osm_c.loc[code, "x"]), float(osm_c.loc[code, "y"]), "osm_code")
            elif jrl and name.upper() in osm_n.index:
                pos[code] = (float(osm_n.loc[name.upper(), "x"]), float(osm_n.loc[name.upper(), "y"]), "osm_name")
            else:
                raise ValueError(f"no position for station {code} {name}")
    return pos


def rail_lines(rail: dict, with_jrl: bool) -> dict:
    lines = dict(rail["lines"])
    if with_jrl:
        lines.update(rail["jrl"]["lines"])
    return lines


def pt_skims(inp: dict, cfg: dict, z: pd.DataFrame, d_road: np.ndarray, with_jrl: bool):
    """Generalised PT time (minutes): the better of a bus-only alternative and the best rail path."""
    p = cfg["model"]["pt"]
    rail = cfg["rail"]
    lines = rail_lines(rail, with_jrl)
    pos = _station_positions(inp, rail, lines, with_jrl)
    speeds = rail["speeds_kmh"]
    align = v(rail["alignment_factor"])
    nz = len(z)
    # line-station nodes
    nodes = {}
    for lname, ln in lines.items():
        for code, name in ln["stations"]:
            nodes.setdefault((lname, code), len(nodes))
    nn = len(nodes)
    src = nn + np.arange(nz)
    snk = nn + nz + np.arange(nz)
    T, H, C = [], [], []
    for lname, ln in lines.items():
        sp = v(speeds[ln["mode"]])
        st = ln["stations"]
        for (c1, _), (c2, _) in zip(st[:-1], st[1:]):
            dkm = np.hypot(pos[c1][0] - pos[c2][0], pos[c1][1] - pos[c2][1]) / 1000.0 * align
            tmin = dkm / sp * 60.0
            a, b = nodes[(lname, c1)], nodes[(lname, c2)]
            T += [a, b]
            H += [b, a]
            C += [tmin, tmin]
    # transfers between line-station nodes of the same station complex (same name)
    name_of = {}
    for lname, ln in lines.items():
        for code, name in ln["stations"]:
            name_of[(lname, code)] = name.upper()
    by_name = {}
    for key, idx in nodes.items():
        by_name.setdefault(name_of[key], []).append(idx)
    tr = (v(p["walk_weight"]) * v(p["transfer_walk_min"]) + v(p["wait_weight"]) * v(p["rail_wait_min"])
          + v(p["transfer_penalty_min"]))
    for idxs in by_name.values():
        for a in idxs:
            for b in idxs:
                if a != b:
                    T.append(a)
                    H.append(b)
                    C.append(tr)
    # access and egress
    code_xy = np.array([pos[c][:2] for (_, c) in nodes])
    tree = cKDTree(code_xy)
    zxy = z[["x", "y"]].values
    det = v(p["walk_detour"])
    for zi in range(nz):
        for j in tree.query_ball_point(zxy[zi], v(p["max_access_km"]) * 1000.0):
            dkm = max(np.hypot(*(code_xy[j] - zxy[zi])), 50.0) / 1000.0 * det
            walk = dkm / v(p["walk_speed_kmh"]) * 60.0 * v(p["walk_weight"]) if dkm <= v(p["max_walk_km"]) else np.inf
            feeder = v(p["wait_weight"]) * v(p["feeder_wait_min"]) + dkm / v(p["feeder_speed_kmh"]) * 60.0
            acc = min(walk, feeder)
            T += [src[zi], j]
            H += [j, snk[zi]]
            C += [acc + v(p["wait_weight"]) * v(p["rail_wait_min"]), acc]
    g = Graph(np.array(T), np.array(H), nn + 2 * nz)
    cost = np.array(C, dtype=float)
    g_rail, ivt = skim(g, cost, src, snk, cost)
    g_bus = (v(p["walk_weight"]) * 2 * v(p["bus_access_walk_min"]) + v(p["wait_weight"]) * v(p["bus_wait_min"])
             + d_road / v(p["bus_speed_kmh"]) * 60.0)
    g_pt = np.minimum(g_rail, g_bus)
    info = {"stations": len({c for (_, c) in nodes}), "line_station_nodes": nn,
            "positions_from_osm": sorted(c for c, (_, _, s) in pos.items() if s != "lta")}
    return g_pt, g_rail, g_bus, info, pos
