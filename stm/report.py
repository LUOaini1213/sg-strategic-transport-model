"""Fill docs/*.template.md with numbers from results/ and config/.

Placeholders look like {{name}}. A placeholder without a value is an error, so a number cannot be typed into the
README by hand and silently go stale; tests/test_report.py regenerates both documents and compares them with the
committed files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"
DOCS = REPO / "docs"
TARGETS = {"README.template.md": REPO / "README.md", "validation_report.template.md": DOCS / "validation_report.md"}


def i(v) -> str:
    return f"{float(v):,.0f}"


def f(v, nd=2) -> str:
    return f"{float(v):,.{nd}f}"


def pct(v, nd=1) -> str:
    return f"{100 * float(v):.{nd}f}%"


def pts(v, nd=1) -> str:
    """Percentage points with sign."""
    return f"{float(v) * 100:+.{nd}f}"


def g(v, nd=3) -> str:
    return f"{float(v):.{nd}g}"


def table(header, rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _label_rows(cfg: dict, prefix: str = ""):
    rows = []
    for k, v in cfg.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and "label" in v:
            val = v.get("value", "")
            if isinstance(val, dict):
                val = "; ".join(f"{a}: {b}" for a, b in val.items())
            elif isinstance(val, list):
                val = ", ".join(str(x) for x in val)
            rows.append([f"`{prefix}{k}`", str(val).replace("|", "/"), v["label"],
                         v.get("note", "").replace("|", "/")])
        elif isinstance(v, dict):
            rows += _label_rows(v, prefix=f"{prefix}{k}.")
    return rows


def context() -> dict:
    s = json.loads((RES / "summary.json").read_text(encoding="utf-8"))
    sf = json.loads((RES / "sioux_falls_check.json").read_text(encoding="utf-8"))
    cfg = json.loads((REPO / "config" / "model.json").read_text(encoding="utf-8"))
    mut_p = RES / "mutation_report.json"
    mut = json.loads(mut_p.read_text(encoding="utf-8")) if mut_p.exists() else None
    c = {}
    z, gen, net = s["zones"], s["generation"], s["network"]
    c.update(n_zones=i(z["n"]), zones_with_residents=i(z["with_residents"]), n_pa=i(z["planning_areas"]),
             commuters=i(gen["commuters_daily"]), census_employed=i(gen["census_employed_residents"]),
             commuter_share=pct(gen["commuters_daily"] / gen["census_employed_residents"]),
             attendance=g(gen["attendance_factor"]), phf=pct(gen["peak_hour_share"]),
             peak_trips=i(gen["am_peak_hour_trips"]), zones_p=i(gen["zones_with_productions"]),
             zones_a=i(gen["zones_with_attractions"]),
             road_nodes=i(net["road_nodes"]), road_links=i(net["road_links"]), connectors=i(net["connectors"]),
             road_km=i(net["road_km_directed"]), lanes_tag=pct(net["lanes_from_tag_share"], 0),
             speed_tag=pct(net["speed_from_tag_share"], 0))
    dc = s["distribution_commute"]
    c.update(dc_a=f(dc["a"], 3), dc_b=f(dc["b_per_km"], 4), dc_r2=f(dc["r2_cells"], 3), dc_srmse=f(dc["srmse_cells"], 3),
             dc_cells=i(dc["cells"]), dc_mean=f(dc["mean_km_model_zone_level"], 1),
             dc_cell_census=f(dc["mean_km_cell_level_census"], 2), dc_cell_model=f(dc["mean_km_cell_level_model"], 2),
             dc_cr=f(dc["coincidence_ratio_cell_level"], 3), dc_intra=pct(dc["intrazonal_share_model"]))
    b = s["distribution_bus"]
    cal, val, tr = b["calibration"], b["validation"], b["transfer_to_commute"]
    c.update(bus_a=f(b["a"], 3), bus_b=f(b["b_per_km"], 3), bus_bexp=f(b["exponential_b_per_km"], 3),
             bus_hour=b["am_peak_hour"], bus_stop_mean=f(b["stop_to_stop_straight_line_mean_km_july"], 1),
             tr_r2=f(tr["r2_cells"], 3), tr_srmse=f(tr["srmse_cells"], 3), tr_mean=f(tr["mean_km_model_zone_level"], 1),
             tr_mean_drop=pct(1 - tr["mean_km_model_zone_level"] / dc["mean_km_model_zone_level"], 0))
    for key, d in (("cal", cal), ("val", val)):
        c.update({f"{key}_trips": i(d["trips_per_hour"]), f"{key}_mean_obs": f(d["mean_km_observed"], 2),
                  f"{key}_mean_mod": f(d["mean_km_model"], 2), f"{key}_mean_exp": f(d["mean_km_model_exponential"], 2),
                  f"{key}_cr": f(d["coincidence_ratio"], 3), f"{key}_cr_exp": f(d["coincidence_ratio_exponential"], 3),
                  f"{key}_intra_obs": pct(d["intrazonal_share_observed"]), f"{key}_intra_mod": pct(d["intrazonal_share_model"]),
                  f"{key}_r2z": f(d["r2_zone_pairs"], 3), f"{key}_pairs": i(d["pa_pairs"]),
                  f"{key}_geh5": pct(d["geh_lt5_share_pa_pairs"], 0), f"{key}_geh10": pct(d["geh_lt10_share_pa_pairs"], 0),
                  f"{key}_r2pa": f(d["r2_pa_pairs"], 3), f"{key}_r2pa_inter": f(d["r2_pa_pairs_excluding_intra_pa"], 3),
                  f"{key}_geh5_100": pct(d["geh_lt5_share_pa_pairs_over_100"], 0), f"{key}_pairs_100": i(d["pa_pairs_over_100"])})
    pt = s["pt_network"]
    c.update(st_base=i(pt["stations_base"]), st_jrl=i(pt["stations_with_jrl"]),
             rail_faster=pct(pt["rail_faster_share_of_commuters_base"], 0),
             jrl_osm=i(len(pt["jrl_positions_from_osm"])))
    m = s["mode_choice"]
    p = m["params"]
    c.update({f"mc_{k}": f(v, 4 if abs(v) < 0.1 else 3) for k, v in p.items()})
    c.update(mc_conv="yes" if m["converged"] else "NO", mc_car_mod=pct(m["share_model"]["car"]),
             mc_car_obs=pct(m["share_census_residence"]["car"]), mc_pt_mod=pct(m["share_model"]["pt"]),
             mc_pt_obs=pct(m["share_census_residence"]["pt"]), mc_oth_mod=pct(m["share_model"]["other"]),
             mc_oth_obs=pct(m["share_census_residence"]["other"]),
             mc_res_mae=f(m["residence_mae_share_points"], 1), mc_work_mae=f(m["workplace_mae_share_points"], 1),
             mc_res_r2=f(m["residence_r2_car_share"], 2), mc_work_r2=f(m["workplace_r2_car_share"], 2),
             mc_hold_n=i(m["holdout_cells"]), mc_hold_r2car=f(m["holdout_r2_car_share"], 2),
             mc_hold_r2pt=f(m["holdout_r2_pt_share"], 2), mc_hold_maecar=f(m["holdout_weighted_mae_car_points"], 1),
             mc_hold_maept=f(m["holdout_weighted_mae_pt_points"], 1))
    prof = pd.read_csv(RES / "mode_choice_time_profile.csv")
    best = prof[prof.estimated].iloc[0]
    c["profile_table"] = table(
        ["b_time (per min)", "", "log-likelihood minus maximum", "West residents' PT share, 2030 without JRL",
         "with JRL", "JRL effect (points)", "JRL effect on car trips/h"],
        [[f(r.b_time, 4), "estimated" if r.estimated else "fixed", i(r.log_likelihood - best.log_likelihood),
          pct(r.west_pt_share_dm), pct(r.west_pt_share_ds), f(r.jrl_change_west_pt_share_points, 2),
          i(r.jrl_change_car_trips_per_hour)] for r in prof.itertuples()])
    c["jrl_pts_lo"] = f(prof.jrl_change_west_pt_share_points.min(), 2)
    c["jrl_pts_hi"] = f(prof.jrl_change_west_pt_share_points.max(), 2)
    c["jrl_pts_est"] = f(best.jrl_change_west_pt_share_points, 2)
    c["ll_drop_003"] = i(best.log_likelihood - prof[prof.b_time.round(4) == -0.03].log_likelihood.iloc[0])
    a = s["assignment"]
    for k, short in (("base_2020", "base"), ("dm_2030", "dm"), ("ds_2030_jrl", "ds")):
        c.update({f"as_{short}_it": i(a[k]["iterations"]), f"as_{short}_gap": f"{a[k]['relative_gap']:.1e}",
                  f"as_{short}_gap2": f"{a[k]['relative_gap_recomputed']:.1e}", f"as_{short}_q": i(a[k]["car_trips_per_hour"]),
                  f"as_{short}_vht": i(a[k]["vehicle_hours"]), f"as_{short}_vkt": i(a[k]["vehicle_km"])})
    r = s["road"]
    vb = r["share_km_by_vc_bin"]
    c["vc_table"] = table(["Scenario"] + [f"V/C {x}" for x in r["vc_bins"]],
                          [[n.replace("_", " ")] + [pct(x) for x in vb[n]] for n in ("base_2020", "dm_2030", "ds_2030_jrl")])
    c.update(vc_over085_base=pct(vb["base_2020"][2] + vb["base_2020"][3]), vc_over1_base=pct(vb["base_2020"][3]),
             west_km=i(r["west_km"]), west_vc_base=f(r["west_mean_vc_base"], 3), west_vc_dm=f(r["west_mean_vc_dm"], 3),
             west_vc_ds=f(r["west_mean_vc_ds"], 3), west_085_base=f(r["west_km_vc_over_0_85_base"], 1),
             west_085_dm=f(r["west_km_vc_over_0_85_dm"], 1), west_085_ds=f(r["west_km_vc_over_0_85_ds"], 1),
             west_down=i(r["west_links_vc_down_by_0_05_ds_vs_dm"]), west_up=i(r["west_links_vc_up_by_0_05_ds_vs_dm"]))
    vc = pd.read_csv(RES / "vc_by_class_base.csv")
    order = ["motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
             "secondary_link", "tertiary_link"]
    vc = vc.set_index("highway").loc[[o for o in order if o in set(vc.highway)]]
    c["vc_class_table"] = table(["OSM class", "km (directed)", "mean V/C (km-weighted)", "km with V/C > 0.85",
                                 "km with V/C > 1.0", "mean speed (km/h, flow-weighted)"],
                                [[k, i(v.km), f(v.mean_vc_km_weighted, 2), pct(v.share_km_vc_over_0_85),
                                  pct(v.share_km_vc_over_1), f(v.mean_speed_kmh_flow_weighted, 0)] for k, v in vc.iterrows()])
    mw_speed = vc.loc["motorway", "mean_speed_kmh_flow_weighted"] if "motorway" in vc.index else float("nan")
    c["motorway_speed"] = f(mw_speed, 0)
    c["primary_speed"] = f(vc.loc["primary", "mean_speed_kmh_flow_weighted"], 0)
    sl = pd.read_csv(RES / "screenlines.csv")
    c["screenline_table"] = table(["Screenline", "Scenario", "links", "assigned eastbound", "OD demand crossing eastbound",
                                   "assigned westbound", "OD demand crossing westbound"],
                                  [[x.screenline, x.scenario.replace("_", " "), x.links_crossing, i(x.assigned_eastbound),
                                    i(x.demand_crossing_eastbound), i(x.assigned_westbound), i(x.demand_crossing_westbound)]
                                   for x in sl.itertuples()])
    sc = s["scenario_2030"]
    t = sc["tengah"]
    ms = sc["mode_shares"]
    c.update(tg_homes=i(t["homes"]), tg_pop=i(t["population"]), tg_comm=i(t["commuters"]), tg_jobs=i(t["tengah_jobs_attracted"]),
             tg_per_res=f(t["commuters_per_resident_west"], 3), comm_2030=i(sc["commuters_daily_2030"]),
             jrl_dt_tengah=f(sc["jrl_mean_pt_time_change_min_tengah_commuters"], 1),
             jrl_dt_west=f(sc["jrl_mean_pt_time_change_min_west_commuters"], 1),
             jrl_save5=pct(sc["jrl_share_west_commuters_saving_5min_or_more"], 0))
    for n, short in (("base_2020", "base"), ("dm_2030", "dm"), ("ds_2030_jrl", "ds")):
        for grp in ("all", "west_residents"):
            for mode in ("car", "pt", "other"):
                c[f"ms_{short}_{grp}_{mode}"] = pct(ms[n][grp][mode])
        c[f"ms_{short}_q"] = i(ms[n]["car_trips_per_hour"])
    for n, short in (("dm_2030", "dm"), ("ds_2030_jrl", "ds")):
        for mode in ("car", "pt", "other"):
            c[f"ms_{short}_tengah_{mode}"] = pct(ms[n]["tengah_residents"][mode])
    c["jrl_west_pt_pts"] = pts(ms["ds_2030_jrl"]["west_residents"]["pt"] - ms["dm_2030"]["west_residents"]["pt"], 2)
    c["jrl_west_car_pts"] = pts(ms["ds_2030_jrl"]["west_residents"]["car"] - ms["dm_2030"]["west_residents"]["car"], 2)
    c["jrl_tengah_pt_pts"] = pts(ms["ds_2030_jrl"]["tengah_residents"]["pt"] - ms["dm_2030"]["tengah_residents"]["pt"], 2)
    c["jrl_car_trips"] = i(ms["ds_2030_jrl"]["car_trips_per_hour"] - ms["dm_2030"]["car_trips_per_hour"])
    c["tengah_car_trips"] = i(ms["dm_2030"]["car_trips_per_hour"] - ms["base_2020"]["car_trips_per_hour"])
    wm = pd.read_csv(RES / "scenario_mode_share_west.csv")
    wm = wm[wm.commuters_ds_2030_jrl > 0].sort_values("commuters_ds_2030_jrl", ascending=False)
    c["west_mode_table"] = table(["Planning area (West Region)", "commuters 2030", "PT 2020", "PT 2030 without JRL",
                                  "PT 2030 with JRL", "change with JRL (points)"],
                                 [[x.planning_area.title(), i(x.commuters_ds_2030_jrl),
                                   pct(x.pt_base_2020) if x.commuters_base_2020 > 0 else "-", pct(x.pt_dm_2030),
                                   pct(x.pt_ds_2030_jrl), pts(x.pt_ds_2030_jrl - x.pt_dm_2030, 2)] for x in wm.itertuples()])
    j = s["junctions"]
    ex = j["example"]
    chk = ex["checks"]
    c.update(jn=i(j["junctions_in_west"]), jappr=i(j["approaches"]), jgf_med=f(j["median_junction_gf_dm_vs_base"], 3),
             jgf_max=f(j["max_junction_gf_dm_vs_base"], 2))
    names = [x if x else "(unnamed link)" for x in ex["approaches"]]
    c["junction_name"] = " / ".join(sorted({x for x in ex["approaches"] if x}))
    c["junction_xy"] = f"{ex['xy'][0]:,.0f} E, {ex['xy'][1]:,.0f} N (SVY21)"
    rows = []
    for k, nm in enumerate(names):
        rows.append([nm, i(chk["base_2020"]["approach_flow"][k]), i(chk["dm_2030"]["approach_flow"][k]),
                     f(chk["dm_2030"]["growth_factor"][k], 3), i(chk["ds_2030_jrl"]["approach_flow"][k]),
                     f(chk["ds_2030_jrl"]["growth_factor"][k], 3)])
    c["junction_table"] = table(["Approach", "2020 base (pcu/h)", "2030 without JRL", "growth factor",
                                 "2030 with JRL", "growth factor"], rows)
    c["junction_check_table"] = table(
        ["", "Y (sum of critical ratios)", "cycle (s)", "highest degree of saturation X", "approaches over X = 0.9"],
        [[n.replace("_", " "), f(chk[n]["Y"], 3), f(chk[n]["cycle_s"], 0), f(chk[n]["max_X"], 3),
          i(chk[n]["approaches_over_practical_X"])] for n in ("base_2020", "dm_2030", "ds_2030_jrl")])
    c.update(sf_obj=f(sf["published_objective_1e5"], 8), sf_obj_pub=f(sf["published_flows_objective_1e5"], 8),
             sf_gap_pub=f"{sf['published_flows_relative_gap']:.1e}",
             sf_bfw6_it=i(sf["bfw_1e-06"]["iterations"]), sf_bfw6_gap=f"{sf['bfw_1e-06']['relative_gap']:.1e}",
             sf_bfw6_obj=f(sf["bfw_1e-06"]["objective_1e5"], 6), sf_bfw6_rel=f"{sf['bfw_1e-06']['objective_rel_diff']:.1e}",
             sf_bfw6_maxrel=pct(sf["bfw_1e-06"]["max_rel_flow_diff"], 2), sf_bfw6_maxabs=f(sf["bfw_1e-06"]["max_abs_flow_diff"], 1),
             sf_bfw4_it=i(sf["bfw_1e-04"]["iterations"]), sf_fw4_it=i(sf["fw_1e-04"]["iterations"]),
             sf_bfw4_maxrel=pct(sf["bfw_1e-04"]["max_rel_flow_diff"], 2), sf_fw4_maxrel=pct(sf["fw_1e-04"]["max_rel_flow_diff"], 2),
             sf_tstt=i(sf["published_tstt"]), sf_bfw6_tstt=i(sf["bfw_1e-06"]["tstt"]))
    if mut:
        c.update(mut_killed=i(mut["killed"]), mut_total=i(mut["total"]), mut_killed_ns=i(mut["killed_without_snapshot"]),
                 tests=i(mut["tests_collected"]))
        c["mutation_table"] = table(["Mutant", "File", "Deliberate bug", "Result (full suite)", "Without snapshot tests"],
                                    [[m_["id"], f"`{m_['file']}`", m_["what"], "killed" if m_["killed"] else "SURVIVED",
                                      "killed" if m_["killed_without_snapshot"] else "survived"]
                                     for m_ in mut["mutants"]])
        c["mutation_survivors"] = ("none" if mut["killed"] == mut["total"] else
                                   "; ".join(f"{m_['id']}: {m_.get('equivalent', 'not explained')}"
                                             for m_ in mut["mutants"] if not m_["killed"]))
    else:
        c.update(mut_killed="(not run)", mut_total="(not run)", mut_killed_ns="(not run)", tests="(not counted)",
                 mutation_table="(mutation testing not run yet)", mutation_survivors="(not run)")
    mc, pc, ac, sc_, jc = cfg["mode_choice"], cfg["pt"], cfg["assignment"], cfg["scenario_2030"], cfg["junction"]
    c.update(cfg_persons=g(sc_["persons_per_home"]["value"]), cfg_terminal=g(mc["car_terminal_min"]["value"]),
             cfg_walk_w=f(pc["walk_weight"]["value"], 1), cfg_wait_w=f(pc["wait_weight"]["value"], 1),
             cfg_occ=g(ac["car_occupancy"]["value"]), cfg_bg=g(ac["background_factor"]["value"]),
             cfg_alpha=g(ac["bpr_alpha"]["value"]), cfg_beta=g(ac["bpr_beta"]["value"]),
             cfg_sat=i(jc["saturation_flow_pcu_per_lane"]["value"]), cfg_lost=g(jc["lost_time_per_phase_s"]["value"]),
             cfg_conn=i(ac["connectors_per_zone"]["value"]), cfg_rgap=f"{ac['rgap_target']['value']:.0e}",
             jrl_n=i(pt["stations_with_jrl"] - pt["stations_base"]))
    c["assumption_table"] = table(["Parameter (config/model.json)", "Value", "Status", "Note / source"],
                                  _label_rows(cfg))
    return c


def fill(template: str, ctx: dict) -> str:
    missing = sorted(set(re.findall(r"{{(\w+)}}", template)) - set(ctx))
    if missing:
        raise KeyError(f"placeholders without a value: {missing}")
    return re.sub(r"{{(\w+)}}", lambda m: ctx[m.group(1)], template)


def render_all() -> dict:
    ctx = context()
    return {dst: fill((DOCS / src).read_text(encoding="utf-8"), ctx) for src, dst in TARGETS.items()}


def write_all() -> None:
    for dst, text in render_all().items():
        dst.write_text(text, encoding="utf-8", newline="\n")
