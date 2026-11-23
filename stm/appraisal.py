"""Economic appraisal of a scenario pair (do-minimum against do-something) from the model's own matrices.

User benefits follow the rule of a half, mode by mode and origin-destination pair by pair:

    benefit_ij = 1/2 (T0_ij + T1_ij) (c0_ij - c1_ij)

with T the trips and c the perceived cost without (0) and with (1) the scheme. For public transport c is the
generalised time of the mode-choice model; for cars it is the travel time on the equilibrium network. Costs that
car users do not perceive (non-fuel operating costs) and tailpipe CO2 are added as the net change in
vehicle-kilometres times a unit value. Fuel is left out: the model has no relation between speed and fuel use,
and the distance of "the" quickest path between two zones is not defined at equilibrium, where several paths
tie. Annual benefits are discounted to a base year over an appraisal period and
compared with scheme costs.

The unit values and their sources are in config/appraisal.json. The scheme costs there are ILLUSTRATIVE, so the
benefit-cost ratio is illustrative too; the present value of benefits is not.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .paths import skim

REPO = Path(__file__).resolve().parents[1]


def load_config(repo: Path = REPO) -> dict:
    return json.loads((repo / "config" / "appraisal.json").read_text(encoding="utf-8"))


def v(entry):
    return entry["value"]


# ---------------------------------------------------------------------------------------------------------------
# user benefits
# ---------------------------------------------------------------------------------------------------------------
def rule_of_half(T0, T1, c0, c1) -> np.ndarray:
    """Change in consumer surplus per cell: existing users gain the full cost change, new or lost users half."""
    T0, T1, c0, c1 = (np.asarray(x, dtype=float) for x in (T0, T1, c0, c1))
    return 0.5 * (T0 + T1) * (c0 - c1)


def existing_user_benefit(T0, c0, c1) -> np.ndarray:
    """The part of the rule of a half that goes to trips already made without the scheme."""
    return np.asarray(T0, dtype=float) * (np.asarray(c0, dtype=float) - np.asarray(c1, dtype=float))


def logsum(V: np.ndarray) -> np.ndarray:
    """log of the sum over modes (first axis) of exp(V): the expected maximum utility of a logit choice."""
    V = np.asarray(V, dtype=float)
    m = V.max(axis=0)
    return m + np.log(np.exp(V - m[None]).sum(axis=0))


def logsum_benefit(T, V0, V1, cost_coefficient: float) -> np.ndarray:
    """Exact consumer-surplus change of a logit model, in the units of the cost variable:
    T (logsum1 - logsum0) / (-coefficient), the coefficient of cost being negative."""
    if cost_coefficient >= 0:
        raise ValueError("the cost coefficient must be negative")
    return np.asarray(T, dtype=float) * (logsum(V1) - logsum(V0)) / (-cost_coefficient)


# ---------------------------------------------------------------------------------------------------------------
# discounting
# ---------------------------------------------------------------------------------------------------------------
def annual_rate(year_from_base: int, schedule) -> float:
    """Discount rate that applies in a year counted from the base year (year 1 is the first year after it).
    ``schedule`` is a list of [last year, rate]; the last rate also applies beyond the last limit."""
    for last, rate in schedule:
        if year_from_base <= last:
            return float(rate)
    return float(schedule[-1][1])


def discount_factors(n_years: int, schedule) -> np.ndarray:
    """Factors for years 0..n_years from the base year: factor[0] = 1, factor[k] = factor[k-1] / (1 + r_k)."""
    f = np.ones(n_years + 1)
    for k in range(1, n_years + 1):
        f[k] = f[k - 1] / (1.0 + annual_rate(k, schedule))
    return f


def benefit_stream(annual: float, first_year: int, n_years: int, growth: float = 0.0) -> np.ndarray:
    """Annual values by year from the base year: zero before ``first_year``, then ``annual`` growing at
    ``growth`` a year for ``n_years`` years."""
    s = np.zeros(first_year + n_years)
    s[first_year:] = annual * (1.0 + growth) ** np.arange(n_years)
    return s


def present_value(stream, schedule) -> float:
    stream = np.asarray(stream, dtype=float)
    return float(np.dot(stream, discount_factors(len(stream) - 1, schedule)))


def npv(pvb: float, pvc: float) -> float:
    return pvb - pvc


def bcr(pvb: float, pvc: float) -> float:
    return pvb / pvc if pvc > 0 else float("nan")


def switching_value(base_value: float, pv_part_linear: float, pv_other: float, pvc: float) -> float:
    """Value of a parameter at which benefits equal costs, when ``pv_part_linear`` (computed at ``base_value``)
    is proportional to the parameter and ``pv_other`` does not depend on it."""
    if pv_part_linear <= 0:
        return float("nan")
    return base_value * (pvc - pv_other) / pv_part_linear


# ---------------------------------------------------------------------------------------------------------------
# the appraisal
# ---------------------------------------------------------------------------------------------------------------
def road_times(rm, flow: np.ndarray) -> np.ndarray:
    """Car time (hours) between zones along the quickest paths at the given link flows."""
    th, _ = skim(rm.net.graph, rm.net.time(flow), rm.origins, rm.dests)
    return th


def annual_components(day: dict, ac: dict, occupancy: float, vot: float | None = None, days: float | None = None,
                      peak_hours: float | None = None) -> dict:
    """Annual benefits in S$ by component from daily (public transport) and peak-hour (road) quantities."""
    val, ann = ac["values"], ac["annualisation"]
    vot = v(val["value_of_time_sgd_per_hour"]) if vot is None else vot
    days = v(ann["working_days_per_year"]) if days is None else days
    peak_hours = v(ann["road_peak_hours_per_day"]) if peak_hours is None else peak_hours
    road = peak_hours * days
    return {
        "pt_user_time": day["pt_person_hours_per_day_one_way"] * v(ann["return_trip_factor"]) * days * vot,
        "car_user_time": day["car_vehicle_hours_per_peak_hour"] * occupancy * road * vot,
        "car_non_fuel_operating": -day["vehicle_km_change_per_peak_hour"] * v(val["non_fuel_cost_sgd_per_km"]) * road,
        "co2": (-day["vehicle_km_change_per_peak_hour"] * v(val["co2_kg_per_vehicle_km"]) / 1000.0
                * v(val["carbon_price_sgd_per_tonne"]) * road)}


def evaluate(annual_total: float, ac: dict, schedule=None, years: int | None = None, growth: float | None = None,
             capital: float | None = None, operating: float | None = None) -> dict:
    """Present values (S$), net present value and benefit-cost ratio for a constant annual benefit."""
    sch = ac["scheme"]
    schedule = v(ac["discounting"]["schedule"]) if schedule is None else schedule
    years = v(sch["appraisal_years"]) if years is None else years
    growth = v(sch["benefit_growth_per_year"]) if growth is None else growth
    capital = v(ac["costs"]["capital_cost_pv_sgd_million"]) * 1e6 if capital is None else capital
    operating = v(ac["costs"]["operating_cost_sgd_million_per_year"]) * 1e6 if operating is None else operating
    first = v(sch["opening_year"]) - v(sch["base_year"])
    pvb = present_value(benefit_stream(annual_total, first, years, growth), schedule)
    pv_op = present_value(benefit_stream(operating, first, years, 0.0), schedule)
    pvc = capital + pv_op
    return {"pvb": pvb, "pv_operating": pv_op, "pvc": pvc, "npv": npv(pvb, pvc), "bcr": bcr(pvb, pvc),
            "pv_per_annual_unit": present_value(benefit_stream(1.0, first, years, growth), schedule)}


def run(out: Path, *, z: pd.DataFrame, T_do_min: np.ndarray, T_2020: np.ndarray, P0: np.ndarray, P1: np.ndarray,
        V0: np.ndarray, V1: np.ndarray, b_time: float, g_pt0: np.ndarray, g_pt1: np.ndarray, Q0: np.ndarray,
        Q1: np.ndarray, flow0: np.ndarray, flow1: np.ndarray, rm, attendance: float, occupancy: float,
        write_json, write_csv, ac: dict | None = None) -> dict:
    """Appraise do-something (1) against do-minimum (0). T are daily commuters, P mode probabilities
    (car, pt, other), V the mode utilities, g_pt generalised public-transport minutes, Q car trips per peak hour,
    flow the equilibrium link flows."""
    ac = load_config() if ac is None else ac
    val = ac["values"]
    nz = len(z)
    nrl = rm.n_road_links

    # ---- public transport: persons per day, one way -------------------------------------------------------------
    N0 = T_do_min * attendance * P0[1]
    N1 = T_do_min * attendance * P1[1]
    pt_min = rule_of_half(N0, N1, g_pt0, g_pt1)
    pt_existing = existing_user_benefit(N0, g_pt0, g_pt1)
    ls_min = logsum_benefit(T_do_min * attendance, V0, V1, b_time)
    # ---- road: vehicles per peak hour ------------------------------------------------------------------------------
    car_h = rule_of_half(Q0, Q1, road_times(rm, flow0), road_times(rm, flow1))
    km = rm.links.length_km.values
    vkm0, vkm1 = float(np.dot(flow0[:nrl], km)), float(np.dot(flow1[:nrl], km))
    vh0 = float(np.dot(flow0[:nrl], rm.net.time(flow0)[:nrl]))
    vh1 = float(np.dot(flow1[:nrl], rm.net.time(flow1)[:nrl]))
    day = {"pt_person_hours_per_day_one_way": float(pt_min.sum() / 60.0),
           "car_vehicle_hours_per_peak_hour": float(car_h.sum()),
           "vehicle_km_change_per_peak_hour": vkm1 - vkm0}
    comp = annual_components(day, ac, occupancy)
    annual = float(sum(comp.values()))
    core = evaluate(annual, ac)
    time_annual = comp["pt_user_time"] + comp["car_user_time"]
    f = core["pv_per_annual_unit"]

    # ---- who gains: by planning area of residence -----------------------------------------------------------------
    ann, vot = ac["annualisation"], v(val["value_of_time_sgd_per_hour"])
    days = v(ann["working_days_per_year"])
    road = v(ann["road_peak_hours_per_day"]) * days
    zone_pt = pt_min.sum(axis=1) / 60.0 * v(ann["return_trip_factor"]) * days * vot
    zone_car = car_h.sum(axis=1) * occupancy * vot * road
    commuters = T_do_min.sum(axis=1)
    by_zone = pd.DataFrame({"planning_area": z.planning_area.values, "region": z.region.values, "commuters": commuters,
                            "pt_user_benefit": zone_pt, "road_user_benefit": zone_car})
    pa = by_zone.groupby(["planning_area", "region"], as_index=False).sum(numeric_only=True)
    pa["user_benefit"] = pa.pt_user_benefit + pa.road_user_benefit
    attributed = float(pa.user_benefit.sum())
    pa["share_of_user_benefit"] = pa.user_benefit / attributed
    pa["share_of_commuters"] = pa.commuters / pa.commuters.sum()
    pa["benefit_per_commuter"] = np.where(pa.commuters > 0, pa.user_benefit / pa.commuters.clip(lower=1e-9), 0.0)
    pa = pa[pa.commuters > 0].sort_values(["user_benefit", "planning_area"], ascending=[False, True], kind="mergesort")
    write_csv(out / "appraisal_benefits_by_planning_area.csv", pa.rename(columns={
        "commuters": "commuters_daily_2030", "pt_user_benefit": "pt_user_benefit_sgd_per_year",
        "road_user_benefit": "road_user_benefit_sgd_per_year", "user_benefit": "user_benefit_sgd_per_year",
        "benefit_per_commuter": "user_benefit_sgd_per_commuter_per_year"}))
    reg = pa.groupby("region").agg(user_benefit=("user_benefit", "sum"), commuters=("commuters", "sum"))
    top = pa.head(5)

    # ---- sensitivity tests ---------------------------------------------------------------------------------------------
    rng_vot = v(val["value_of_time_range"])
    capital = v(ac["costs"]["capital_cost_pv_sgd_million"]) * 1e6
    tests = [("core", comp, {})]
    for name, factor in ((f"value of time -{rng_vot:.0%}", 1 - rng_vot), (f"value of time +{rng_vot:.0%}", 1 + rng_vot)):
        tests.append((name, annual_components(day, ac, occupancy, vot=vot * factor), {}))
    tests += [
        ("discount rates of the Green Book 2026", comp, {"schedule": v(ac["discounting"]["schedule_green_book_2026"])}),
        (f"flat discount rate {v(ac['discounting']['high_rate']):.0%}", comp,
         {"schedule": [[10 ** 6, v(ac["discounting"]["high_rate"])]]}),
        ("appraisal period 30 years", comp, {"years": 30}),
        ("benefits grow 1% a year", comp, {"growth": 0.01}),
        ("public-transport benefits to existing users only", dict(
            comp, pt_user_time=float(pt_existing.sum()) / 60.0 * v(ann["return_trip_factor"]) * days * vot), {}),
        ("no road decongestion counted", dict(comp, car_user_time=0.0), {}),
        ("road decongestion in 4 peak hours a day", annual_components(day, ac, occupancy, peak_hours=4.0), {}),
        ("220 working days a year", annual_components(day, ac, occupancy, days=220.0), {}),
        ("capital cost -50%", comp, {"capital": 0.5 * capital}),
        ("capital cost +50%", comp, {"capital": 1.5 * capital})]
    rows = []
    for name, cmp_, kw in tests:
        e = evaluate(float(sum(cmp_.values())), ac, **kw)
        rows.append({"test": name, "annual_benefit_sgd_million": sum(cmp_.values()) / 1e6, "pvb_sgd_million": e["pvb"] / 1e6,
                     "pvc_sgd_million": e["pvc"] / 1e6, "npv_sgd_million": e["npv"] / 1e6, "bcr": e["bcr"]})
    sens = pd.DataFrame(rows)
    write_csv(out / "appraisal_sensitivity.csv", sens)

    # ---- land-use test: the same line without Tengah (public-transport user benefits only) ---------------------------
    M0 = T_2020 * attendance * P0[1]
    M1 = T_2020 * attendance * P1[1]
    pt_min_2020 = float(rule_of_half(M0, M1, g_pt0, g_pt1).sum())
    tengah = (z.planning_area == "TENGAH").values
    pt_annual_2020 = pt_min_2020 / 60.0 * v(ann["return_trip_factor"]) * days * vot

    res = {
        "scenarios": {"do_minimum": v(ac["scheme"]["do_minimum"]), "do_something": v(ac["scheme"]["do_something"])},
        "quantities": dict(
            day, pt_trips_per_day_one_way_do_minimum=float(N0.sum()), pt_trips_per_day_one_way_do_something=float(N1.sum()),
            pt_person_hours_existing_users=float(pt_existing.sum() / 60.0),
            pt_mean_saving_min_per_pt_trip=float(pt_min.sum() / (0.5 * (N0.sum() + N1.sum()))),
            pt_pairs_with_higher_cost=int(np.sum(g_pt1 > g_pt0 + 1e-9)),
            pt_person_hours_logsum=float(ls_min.sum() / 60.0),
            rule_of_half_over_logsum=float(pt_min.sum() / ls_min.sum()) if ls_min.sum() != 0 else float("nan"),
            car_trips_per_peak_hour_do_minimum=float(Q0.sum()), car_trips_per_peak_hour_do_something=float(Q1.sum()),
            vehicle_hours_do_minimum=vh0, vehicle_hours_do_something=vh1, vehicle_km_do_minimum=vkm0,
            vehicle_km_do_something=vkm1,
            car_mean_time_saving_s_per_trip=float(car_h.sum() / (0.5 * (Q0.sum() + Q1.sum())) * 3600.0),
            car_od_pairs_slower=int(np.sum(car_h < -1e-9)), car_od_pairs_faster=int(np.sum(car_h > 1e-9))),
        "annual_benefits_sgd": dict(comp, total=annual),
        "annual_shares": {k: val_ / annual for k, val_ in comp.items()},
        "present_values_sgd": {k: val_ * f for k, val_ in comp.items()},
        "core": {"pvb_sgd": core["pvb"], "pv_operating_sgd": core["pv_operating"], "capital_sgd": capital,
                 "pvc_sgd": core["pvc"], "npv_sgd": core["npv"], "bcr": core["bcr"],
                 "pv_per_annual_unit": f, "first_benefit_year": v(ac["scheme"]["opening_year"]),
                 "last_benefit_year": v(ac["scheme"]["opening_year"]) + v(ac["scheme"]["appraisal_years"]) - 1},
        "switching": {
            "benefit_multiple_for_bcr_1": core["pvc"] / core["pvb"],
            "capital_cost_for_bcr_1_sgd": core["pvb"] - core["pv_operating"],
            "value_of_time_for_bcr_1_sgd_per_hour": switching_value(vot, time_annual * f, (annual - time_annual) * f,
                                                                    core["pvc"]),
            "annual_benefit_for_bcr_1_sgd": core["pvc"] / f},
        "distribution": {
            "attributed_user_benefit_sgd_per_year": attributed,
            "not_attributed_sgd_per_year": annual - attributed,
            "west_region_share": float(reg.user_benefit.get("WEST REGION", 0.0) / attributed),
            "west_region_share_of_commuters": float(reg.commuters.get("WEST REGION", 0.0) / reg.commuters.sum()),
            "tengah_share": float((zone_pt[tengah].sum() + zone_car[tengah].sum()) / attributed),
            "tengah_share_of_commuters": float(commuters[tengah].sum() / commuters.sum()),
            "tengah_benefit_per_commuter_sgd": float((zone_pt[tengah].sum() + zone_car[tengah].sum())
                                                     / commuters[tengah].sum()),
            "all_benefit_per_commuter_sgd": float(attributed / commuters.sum()),
            "planning_areas_with_commuters": int(len(pa)),
            "planning_areas_losing": int((pa.user_benefit < 0).sum()),
            "top5": [{"planning_area": r.planning_area, "share": float(r.share_of_user_benefit)} for r in top.itertuples()],
            "top5_share": float(top.share_of_user_benefit.sum()),
            "by_region": {r: {"share": float(x.user_benefit / attributed),
                              "per_commuter_sgd": float(x.user_benefit / x.commuters)} for r, x in reg.iterrows()}},
        "land_use_test": {
            "pt_user_time_sgd_per_year_with_tengah": comp["pt_user_time"],
            "pt_user_time_sgd_per_year_2020_land_use": pt_annual_2020,
            "share_of_pt_user_benefit_due_to_tengah": 1.0 - pt_annual_2020 / comp["pt_user_time"],
            "pt_person_hours_per_day_one_way_2020_land_use": pt_min_2020 / 60.0,
            "pvb_pt_user_time_with_tengah_sgd": comp["pt_user_time"] * f,
            "pvb_pt_user_time_2020_land_use_sgd": pt_annual_2020 * f},
        "sensitivity": {"bcr_min": float(sens.bcr.min()), "bcr_max": float(sens.bcr.max()),
                        "tests": int(len(sens) - 1), "tests_with_bcr_at_least_1": int((sens.bcr[1:] >= 1.0).sum())}}
    write_json(out / "appraisal.json", res)
    return res
