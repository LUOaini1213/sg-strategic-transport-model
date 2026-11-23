"""Economic appraisal: identities, hand-worked numbers, a two-zone example run end to end, and arithmetic checks of
the committed results. Expected values are worked out in the comments, not taken from the code's own output."""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.integrate import quad

from stm import appraisal as A
from stm.assignment import Network
from stm.paths import Graph
from stm.pipeline import write_csv, write_json

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"


# ---- rule of a half ---------------------------------------------------------------------------------------------
def test_rule_of_half_hand():
    # 100 trips at cost 10 become 140 trips at cost 8: 1/2 (100 + 140) (10 - 8) = 240
    assert A.rule_of_half(100, 140, 10, 8) == pytest.approx(240.0)
    # existing users 100 x 2 = 200, new users 1/2 x 40 x 2 = 40
    assert A.existing_user_benefit(100, 10, 8) == pytest.approx(200.0)


@pytest.mark.parametrize("a,b,c0,c1", [(500.0, 20.0, 10.0, 8.0), (80.0, 1.5, 30.0, 12.0), (1000.0, 7.0, 5.0, 9.0)])
def test_rule_of_half_is_the_exact_surplus_integral_for_linear_demand(a, b, c0, c1):
    # demand D(c) = a - b c; the change in consumer surplus is the integral of D from c1 to c0
    #   = a (c0 - c1) - b (c0^2 - c1^2) / 2, and also the area found numerically
    def demand(c):
        return a - b * c
    closed = a * (c0 - c1) - b * (c0 ** 2 - c1 ** 2) / 2.0
    numeric, _ = quad(demand, c1, c0)
    roh = A.rule_of_half(demand(c0), demand(c1), c0, c1)
    assert roh == pytest.approx(closed, rel=1e-12)
    assert roh == pytest.approx(numeric, rel=1e-9)


def test_zero_change_gives_zero_benefit():
    rng = np.random.default_rng(1)
    T, c = rng.uniform(0, 100, (4, 4)), rng.uniform(5, 50, (4, 4))
    assert np.all(A.rule_of_half(T, T, c, c) == 0.0)
    assert np.all(A.rule_of_half(T, 2 * T, c, c) == 0.0)       # more trips at an unchanged cost: no user benefit


def test_reversing_the_scheme_reverses_the_sign():
    rng = np.random.default_rng(2)
    T0, T1 = rng.uniform(0, 100, (5, 5)), rng.uniform(0, 100, (5, 5))
    c0, c1 = rng.uniform(5, 50, (5, 5)), rng.uniform(5, 50, (5, 5))
    assert A.rule_of_half(T0, T1, c0, c1) == pytest.approx(-A.rule_of_half(T1, T0, c1, c0))
    assert A.rule_of_half(T0, T1, c0, c1) + A.rule_of_half(T1, T0, c1, c0) == pytest.approx(np.zeros((5, 5)), abs=1e-9)


def test_rule_of_half_overstates_for_demand_convex_to_the_origin():
    # constant-elasticity demand D = 1000 c^-1 from cost 10 to 5: exact surplus 1000 ln 2 = 693.1;
    # rule of a half 1/2 (100 + 200) x 5 = 750
    exact, _ = quad(lambda c: 1000.0 / c, 5.0, 10.0)
    assert exact == pytest.approx(1000.0 * math.log(2.0))
    assert A.rule_of_half(100.0, 200.0, 10.0, 5.0) == pytest.approx(750.0)
    assert A.rule_of_half(100.0, 200.0, 10.0, 5.0) > exact


# ---- logsum -----------------------------------------------------------------------------------------------------
def test_logsum_hand():
    assert A.logsum(np.array([[0.0], [0.0]]))[0] == pytest.approx(math.log(2.0))
    assert A.logsum(np.array([[1.0], [3.0]]))[0] == pytest.approx(3.0 + math.log(1.0 + math.exp(-2.0)))


def test_logsum_benefit_single_mode_is_trips_times_cost_change():
    # one mode, V = -0.05 x cost: 200 trips, cost 40 -> 30 minutes: benefit 200 x 10 = 2000 minutes
    b = -0.05
    out = A.logsum_benefit(np.array([200.0]), np.array([[b * 40.0]]), np.array([[b * 30.0]]), b)
    assert out[0] == pytest.approx(2000.0)
    with pytest.raises(ValueError):
        A.logsum_benefit(np.array([1.0]), np.array([[0.0]]), np.array([[0.0]]), 0.01)


def test_rule_of_half_close_to_logsum_for_a_small_change():
    # binary logit, cost coefficient -0.1 per minute; mode 1 improves from 30 to 29 minutes, mode 2 stays at 25.
    # P1 = 1 / (1 + exp(0.1 (c1 - 25))): 0.377541 before, 0.401312 after (per 1000 travellers: 377.541, 401.312)
    # rule of a half: 1/2 (377.541 + 401.312) x 1 = 389.43; logsum: 1000 x ln(...) / 0.1 = 389.46
    b, T = -0.1, 1000.0
    V0 = np.array([[b * 30.0], [b * 25.0]])
    V1 = np.array([[b * 29.0], [b * 25.0]])
    p0 = 1.0 / (1.0 + math.exp(0.5))
    p1 = 1.0 / (1.0 + math.exp(0.4))
    assert p0 == pytest.approx(0.377541, abs=1e-6) and p1 == pytest.approx(0.401312, abs=1e-6)
    roh = A.rule_of_half(T * p0, T * p1, 30.0, 29.0)
    ls = A.logsum_benefit(np.array([T]), V0, V1, b)[0]
    assert roh == pytest.approx(389.43, abs=0.01)
    assert ls == pytest.approx(roh, rel=1e-3)
    assert ls != pytest.approx(roh, rel=1e-6)          # close, not identical: the logit demand curve is not linear


# ---- discounting ------------------------------------------------------------------------------------------------
def test_annual_rate_boundaries():
    sch = [[30, 0.035], [75, 0.03]]
    assert A.annual_rate(1, sch) == 0.035
    assert A.annual_rate(30, sch) == 0.035
    assert A.annual_rate(31, sch) == 0.03
    assert A.annual_rate(75, sch) == 0.03
    assert A.annual_rate(90, sch) == 0.03               # beyond the last limit the last rate still applies


def test_discount_factors_hand():
    # 10% for years 1-2, then 5%: 1, 1/1.1, 1/1.21, 1/(1.21 x 1.05), 1/(1.21 x 1.1025)
    f = A.discount_factors(4, [[2, 0.10], [99, 0.05]])
    assert f == pytest.approx([1.0, 0.9090909, 0.8264463, 0.7870917, 0.7496111], rel=1e-6)


def test_benefit_stream_and_present_value_hand():
    # 100 a year growing 10%, first in year 2, for 3 years: 0, 0, 100, 110, 121
    s = A.benefit_stream(100.0, 2, 3, 0.10)
    assert s == pytest.approx([0.0, 0.0, 100.0, 110.0, 121.0])
    # at a flat 10%: 100/1.21 + 110/1.331 + 121/1.4641 = 3 x 82.644628 = 247.933884
    assert A.present_value(s, [[99, 0.10]]) == pytest.approx(247.933884, rel=1e-8)
    assert A.present_value(A.benefit_stream(100.0, 0, 3), [[99, 0.0]]) == pytest.approx(300.0)


def test_npv_bcr_and_switching_value():
    assert A.npv(150.0, 100.0) == 50.0
    assert A.bcr(150.0, 100.0) == 1.5
    assert math.isnan(A.bcr(150.0, 0.0))
    # benefits = 50 (proportional to a parameter now worth 10) + 20 (fixed); costs 120:
    # the parameter must reach 10 x (120 - 20) / 50 = 20, and then 50 x 20/10 + 20 = 120
    sv = A.switching_value(10.0, 50.0, 20.0, 120.0)
    assert sv == pytest.approx(20.0)
    assert 50.0 * sv / 10.0 + 20.0 == pytest.approx(120.0)
    assert math.isnan(A.switching_value(10.0, 0.0, 20.0, 120.0))


# ---- a two-zone example, end to end -----------------------------------------------------------------------------
def _toy_config():
    def e(x):
        return {"value": x, "label": "ILLUSTRATIVE"}
    return {
        "scheme": {"do_minimum": e("dm"), "do_something": e("ds"), "base_year": e(2026), "opening_year": e(2027),
                   "appraisal_years": e(2), "benefit_growth_per_year": e(0.0)},
        "discounting": {"schedule": e([[99, 0.0]]), "schedule_green_book_2026": e([[99, 0.0]]), "high_rate": e(0.07)},
        "values": {"value_of_time_sgd_per_hour": e(10.0), "value_of_time_range": e(0.25),
                   "non_fuel_cost_sgd_per_km": e(0.1), "co2_kg_per_vehicle_km": e(0.25),
                   "carbon_price_sgd_per_tonne": e(40.0)},
        "annualisation": {"working_days_per_year": e(200), "return_trip_factor": e(2.0), "road_peak_hours_per_day": e(2.0)},
        "costs": {"capital_cost_pv_sgd_million": e(1.0), "operating_cost_sgd_million_per_year": e(0.5)}}


def _toy_run(tmp_path):
    # nodes 0, 1 = sources of zones 0, 1; nodes 2, 3 = their sinks. Road links 0 -> 3 and 1 -> 2 (10 km, free-flow
    # 0.5 h, capacity 1000, BPR 0.15 and 4); two connector-like links 0 -> 2 and 1 -> 3 for intrazonal paths.
    g = Graph(np.array([0, 1, 0, 1]), np.array([3, 2, 2, 3]), 4)
    net = Network(graph=g, t0=np.array([0.5, 0.5, 0.1, 0.1]), capacity=np.array([1000.0, 1000.0, np.inf, np.inf]),
                  alpha=np.array([0.15, 0.15, 0.0, 0.0]), beta=np.array([4.0, 4.0, 1.0, 1.0]))
    rm = SimpleNamespace(net=net, n_road_links=2, origins=np.array([0, 1]), dests=np.array([2, 3]),
                         links=pd.DataFrame({"length_km": [10.0, 10.0]}), length_km=np.array([10.0, 10.0, 1.0, 1.0]))
    z = pd.DataFrame({"planning_area": ["TENGAH", "ELSEWHERE"], "region": ["WEST REGION", "EAST REGION"]})
    T = np.array([[0.0, 10000.0], [4000.0, 0.0]])
    P0 = np.array([np.full((2, 2), 0.3), np.full((2, 2), 0.5), np.full((2, 2), 0.2)])
    P1 = P0.copy()
    P1[:, 0, 1] = [0.25, 0.6, 0.15]
    g0 = np.full((2, 2), 40.0)
    g1 = g0.copy()
    g1[0, 1] = 30.0
    Q0 = np.array([[0.0, 1000.0], [500.0, 0.0]])
    Q1 = np.array([[0.0, 900.0], [500.0, 0.0]])
    return A.run(tmp_path, z=z, T_do_min=T, T_2020=0.5 * T, P0=P0, P1=P1, V0=np.log(P0), V1=np.log(P1), b_time=-0.1,
                 g_pt0=g0, g_pt1=g1, Q0=Q0, Q1=Q1, flow0=np.array([1000.0, 500.0, 0.0, 0.0]),
                 flow1=np.array([900.0, 500.0, 0.0, 0.0]), rm=rm, attendance=0.9, occupancy=1.2,
                 write_json=write_json, write_csv=write_csv, ac=_toy_config())


def test_two_zone_example_by_hand(tmp_path):
    r = _toy_run(tmp_path)
    q = r["quantities"]
    # public transport, zone 0 -> 1: 10000 x 0.9 x 0.5 = 4500 trips become 10000 x 0.9 x 0.6 = 5400; cost 40 -> 30:
    #   1/2 (4500 + 5400) x 10 = 49,500 min = 825 h; existing users 4500 x 10 / 60 = 750 h
    assert q["pt_trips_per_day_one_way_do_minimum"] == pytest.approx(4500.0 + 1800.0)
    assert q["pt_person_hours_per_day_one_way"] == pytest.approx(825.0)
    assert q["pt_person_hours_existing_users"] == pytest.approx(750.0)
    # road, link 0: time 0.5 (1 + 0.15 x 1^4) = 0.575 h at 1000 pcu/h, 0.5 (1 + 0.15 x 0.9^4) = 0.5492075 h at 900:
    #   1/2 (1000 + 900) (0.575 - 0.5492075) = 24.502875 vehicle-hours; link 1 unchanged
    assert q["car_vehicle_hours_per_peak_hour"] == pytest.approx(24.502875, rel=1e-9)
    assert q["vehicle_km_change_per_peak_hour"] == pytest.approx(-1000.0)       # 14,000 - 15,000
    assert q["vehicle_hours_do_minimum"] == pytest.approx(1000 * 0.575 + 500 * 0.5 * (1 + 0.15 * 0.5 ** 4))
    b = r["annual_benefits_sgd"]
    assert b["pt_user_time"] == pytest.approx(825.0 * 2 * 200 * 10)             # 3,300,000
    assert b["car_user_time"] == pytest.approx(24.502875 * 1.2 * 2 * 200 * 10)  # 117,613.8
    assert b["car_non_fuel_operating"] == pytest.approx(1000 * 0.1 * 2 * 200)   # 40,000
    assert b["co2"] == pytest.approx(1000 * 0.25 / 1000 * 40 * 2 * 200)         # 4,000
    assert b["total"] == pytest.approx(3300000 + 117613.8 + 40000 + 4000)
    # no discounting, two years of benefits: PVB = 2 x total; PVC = 1,000,000 + 2 x 500,000
    c = r["core"]
    assert c["pvb_sgd"] == pytest.approx(2 * 3461613.8)
    assert c["pvc_sgd"] == pytest.approx(2000000.0)
    assert c["bcr"] == pytest.approx(3.4616138)
    assert c["npv_sgd"] == pytest.approx(2 * 3461613.8 - 2000000.0)
    assert (c["first_benefit_year"], c["last_benefit_year"]) == (2027, 2028)
    s = r["switching"]
    assert s["capital_cost_for_bcr_1_sgd"] == pytest.approx(2 * 3461613.8 - 1000000.0)
    assert s["benefit_multiple_for_bcr_1"] == pytest.approx(1 / 3.4616138)
    # value of time at which benefits equal costs: (2,000,000 - 2 x 44,000) / (2 x 341,761.38) = 2.797273
    assert s["value_of_time_for_bcr_1_sgd_per_hour"] == pytest.approx(10.0 * (2000000 - 88000) / (2 * 3417613.8))
    # zone 0 (Tengah) receives every user benefit; with half the commuters (the "2020 land use") half the PT benefit
    d = r["distribution"]
    assert d["tengah_share"] == pytest.approx(1.0)
    assert d["west_region_share"] == pytest.approx(1.0)
    assert d["attributed_user_benefit_sgd_per_year"] == pytest.approx(3300000 + 117613.8)
    assert d["not_attributed_sgd_per_year"] == pytest.approx(44000.0)
    assert d["tengah_benefit_per_commuter_sgd"] == pytest.approx(3417613.8 / 10000)
    assert r["land_use_test"]["share_of_pt_user_benefit_due_to_tengah"] == pytest.approx(0.5)
    sens = pd.read_csv(tmp_path / "appraisal_sensitivity.csv").set_index("test")
    assert sens.loc["core", "bcr"] == pytest.approx(3.4616138, rel=1e-6)
    # value of time +25%: time benefits x 1.25 -> (1.25 x 3,417,613.8 + 44,000) x 2 / 2,000,000 = 4.3160
    assert sens.loc["value of time +25%", "bcr"] == pytest.approx((1.25 * 3417613.8 + 44000) / 1e6, rel=1e-6)
    # existing users only: 750 h instead of 825 h -> 3,000,000 + 117,613.8 + 44,000
    assert sens.loc["public-transport benefits to existing users only", "annual_benefit_sgd_million"] == pytest.approx(
        3.1616138, rel=1e-6)
    assert sens.loc["no road decongestion counted", "annual_benefit_sgd_million"] == pytest.approx(3.344, rel=1e-6)
    assert sens.loc["capital cost +50%", "pvc_sgd_million"] == pytest.approx(2.5)
    assert sens.loc["appraisal period 30 years", "pvb_sgd_million"] == pytest.approx(30 * 3.4616138, rel=1e-6)


def test_evaluate_uses_the_schedule_from_the_base_year():
    ac = _toy_config()
    ac["scheme"]["opening_year"]["value"] = 2028
    ac["scheme"]["appraisal_years"]["value"] = 1
    # one benefit of 121 in year 2 at 10%: 121 / 1.21 = 100; operating cost 0.5 m in the same year: 413,223.14
    e = A.evaluate(121.0, ac, schedule=[[99, 0.10]])
    assert e["pvb"] == pytest.approx(100.0)
    assert e["pv_operating"] == pytest.approx(500000 / 1.21)
    assert e["pvc"] == pytest.approx(1000000 + 500000 / 1.21)
    assert e["bcr"] * e["pvc"] == pytest.approx(e["pvb"])


# ---- the committed appraisal ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def committed():
    return (json.loads((RES / "appraisal.json").read_text(encoding="utf-8")), A.load_config())


def test_committed_components_add_up(committed):
    r, ac = committed
    b = r["annual_benefits_sgd"]
    parts = [b[k] for k in b if k != "total"]
    assert sum(parts) == pytest.approx(b["total"], rel=1e-9)
    assert sum(r["present_values_sgd"].values()) == pytest.approx(r["core"]["pvb_sgd"], rel=1e-9)
    assert sum(r["annual_shares"].values()) == pytest.approx(1.0)
    c = r["core"]
    assert c["pvc_sgd"] == pytest.approx(c["capital_sgd"] + c["pv_operating_sgd"], rel=1e-9)
    assert c["npv_sgd"] == pytest.approx(c["pvb_sgd"] - c["pvc_sgd"], rel=1e-8)
    assert c["bcr"] == pytest.approx(c["pvb_sgd"] / c["pvc_sgd"], rel=1e-9)


def test_committed_values_follow_from_the_quantities_and_the_config(committed):
    r, ac = committed
    q, val, ann = r["quantities"], ac["values"], ac["annualisation"]
    vot, days = val["value_of_time_sgd_per_hour"]["value"], ann["working_days_per_year"]["value"]
    assert r["annual_benefits_sgd"]["pt_user_time"] == pytest.approx(
        q["pt_person_hours_per_day_one_way"] * ann["return_trip_factor"]["value"] * days * vot, rel=1e-8)
    assert r["annual_benefits_sgd"]["co2"] == pytest.approx(
        -q["vehicle_km_change_per_peak_hour"] * val["co2_kg_per_vehicle_km"]["value"] / 1000
        * val["carbon_price_sgd_per_tonne"]["value"] * ann["road_peak_hours_per_day"]["value"] * days, rel=1e-8)
    # the present value of 1 a year, recomputed here from the published schedule: 2030-2089 seen from 2026
    sch = ac["discounting"]["schedule"]["value"]
    f, total = 1.0, 0.0
    for k in range(1, 4 + 60):
        f /= 1.0 + (sch[0][1] if k <= sch[0][0] else sch[1][1])
        if k >= 4:
            total += f
    assert r["core"]["pv_per_annual_unit"] == pytest.approx(total, rel=1e-9)
    assert r["core"]["pvb_sgd"] == pytest.approx(r["annual_benefits_sgd"]["total"] * total, rel=1e-8)


def test_committed_switching_values_switch(committed):
    r, ac = committed
    q = r["quantities"]
    day = {k: q[k] for k in ("pt_person_hours_per_day_one_way", "car_vehicle_hours_per_peak_hour",
                             "vehicle_km_change_per_peak_hour")}
    occ = json.loads((REPO / "config" / "model.json").read_text(encoding="utf-8"))["assignment"]["car_occupancy"]["value"]
    comp = A.annual_components(day, ac, occ, vot=r["switching"]["value_of_time_for_bcr_1_sgd_per_hour"])
    assert A.evaluate(sum(comp.values()), ac)["bcr"] == pytest.approx(1.0, rel=1e-8)
    assert A.evaluate(r["annual_benefits_sgd"]["total"], ac,
                      capital=r["switching"]["capital_cost_for_bcr_1_sgd"])["bcr"] == pytest.approx(1.0, rel=1e-8)
    assert A.evaluate(r["switching"]["annual_benefit_for_bcr_1_sgd"], ac)["bcr"] == pytest.approx(1.0, rel=1e-8)


def test_committed_distribution_and_checks(committed):
    r, _ = committed
    pa = pd.read_csv(RES / "appraisal_benefits_by_planning_area.csv")
    assert pa.share_of_user_benefit.sum() == pytest.approx(1.0, abs=1e-6)
    assert pa.share_of_commuters.sum() == pytest.approx(1.0, abs=1e-6)
    assert pa.user_benefit_sgd_per_year.sum() == pytest.approx(r["distribution"]["attributed_user_benefit_sgd_per_year"],
                                                               rel=1e-5)
    d = r["distribution"]
    assert d["attributed_user_benefit_sgd_per_year"] + d["not_attributed_sgd_per_year"] == pytest.approx(
        r["annual_benefits_sgd"]["total"], rel=1e-9)
    assert sum(x["share"] for x in d["by_region"].values()) == pytest.approx(1.0)
    q = r["quantities"]
    assert q["pt_pairs_with_higher_cost"] == 0                    # a new line cannot make a public-transport path worse
    assert q["pt_person_hours_existing_users"] <= q["pt_person_hours_per_day_one_way"]
    assert 0.99 < q["rule_of_half_over_logsum"] < 1.01           # rule of a half against the logit model's own surplus
    # fewer car trips: time saved by remaining users is less than the fall in total vehicle-hours
    assert 0 < q["car_vehicle_hours_per_peak_hour"] < q["vehicle_hours_do_minimum"] - q["vehicle_hours_do_something"]
    sens = pd.read_csv(RES / "appraisal_sensitivity.csv").set_index("test")
    assert sens.loc["core", "bcr"] == pytest.approx(r["core"]["bcr"], rel=1e-6)
    assert sens.loc["value of time -25%", "bcr"] < sens.loc["core", "bcr"] < sens.loc["value of time +25%", "bcr"]
    assert sens.loc["flat discount rate 7%", "pvb_sgd_million"] < sens.loc["core", "pvb_sgd_million"]
    assert r["sensitivity"]["tests_with_bcr_at_least_1"] == int((sens.bcr.iloc[1:] >= 1).sum())


def test_appraisal_config_is_labelled_and_sourced():
    ac = A.load_config()
    for sec, items in ac.items():
        if sec.startswith("_"):
            continue
        for name, e in items.items():
            assert e["label"] in {"REAL", "DERIVED", "ASSUMPTION", "ILLUSTRATIVE"}, name
            if e["label"] in ("REAL", "DERIVED"):
                assert "http" in e["note"] and "read 2026-" in e["note"], f"{name}: needs a URL and the date it was read"
    assert ac["costs"]["capital_cost_pv_sgd_million"]["label"] == "ILLUSTRATIVE"
    assert ac["costs"]["operating_cost_sgd_million_per_year"]["label"] == "ILLUSTRATIVE"
