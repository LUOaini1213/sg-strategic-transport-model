"""The whole model, from the committed inputs to results/ (offline, deterministic).

Steps
  a  zones                 332 MP2019 subzones
  b  trip generation       Census 2020 commuters by region/planning area -> subzones; AM peak-hour share
  c  distribution          doubly constrained gamma gravity model; commuters calibrated to the Census
                           region-of-residence x workplace matrix; a bus-trip gravity model calibrated to the
                           DataMall bus trip-length distribution (July 2026) and validated on August 2026
  d  mode choice           multinomial logit calibrated to Census mode shares by planning area
  e  assignment            bi-conjugate Frank-Wolfe user equilibrium, BPR links, relative gap <= 1e-4
  f  validation            bus OD comparison; road plausibility (V/C, screenlines); no traffic counts
  g  2030 scenarios        Tengah build-out, with and without the Jurong Region Line; junction growth factors
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath

from . import gravity as G
from . import junction as J
from . import logit as L
from . import model as M
from . import stats as S
from .assignment import assign, equilibrium_gap

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
WEST = "WEST REGION"


# ---------------------------------------------------------------------------------------------------------------
# small writers (LF, rounded, stable column order)
# ---------------------------------------------------------------------------------------------------------------
def _round(x, nd=6):
    if isinstance(x, (float, np.floating)):
        if not np.isfinite(x):
            return None
        return float(f"{float(x):.{nd}g}")
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, dict):
        return {k: _round(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v, nd) for v in x]
    if isinstance(x, np.ndarray):
        return [_round(v, nd) for v in x.tolist()]
    return x


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(_round(obj), indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


def write_csv(path: Path, df: pd.DataFrame, sig: int = 7) -> None:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]):
            out[c] = out[c].map(lambda v: "" if not np.isfinite(v) else f"{v:.{sig}g}")
    out.to_csv(path, index=False, lineterminator="\n")


# ---------------------------------------------------------------------------------------------------------------
def groups_matrix(groups: np.ndarray, n_groups: int) -> np.ndarray:
    R = np.zeros((n_groups, groups.size))
    ok = groups >= 0
    R[groups[ok], np.where(ok)[0]] = 1.0
    return R


def residence_groups(inp: dict, z: pd.DataFrame):
    mr = inp["mode_res"]
    rows = [p for p in mr.planning_area if p != "Total"]
    idx = {M.pa_title(p): k for k, p in enumerate(rows) if p != "Others"}
    other = rows.index("Others")
    g = np.array([idx.get(pa, other) for pa in z.planning_area])
    sub = mr.set_index("planning_area").loc[rows]
    obs = np.stack([sub.CarOnly + sub.Taxi_PrivateHireCarOnly,
                    sub.PublicBusOnly + sub.Rail_MRT_LRT_Only + sub.Rail_MRT_LRT_andPublicBusOnly
                    + sub.CombinationofRail_MRT_LRT_and_orPublicBus_withOtherModes,
                    sub.PrivateCharteredBus_VanOnly + sub.Lorry_PickupOnly + sub.Motorcycle_ScooterOnly + sub.Others],
                   axis=1).astype(float)
    return rows, g, obs


def workplace_mode_obs(inp: dict, te: dict):
    wp = inp["workplace"]
    w = wp[wp.region_of_residence == "TOTAL"].pivot_table(index="workplace", columns="mode", values="persons",
                                                          aggfunc="sum")
    w.index = [M.pa_title(p) for p in w.index]
    w = w.loc[te["workplaces"]]
    return w[["car_taxi", "pt", "other"]].values.astype(float)


def cell_mode_obs(inp: dict, te: dict):
    wp = inp["workplace"]
    w = wp[(wp.region_of_residence != "TOTAL") & ~wp.workplace.isin(M.NON_WORKPLACE)].copy()
    w["workplace"] = w.workplace.map(M.pa_title)
    out = np.zeros((len(M.REGIONS), len(te["workplaces"]), 3))
    ri = {r: k for k, r in enumerate(M.REGIONS)}
    wi = {p: k for k, p in enumerate(te["workplaces"])}
    mi = {"car_taxi": 0, "pt": 1, "other": 2}
    for r in w.itertuples():
        if r.mode in mi:
            out[ri[r.region_of_residence], wi[r.workplace], mi[r.mode]] += r.persons
    return out


def zone_of_points(xy: np.ndarray, geom: dict) -> np.ndarray:
    """Zone id (0-based) of each point by point-in-polygon on the simplified outlines; -1 if none."""
    out = np.full(len(xy), -1, dtype=int)
    for zg in geom["zones"]:
        for ring in zg["rings"]:
            p = MplPath(np.asarray(ring))
            m = (out < 0) & p.contains_points(xy)
            out[m] = zg["zone"] - 1
    return out


def car_demand(T_daily: np.ndarray, Pcar: np.ndarray, cfg: dict, phf: float) -> np.ndarray:
    a = cfg["model"]["assignment"]
    att = M.v(cfg["model"]["generation"]["attendance_factor"])
    Q = T_daily * att * phf * Pcar / M.v(a["car_occupancy"]) * M.v(a["background_factor"])
    np.fill_diagonal(Q, 0.0)
    return Q


def tengah_2030(inp: dict, cfg: dict, z: pd.DataFrame, te: dict):
    """Productions and extra attractions in Tengah for 2030 (daily commuters before attendance factor)."""
    s = cfg["model"]["scenario_2030"]
    t = inp["tengah"].copy()
    gpr = pd.to_numeric(t.gpr, errors="coerce")
    res_mask = t.lu_desc.isin(["RESIDENTIAL", "COMMERCIAL & RESIDENTIAL", "RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY"])
    mean_res_gpr = float(gpr[res_mask & gpr.notna()].mean())
    # residential floor area: numeric GPR, or the mean numeric GPR of Tengah's residential parcels for EVA/SDP codes
    t["gfa"] = t.site_area_m2 * gpr.fillna(mean_res_gpr)
    homes = M.v(s["tengah_homes"]) * M.v(s["tengah_buildout_by_2030"])
    pop = homes * M.v(s["persons_per_home"])
    west = (z.region == WEST).values
    per_resident = te["O"][west].sum() / z.pop_total.values[west].sum()
    nz = len(z)
    O_add = np.zeros(nz)
    r = t[res_mask]
    O_add += np.bincount(r.zone.values - 1, weights=(r.gfa / r.gfa.sum()).values * pop * per_resident, minlength=nz)
    w = M.v(cfg["model"]["generation"]["job_weight_per_m2_gfa"])
    nr = t[~res_mask].copy()
    nr["gfa_nr"] = nr.site_area_m2 * gpr[~res_mask].fillna(1.0)
    nr["jw"] = nr.gfa_nr * nr.lu_desc.map(w).fillna(0.0)
    jobs_per_weight = te["D"][west].sum() / te["job_weight"][west].sum()
    D_add = np.bincount(nr.zone.values - 1, weights=nr.jw.values * jobs_per_weight, minlength=nz)
    return O_add, D_add, {"homes": homes, "population": pop, "commuters_per_resident_west": per_resident,
                          "commuters": float(O_add.sum()), "tengah_jobs_attracted": float(D_add.sum()),
                          "mean_residential_gpr_used": mean_res_gpr}


def screenline(rm: M.RoadModel, xy: np.ndarray, flows: np.ndarray, x0: float, y_lo: float, y_hi: float):
    """Assigned flow crossing the line x = x0 (between y_lo and y_hi) eastbound and westbound."""
    a = rm.links.a.values - 1
    b = rm.links.b.values - 1
    xa, xb = xy[a, 0], xy[b, 0]
    ym = 0.5 * (xy[a, 1] + xy[b, 1])
    f = flows[: rm.n_road_links]
    inside = (ym >= y_lo) & (ym <= y_hi)
    east = inside & (xa < x0) & (xb >= x0)
    westb = inside & (xa >= x0) & (xb < x0)
    return float(f[east].sum()), float(f[westb].sum()), int(east.sum() + westb.sum())


# ---------------------------------------------------------------------------------------------------------------
def run(out: Path = RESULTS, assign_scenarios: bool = True, verbose: bool = True) -> dict:
    t_start = time.time()
    out.mkdir(parents=True, exist_ok=True)
    cfg = M.load_config()
    inp = M.load_inputs()
    z = M.zone_table(inp)
    nz = len(z)
    geom = json.loads((M.INPUTS / "zones_geometry.json").read_text(encoding="utf-8"))
    mcfg = cfg["model"]
    summary: dict = {"zones": {"n": nz, "with_residents": int((z.pop_total > 0).sum()),
                               "planning_areas": int(z.planning_area.nunique())}}

    def log(msg):
        if verbose:
            print(f"[{time.time() - t_start:6.1f}s] {msg}", flush=True)

    # ---- b. trip ends ------------------------------------------------------------------------------------------
    te = M.trip_ends_2020(inp, cfg, z)
    O, D = te["O"], te["D"]
    phf = M.peak_hour_share(inp, cfg, "202607")
    att = M.v(mcfg["generation"]["attendance_factor"])
    summary["generation"] = {"commuters_daily": float(O.sum()), "attendance_factor": att, "peak_hour_share": phf,
                             "am_peak_hour_trips": float(O.sum() * att * phf),
                             "zones_with_productions": int((O > 0).sum()),
                             "zones_with_attractions": int((D > 0).sum()),
                             "census_employed_residents": float(inp["mode_res"].set_index("planning_area")
                                                                .loc["Total", "Total"])}
    log("trip ends")

    # ---- road network and car skims ------------------------------------------------------------------------------
    rm = M.road_model(inp, cfg, z)
    node_xy = inp["nodes"][["x", "y"]].values
    t_ff, d = M.car_skims(rm, cfg)
    summary["network"] = {"road_nodes": rm.n_road_nodes, "road_links": rm.n_road_links,
                          "connectors": int(rm.net.graph.n_links - rm.n_road_links),
                          "road_km_directed": float(rm.links.length_km.sum()),
                          "lanes_from_tag_share": float((rm.links.lanes_src != "default").mean()),
                          "speed_from_tag_share": float(rm.links.maxspeed_tag_kmh.notna().mean())}
    log("road network and skims")

    # ---- c. distribution: commuters calibrated to the Census matrix -----------------------------------------------
    N = te["N_region_workplace"]
    a_c, b_c, ll_c, Mg = G.calibrate_gamma_aggregate(O, D, d, te["zone_region"], te["zone_workplace"], N)
    T = G.gravity(O, D, d, "gamma", a_c, b_c)
    Rr = groups_matrix(te["zone_region"], len(M.REGIONS))
    Cw = groups_matrix(te["zone_workplace"], len(te["workplaces"])).T
    Dbar = (Rr @ (O[:, None] * D[None, :] * d) @ Cw) / np.maximum(Rr @ (O[:, None] * D[None, :]) @ Cw, 1e-12)
    cells = pd.DataFrame([(M.REGIONS[i], te["workplaces"][j], N[i, j], Mg[i, j], Dbar[i, j])
                          for i in range(N.shape[0]) for j in range(N.shape[1])],
                         columns=["region_of_residence", "workplace", "census_commuters", "modelled_commuters",
                                  "mean_zone_pair_km"])
    obs_cell_mean = float((N * Dbar).sum() / N.sum())
    mod_cell_mean = float((Mg * Dbar).sum() / Mg.sum())
    edges, h_mod = G.tld(T, d, M.v(mcfg["distribution"]["tld_bin_km"]))
    bins = np.digitize(Dbar, edges) - 1
    p_obs = np.bincount(bins.ravel(), weights=N.ravel(), minlength=len(edges))
    p_mod = np.bincount(bins.ravel(), weights=Mg.ravel(), minlength=len(edges))
    summary["distribution_commute"] = {
        "deterrence": "gamma", "a": a_c, "b_per_km": b_c, "log_likelihood": ll_c,
        "cells": int(N.size), "r2_cells": S.r_squared(Mg, N), "srmse_cells": S.srmse(Mg, N),
        "mean_km_model_zone_level": G.mean_cost(T, d),
        "mean_km_cell_level_census": obs_cell_mean, "mean_km_cell_level_model": mod_cell_mean,
        "coincidence_ratio_cell_level": G.coincidence_ratio(p_obs, p_mod),
        "intrazonal_share_model": float(np.trace(T) / T.sum())}
    write_csv(out / "calibration_commute_cells.csv", cells)
    log(f"commute gravity a={a_c:.3f} b={b_c:.4f}")

    # ---- c/f. bus layer ---------------------------------------------------------------------------------------------
    pk = M.v(mcfg["period"]["am_peak_hour"])
    days = M.v(mcfg["period"]["bus_weekdays"])
    pa_names = sorted(z.planning_area.unique())
    pa_idx = {p: k for k, p in enumerate(pa_names)}
    Rpa = groups_matrix(z.planning_area.map(pa_idx).values, len(pa_names))
    bus = {}
    tld_rows = []
    pair_tables = {}
    for ym in ("202607", "202608"):
        od = inp[f"bus_od_{ym}"]
        od = od[od.hour == pk]
        Ob = np.zeros((nz, nz))
        np.add.at(Ob, (od.o_zone.values - 1, od.d_zone.values - 1), od.weekday_trips_month_total.values / days[ym])
        bus[ym] = Ob
    obs_c = bus["202607"]
    tgt_m, tgt_l = G.mean_cost(obs_c, d), G.mean_log_cost(obs_c, d)
    a_b, b_b, resid_b = G.calibrate_gamma_moments(obs_c.sum(1), obs_c.sum(0), d, tgt_m, tgt_l)
    b_exp = G.calibrate_exponential_mean(obs_c.sum(1), obs_c.sum(0), d, tgt_m)
    bus_summary = {"deterrence": "gamma", "a": a_b, "b_per_km": b_b, "moment_residual": resid_b,
                   "exponential_b_per_km": b_exp, "calibration_month": "2026-07", "validation_month": "2026-08",
                   "am_peak_hour": f"{pk:02d}:00-{pk + 1:02d}:00"}
    for ym, role in (("202607", "calibration"), ("202608", "validation")):
        Ob = bus[ym]
        Tb = G.gravity(Ob.sum(1), Ob.sum(0), d, "gamma", a_b, b_b)
        Te = G.gravity(Ob.sum(1), Ob.sum(0), d, "exponential", b=b_exp)
        e, ho = G.tld(Ob, d, M.v(mcfg["distribution"]["tld_bin_km"]))
        _, hm = G.tld(Tb, d, M.v(mcfg["distribution"]["tld_bin_km"]))
        _, he = G.tld(Te, d, M.v(mcfg["distribution"]["tld_bin_km"]))
        for k in range(len(ho)):
            tld_rows.append([ym, e[k], e[k + 1], ho[k], hm[k], he[k]])
        Po, Pm = Rpa @ Ob @ Rpa.T, Rpa @ Tb @ Rpa.T
        m = (Po + Pm) > 0
        gh = S.geh(Pm, Po)
        inter = m & ~np.eye(len(pa_names), dtype=bool)
        bus_summary[role] = {
            "trips_per_hour": float(Ob.sum()), "mean_km_observed": G.mean_cost(Ob, d),
            "mean_km_model": G.mean_cost(Tb, d), "mean_km_model_exponential": G.mean_cost(Te, d),
            "coincidence_ratio": G.coincidence_ratio(ho, hm), "coincidence_ratio_exponential": G.coincidence_ratio(ho, he),
            "intrazonal_share_observed": float(np.trace(Ob) / Ob.sum()), "intrazonal_share_model": float(np.trace(Tb) / Tb.sum()),
            "r2_zone_pairs": S.r_squared(Tb, Ob), "pa_pairs": int(m.sum()),
            "geh_lt5_share_pa_pairs": S.share_within(gh[m], 5.0), "geh_lt10_share_pa_pairs": S.share_within(gh[m], 10.0),
            "r2_pa_pairs": S.r_squared(Pm[m], Po[m]), "r2_pa_pairs_excluding_intra_pa": S.r_squared(Pm[inter], Po[inter]),
            "geh_lt5_share_pa_pairs_over_100": S.share_within(gh[m & (Po >= 100)], 5.0),
            "pa_pairs_over_100": int((m & (Po >= 100)).sum())}
        if role == "validation":
            ii, jj = np.where(m)
            pair_tables[ym] = pd.DataFrame({"origin_pa": [pa_names[i] for i in ii], "dest_pa": [pa_names[j] for j in jj],
                                            "observed_trips": Po[ii, jj], "modelled_trips": Pm[ii, jj], "geh": gh[ii, jj]})
    st = inp["bus_stop_tld_202607"]
    st = st[st.hour == pk]
    mids = np.where(st.km_to == "inf", st.km_from.astype(float) + 0.5,
                    0.5 * (st.km_from.astype(float) + pd.to_numeric(st.km_to, errors="coerce")))
    bus_summary["stop_to_stop_straight_line_mean_km_july"] = float((mids * st.weekday_trips_month_total).sum()
                                                                     / st.weekday_trips_month_total.sum())
    # what if the bus-calibrated deterrence function were used for commuting?
    Tt = G.gravity(O, D, d, "gamma", a_b, b_b)
    Mt = Rr @ Tt @ Cw
    bus_summary["transfer_to_commute"] = {"r2_cells": S.r_squared(Mt, N), "srmse_cells": S.srmse(Mt, N),
                                          "mean_km_model_zone_level": G.mean_cost(Tt, d)}
    summary["distribution_bus"] = bus_summary
    write_csv(out / "tld_bus.csv", pd.DataFrame(tld_rows, columns=["month", "km_from", "km_to", "observed_trips",
                                                                   "modelled_trips_gamma", "modelled_trips_exponential"]))
    write_csv(out / "bus_pa_pairs_202608.csv", pair_tables["202608"].sort_values("observed_trips", ascending=False))
    log(f"bus gravity a={a_b:.3f} b={b_b:.4f}")

    # ---- PT skims --------------------------------------------------------------------------------------------------
    g_pt0, g_rail0, g_bus0, info0, pos0 = M.pt_skims(inp, cfg, z, d, with_jrl=False)
    g_pt1, g_rail1, g_bus1, info1, pos1 = M.pt_skims(inp, cfg, z, d, with_jrl=True)
    summary["pt_network"] = {"stations_base": info0["stations"], "stations_with_jrl": info1["stations"],
                             "jrl_positions_from_osm": info1["positions_from_osm"],
                             "rail_faster_share_of_commuters_base": float((T * (g_rail0 < g_bus0)).sum() / T.sum())}
    log("pt skims")

    # ---- d. mode choice --------------------------------------------------------------------------------------------
    term = M.v(mcfg["mode_choice"]["car_terminal_min"])
    t_car = t_ff * M.v(mcfg["mode_choice"]["car_speed_factor"]) + term
    priv = z.private_share.values
    cen = z.central.values
    ind = M.industrial_share(inp, cfg, nz)
    res_rows, res_g, obs_res = residence_groups(inp, z)
    obs_work = workplace_mode_obs(inp, te)
    X0 = (t_car, g_pt0, d, priv, cen, ind)
    theta, ll_m, opt = L.calibrate(T, X0, obs_res, res_g, obs_work, te["zone_workplace"])
    n_obs = float(obs_res.sum() + obs_work.sum())
    P0 = L.probabilities(L.utilities(theta, *X0))
    S_res = L.group_shares(T, P0, res_g, len(res_rows), 0)
    S_work = L.group_shares(T, P0, te["zone_workplace"], len(te["workplaces"]), 1)
    obs_cells = cell_mode_obs(inp, te)
    mod_cells = np.einsum("gi,mij,jh->ghm", Rr, P0 * T[None], Cw)
    tot_cells = obs_cells.sum(2)
    sh_obs = obs_cells / np.maximum(tot_cells[..., None], 1)
    sh_mod = mod_cells / np.maximum(mod_cells.sum(2)[..., None], 1e-12)
    big = tot_cells >= 1000
    w_cells = tot_cells[big]
    share_res_obs = obs_res / obs_res.sum(1, keepdims=True)
    share_work_obs = obs_work / obs_work.sum(1, keepdims=True)
    tot_mod = (P0 * T[None]).sum(axis=(1, 2)) / T.sum()
    tot_obs = obs_res.sum(0) / obs_res.sum()
    summary["mode_choice"] = {
        "params": dict(zip(L.PARAMS, theta.tolist())), "log_likelihood": ll_m, "converged": bool(opt.success),
        "value_of_time_note": "b_time is per minute of (generalised) time",
        "share_model": dict(zip(L.MODES, tot_mod.tolist())), "share_census_residence": dict(zip(L.MODES, tot_obs.tolist())),
        "residence_mae_share_points": float(np.mean(np.abs(S_res - share_res_obs)) * 100),
        "workplace_mae_share_points": float(np.mean(np.abs(S_work - share_work_obs)) * 100),
        "residence_r2_car_share": S.r_squared(S_res[:, 0], share_res_obs[:, 0]),
        "workplace_r2_car_share": S.r_squared(S_work[:, 0], share_work_obs[:, 0]),
        "holdout_cells": int(big.sum()),
        "holdout_r2_car_share": S.r_squared(sh_mod[big][:, 0], sh_obs[big][:, 0]),
        "holdout_r2_pt_share": S.r_squared(sh_mod[big][:, 1], sh_obs[big][:, 1]),
        "holdout_weighted_mae_car_points": float(np.sum(w_cells * np.abs(sh_mod[big][:, 0] - sh_obs[big][:, 0])) / w_cells.sum() * 100),
        "holdout_weighted_mae_pt_points": float(np.sum(w_cells * np.abs(sh_mod[big][:, 1] - sh_obs[big][:, 1])) / w_cells.sum() * 100)}
    write_csv(out / "mode_shares_residence.csv", pd.DataFrame({
        "planning_area_of_residence": res_rows, "census_car": share_res_obs[:, 0], "model_car": S_res[:, 0],
        "census_pt": share_res_obs[:, 1], "model_pt": S_res[:, 1], "census_other": share_res_obs[:, 2],
        "model_other": S_res[:, 2], "census_commuters": obs_res.sum(1)}))
    write_csv(out / "mode_shares_workplace.csv", pd.DataFrame({
        "workplace": te["workplaces"], "census_car": share_work_obs[:, 0], "model_car": S_work[:, 0],
        "census_pt": share_work_obs[:, 1], "model_pt": S_work[:, 1], "census_other": share_work_obs[:, 2],
        "model_other": S_work[:, 2], "census_commuters": obs_work.sum(1)}))
    gi, hi = np.where(big)
    write_csv(out / "mode_shares_holdout_cells.csv", pd.DataFrame({
        "region_of_residence": [M.REGIONS[i] for i in gi], "workplace": [te["workplaces"][j] for j in hi],
        "census_commuters": tot_cells[gi, hi], "census_car": sh_obs[gi, hi, 0], "model_car": sh_mod[gi, hi, 0],
        "census_pt": sh_obs[gi, hi, 1], "model_pt": sh_mod[gi, hi, 1]}))
    log(f"mode choice {np.round(theta, 4).tolist()} converged={opt.success}")

    # ---- e. base assignment ------------------------------------------------------------------------------------------
    acfg = mcfg["assignment"]
    Q0 = car_demand(T, P0[0], cfg, phf)
    scen = {"base_2020": {"T": T, "P": P0, "Q": Q0}}

    # ---- g. 2030 demand ----------------------------------------------------------------------------------------------
    O_add, D_add, tinfo = tengah_2030(inp, cfg, z, te)
    O30 = O + O_add
    D30 = D + D_add
    D30 = D30 * (O30.sum() / D30.sum())
    T30 = G.gravity(O30, D30, d, "gamma", a_c, b_c)
    for name, gpt in (("dm_2030", g_pt0), ("ds_2030_jrl", g_pt1)):
        P = L.probabilities(L.utilities(theta, t_car, gpt, d, priv, cen, ind))
        scen[name] = {"T": T30, "P": P, "Q": car_demand(T30, P[0], cfg, phf)}
    dg = g_pt1 - g_pt0
    tz0 = (z.planning_area == "TENGAH").values
    zw0 = (z.region == WEST).values
    # profile of the log-likelihood in b_time, and what each value would do to the JRL result
    prof = []
    for bt in (-0.005, theta[2], -0.02, -0.03, -0.05):
        def ll_fixed(th7, bt=bt):
            th = np.insert(th7, 2, bt)
            return -L.log_likelihood(th, T, X0, obs_res, res_g, obs_work, te["zone_workplace"]) / n_obs
        from scipy.optimize import minimize as _min
        r_ = _min(ll_fixed, np.delete(theta, 2), method="BFGS", options={"gtol": 1e-7, "maxiter": 5000})
        th = np.insert(r_.x, 2, bt)
        P_dm = L.probabilities(L.utilities(th, t_car, g_pt0, d, priv, cen, ind))
        P_ds = L.probabilities(L.utilities(th, t_car, g_pt1, d, priv, cen, ind))
        zw1 = (z.region == WEST).values
        pt_dm = float((P_dm[1][zw1] * T30[zw1]).sum() / T30[zw1].sum())
        pt_ds = float((P_ds[1][zw1] * T30[zw1]).sum() / T30[zw1].sum())
        q_dm = float(car_demand(T30, P_dm[0], cfg, phf).sum())
        q_ds = float(car_demand(T30, P_ds[0], cfg, phf).sum())
        prof.append({"b_time": float(bt), "estimated": bool(bt == theta[2]), "log_likelihood": -float(r_.fun) * n_obs,
                     "west_pt_share_dm": pt_dm, "west_pt_share_ds": pt_ds,
                     "jrl_change_west_pt_share_points": (pt_ds - pt_dm) * 100,
                     "jrl_change_car_trips_per_hour": q_ds - q_dm})
    write_csv(out / "mode_choice_time_profile.csv", pd.DataFrame(prof))
    summary["scenario_2030"] = {
        "tengah": tinfo, "commuters_daily_2030": float(O30.sum()),
        "jrl_mean_pt_time_change_min_tengah_commuters": float((T30[tz0] * dg[tz0]).sum() / T30[tz0].sum()),
        "jrl_mean_pt_time_change_min_west_commuters": float((T30[zw0] * dg[zw0]).sum() / T30[zw0].sum()),
        "jrl_share_west_commuters_saving_5min_or_more": float((T30[zw0] * (dg[zw0] <= -5)).sum() / T30[zw0].sum())}

    results_flows = {}
    conv_rows = []
    zone_rows = {"zone": z.zone.values, "subzone": z.subzone.values, "planning_area": z.planning_area.values,
                 "region": z.region.values, "productions_2020": O, "attractions_2020": D,
                 "productions_2030": O30, "attractions_2030": D30}
    if assign_scenarios:
        for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
            r = assign(rm.net, rm.origins, rm.dests, scen[name]["Q"], method="bfw", rgap_target=M.v(acfg["rgap_target"]),
                       max_iter=M.v(acfg["max_iter"]))
            chk = equilibrium_gap(rm.net, r.flow, rm.origins, rm.dests, scen[name]["Q"])
            results_flows[name] = r.flow
            conv_rows += [[name, k + 1, g] for k, g in enumerate(r.history)]
            summary.setdefault("assignment", {})[name] = {
                "iterations": r.iterations, "relative_gap": r.relative_gap, "relative_gap_recomputed": chk["relative_gap"],
                "converged": r.converged, "car_trips_per_hour": float(scen[name]["Q"].sum()),
                "vehicle_hours": float(np.dot(r.flow[: rm.n_road_links], r.time[: rm.n_road_links])),
                "vehicle_km": float(np.dot(r.flow[: rm.n_road_links], rm.links.length_km.values)),
                "average_excess_cost_min": r.average_excess_cost * 60}
            log(f"assignment {name}: {r.iterations} iterations, gap {r.relative_gap:.2e}")
        write_csv(out / "assignment_convergence.csv", pd.DataFrame(conv_rows, columns=["scenario", "iteration",
                                                                                      "relative_gap"]))
    else:
        lf = pd.read_csv(out / "link_flows.csv")
        for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
            results_flows[name] = np.concatenate([lf[f"flow_{name}"].values,
                                                  np.zeros(rm.net.graph.n_links - rm.n_road_links)])

    # ---- link results, V/C, west --------------------------------------------------------------------------------------
    Ld = rm.links
    xy = node_xy
    mid = 0.5 * (xy[Ld.a.values - 1] + xy[Ld.b.values - 1])
    link_zone = zone_of_points(mid, geom)
    link_region = np.where(link_zone >= 0, z.region.values[np.clip(link_zone, 0, None)], "")
    lf = pd.DataFrame({"link": Ld.link.values, "highway": Ld.highway.values, "name": Ld.name.values,
                       "length_km": Ld.length_km.values, "lanes": Ld.lanes.values, "capacity": Ld.capacity.values,
                       "region": link_region})
    for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
        f = results_flows[name][: rm.n_road_links]
        lf[f"flow_{name}"] = f
        lf[f"vc_{name}"] = f / Ld.capacity.values
        tt = rm.net.time(results_flows[name])[: rm.n_road_links]
        lf[f"speed_kmh_{name}"] = Ld.length_km.values / np.maximum(tt, 1e-12)
    write_csv(out / "link_flows.csv", lf)
    base_vc = lf.vc_base_2020.values
    km = lf.length_km.values
    vc_bins = [0, 0.5, 0.85, 1.0, np.inf]
    vc_tab = {}
    for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
        vc = lf[f"vc_{name}"].values
        h, _ = np.histogram(vc, bins=vc_bins, weights=km)
        vc_tab[name] = (h / km.sum()).tolist()
    by_class = []
    for cls, g in lf.groupby("highway"):
        k = g.length_km.values
        by_class.append({"highway": cls, "km": float(k.sum()),
                         "mean_vc_km_weighted": float(np.sum(g.vc_base_2020 * k) / k.sum()),
                         "share_km_vc_over_0_85": float(k[g.vc_base_2020 > 0.85].sum() / k.sum()),
                         "share_km_vc_over_1": float(k[g.vc_base_2020 > 1.0].sum() / k.sum()),
                         "mean_speed_kmh_flow_weighted": float(np.sum(g.flow_base_2020 * g.length_km) /
                                                               max(np.sum(g.flow_base_2020 * g.length_km / g.speed_kmh_base_2020), 1e-9))})
    write_csv(out / "vc_by_class_base.csv", pd.DataFrame(by_class))
    west = lf.region.values == WEST
    dvc = lf.vc_ds_2030_jrl.values - lf.vc_dm_2030.values
    summary["road"] = {
        "vc_bins": ["0-0.5", "0.5-0.85", "0.85-1.0", ">1.0"], "share_km_by_vc_bin": vc_tab,
        "west_links": int(west.sum()), "west_km": float(km[west].sum()),
        "west_mean_vc_base": float(np.sum(base_vc[west] * km[west]) / km[west].sum()),
        "west_mean_vc_dm": float(np.sum(lf.vc_dm_2030.values[west] * km[west]) / km[west].sum()),
        "west_mean_vc_ds": float(np.sum(lf.vc_ds_2030_jrl.values[west] * km[west]) / km[west].sum()),
        "west_km_vc_over_0_85_base": float(km[west & (base_vc > 0.85)].sum()),
        "west_km_vc_over_0_85_dm": float(km[west & (lf.vc_dm_2030.values > 0.85)].sum()),
        "west_km_vc_over_0_85_ds": float(km[west & (lf.vc_ds_2030_jrl.values > 0.85)].sum()),
        "west_links_vc_down_by_0_05_ds_vs_dm": int((west & (dvc <= -0.05)).sum()),
        "west_links_vc_up_by_0_05_ds_vs_dm": int((west & (dvc >= 0.05)).sum())}
    # screenlines: consistency of assigned flows with the demand that must cross them
    zx = z.x.values
    sl_rows = []
    for nm, x0, ylo, yhi in (("x = 21 km (West | rest)", 21000.0, 25000.0, 50000.0),
                             ("x = 30 km (central)", 30000.0, 25000.0, 50000.0)):
        for name in ("base_2020", "ds_2030_jrl"):
            e, w_, n_links = screenline(rm, node_xy, results_flows[name], x0, ylo, yhi)
            Q = scen[name]["Q"]
            dem_e = float(Q[np.ix_(zx < x0, zx >= x0)].sum())
            dem_w = float(Q[np.ix_(zx >= x0, zx < x0)].sum())
            sl_rows.append([nm, name, n_links, e, dem_e, w_, dem_w])
    sl = pd.DataFrame(sl_rows, columns=["screenline", "scenario", "links_crossing", "assigned_eastbound",
                                        "demand_crossing_eastbound", "assigned_westbound", "demand_crossing_westbound"])
    write_csv(out / "screenlines.csv", sl)
    log("link results")

    # ---- g. scenario comparison: mode shares in the west ------------------------------------------------------------
    rows = []
    zw = (z.region == WEST).values
    for pa in sorted(z.planning_area[zw].unique()):
        m = (z.planning_area == pa).values
        r = {"planning_area": pa}
        for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
            Tm, P = scen[name]["T"], scen[name]["P"]
            tot = Tm[m].sum()
            for k, mode in enumerate(L.MODES):
                r[f"{mode}_{name}"] = (P[k][m] * Tm[m]).sum() / tot if tot > 0 else np.nan
            r[f"commuters_{name}"] = tot
        rows.append(r)
    ms = pd.DataFrame(rows)
    write_csv(out / "scenario_mode_share_west.csv", ms)
    sm = {}
    for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
        Tm, P = scen[name]["T"], scen[name]["P"]
        sm[name] = {"west_residents": {mode: float((P[k][zw] * Tm[zw]).sum() / Tm[zw].sum()) for k, mode in enumerate(L.MODES)},
                    "all": {mode: float((P[k] * Tm).sum() / Tm.sum()) for k, mode in enumerate(L.MODES)},
                    "car_trips_per_hour": float(scen[name]["Q"].sum())}
    tz = (z.planning_area == "TENGAH").values
    for name in ("dm_2030", "ds_2030_jrl"):
        Tm, P = scen[name]["T"], scen[name]["P"]
        sm[name]["tengah_residents"] = {mode: float((P[k][tz] * Tm[tz]).sum() / Tm[tz].sum()) for k, mode in enumerate(L.MODES)}
    summary["scenario_2030"]["mode_shares"] = sm
    zone_rows.update({f"car_share_{n}": np.divide((scen[n]["P"][0] * scen[n]["T"]).sum(1), scen[n]["T"].sum(1),
                                                  out=np.full(nz, np.nan), where=scen[n]["T"].sum(1) > 0)
                      for n in scen})
    write_csv(out / "zones_trip_ends.csv", pd.DataFrame(zone_rows))

    # ---- g. junction growth factors and worked example ----------------------------------------------------------------
    jres = junctions(rm, inp, cfg, lf, results_flows, link_region, out)
    summary["junctions"] = jres
    log("junctions")

    summary["runtime_s"] = None  # not recorded: it differs between machines
    write_json(out / "summary.json", summary)
    write_json(out / "inputs_used.json", {"model": cfg["model"], "rail_base_year_rule": cfg["rail"]["base_year_rule"],
                                          "rail_speeds": cfg["rail"]["speeds_kmh"]})
    np.savez_compressed(out / "demand_base_2020.npz", T=np.round(T, 6), Q=np.round(Q0, 6))
    log("done")
    return summary


def junctions(rm, inp, cfg, lf, flows, link_region, out: Path) -> dict:
    """Signalised junction clusters in the West Region: approach growth factors, and one worked example."""
    from scipy.spatial import cKDTree

    jc = cfg["model"]["junction"]
    nodes = inp["nodes"]
    xy = nodes[["x", "y"]].values
    sig = np.where(nodes.traffic_signals.values == 1)[0]
    tree = cKDTree(xy)
    a = rm.links.a.values - 1
    b = rm.links.b.values - 1
    motor = rm.links.highway.values == "motorway"   # expressway main carriageways are never signal approaches
    on_motor = np.zeros(len(nodes), dtype=bool)
    on_motor[a[motor]] = True
    on_motor[b[motor]] = True
    # cluster: signal nodes within 60 m of each other (single linkage), plus every node within 30 m of them
    parent = {i: i for i in sig}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    st = cKDTree(xy[sig])
    for i, j in st.query_pairs(60.0):
        ri, rj = find(sig[i]), find(sig[j])
        if ri != rj:
            parent[rj] = ri
    members = {}
    for i in sig:
        members.setdefault(find(i), set()).add(i)
    node_cluster = np.full(len(nodes), -1)
    for cid, (root, mem) in enumerate(sorted(members.items())):
        for i in mem:
            node_cluster[i] = cid
        for i in mem:
            for j in tree.query_ball_point(xy[i], 30.0):
                if node_cluster[j] < 0 and not on_motor[j]:
                    node_cluster[j] = cid
    ca, cb = node_cluster[a], node_cluster[b]
    approach = (cb >= 0) & (ca != cb) & ~motor
    exit_ = (ca >= 0) & (ca != cb) & ~motor
    nrl = rm.n_road_links
    names = rm.links.name.values
    rows = []
    for cid in np.unique(cb[approach]):
        ins = np.where(approach & (cb == cid))[0]
        if len(ins) < 3:
            continue
        reg = link_region[ins]
        if not np.any(reg == WEST):
            continue
        base = flows["base_2020"][ins]
        if base.sum() < 500:
            continue
        cx, cy = xy[node_cluster == cid].mean(axis=0)
        for k in ins:
            rows.append({"junction": int(cid), "x": round(float(cx), 1), "y": round(float(cy), 1), "approach_link": int(k + 1),
                         "road": names[k], "lanes": float(rm.links.lanes.values[k]),
                         "flow_base_2020": float(flows["base_2020"][k]), "flow_dm_2030": float(flows["dm_2030"][k]),
                         "flow_ds_2030_jrl": float(flows["ds_2030_jrl"][k])})
    gf = pd.DataFrame(rows)
    gf["gf_dm_vs_base"] = gf.flow_dm_2030 / gf.flow_base_2020.where(gf.flow_base_2020 > 0)
    gf["gf_ds_vs_base"] = gf.flow_ds_2030_jrl / gf.flow_base_2020.where(gf.flow_base_2020 > 0)
    gf["gf_ds_vs_dm"] = gf.flow_ds_2030_jrl / gf.flow_dm_2030.where(gf.flow_dm_2030 > 0)
    tot = gf.groupby("junction")[["flow_base_2020", "flow_dm_2030", "flow_ds_2030_jrl"]].sum()
    tot["gf_dm_vs_base"] = tot.flow_dm_2030 / tot.flow_base_2020
    tot["gf_ds_vs_base"] = tot.flow_ds_2030_jrl / tot.flow_base_2020
    gf = gf.merge(tot[["gf_dm_vs_base", "gf_ds_vs_base"]].rename(columns=lambda c: "junction_" + c),
                  left_on="junction", right_index=True)
    write_csv(out / "junction_growth_factors.csv", gf.sort_values(["junction", "approach_link"]))
    # worked example: the 3- or 4-arm junction (every arm >= 100 pcu/h in the base) with the largest growth in
    # entering flow, do-minimum 2030 against the base
    arms = gf.groupby("junction").size()
    minflow = gf.groupby("junction").flow_base_2020.min()
    cand = tot[arms.reindex(tot.index).between(3, 4) & (minflow.reindex(tot.index) >= 100)].copy()
    cand["increase"] = cand.flow_dm_2030 - cand.flow_base_2020
    jid = int(cand.increase.idxmax())
    ins = np.where(approach & (cb == jid))[0]
    outs = np.where(exit_ & (ca == jid))[0]
    bear_in = [J.bearing_deg(*xy[a[k]], *xy[b[k]]) for k in ins]
    bear_out = [J.bearing_deg(*xy[a[k]], *xy[b[k]]) for k in outs]
    seed = np.ones((len(ins), len(outs)))
    for i, bi in enumerate(bear_in):
        for j, bo in enumerate(bear_out):
            dd = abs((bi - bo + 180.0) % 360.0 - 180.0)
            if abs(dd - 180.0) < 30.0:   # leaving back the way it came: U-turn, banned in the seed
                seed[i, j] = 0.0
    ex = {"junction": jid, "approaches": [str(names[k]) for k in ins], "exits": [str(names[k]) for k in outs]}
    s_lane = M.v(jc["saturation_flow_pcu_per_lane"])
    lanes_in = rm.links.lanes.values[ins]
    checks = {}
    turn_tables = {}
    base_in = flows["base_2020"][ins]
    base_out = flows["base_2020"][outs]
    base_turns = J.furness_turns(seed, base_in, base_out)
    for name in ("base_2020", "dm_2030", "ds_2030_jrl"):
        q_in = flows[name][ins]
        gfac = np.divide(q_in, base_in, out=np.ones_like(q_in), where=base_in > 0)
        # how growth factors feed a junction model: grow the (here modelled, normally surveyed) base turning
        # flows by the approach growth factors, then balance to the forecast exit flows
        grown = base_turns * gfac[:, None]
        turns = J.furness_turns(np.where(grown > 0, grown, 0.0), q_in, flows[name][outs])
        turn_tables[name] = turns
        keep = q_in >= M.v(jc["min_approach_flow"])
        chk = J.signal_check(q_in[keep], s_lane * lanes_in[keep], np.array(bear_in)[keep],
                             M.v(jc["lost_time_per_phase_s"]), M.v(jc["cycle_min_s"]), M.v(jc["cycle_max_s"]))
        checks[name] = {"approach_flow": q_in.tolist(), "growth_factor": gfac.tolist(), "Y": chk["Y"],
                        "cycle_s": chk["cycle_s"], "max_X": float(np.max(chk["X"])),
                        "approaches_over_practical_X": int(np.sum(chk["X"] > M.v(jc["practical_x"]))),
                        "X": chk["X"].tolist(), "delay_s": chk["delay_s"].tolist(), "phases": chk["phases"]}
    ex["checks"] = checks
    ex["xy"] = [float(v) for v in xy[node_cluster == jid].mean(axis=0)]
    rows = []
    for name, tt in turn_tables.items():
        for i in range(len(ins)):
            for j in range(len(outs)):
                if tt[i, j] > 0:
                    rows.append([name, str(names[ins[i]]), int(ins[i] + 1), str(names[outs[j]]), int(outs[j] + 1), tt[i, j]])
    write_csv(out / "junction_example_turns.csv", pd.DataFrame(rows, columns=["scenario", "from_road", "from_link",
                                                                              "to_road", "to_link", "pcu_per_hour"]))
    return {"junctions_in_west": int(gf.junction.nunique()), "approaches": int(len(gf)),
            "median_junction_gf_dm_vs_base": float(tot.gf_dm_vs_base.median()),
            "max_junction_gf_dm_vs_base": float(tot.gf_dm_vs_base.max()),
            "example": ex}
