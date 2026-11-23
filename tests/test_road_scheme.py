"""The stylised road scheme: link selection, widening, a two-route example solved by hand and by the assignment
code, its appraisal with fixed demand, and checks of the committed results. The scheme is ILLUSTRATIVE."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stm import appraisal as A
from stm import model as M
from stm import road_scheme as RS
from stm.assignment import Network, assign
from stm.paths import Graph
from stm.pipeline import write_csv, write_json

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"
XY = np.array([[0.0, 1000.0], [0.0, 0.0], [0.0, 1000.0], [0.0, 0.0]])     # nodes 0, 1 sources; 2, 3 sinks


def _toy():
    """Zone 0 lies north of zone 1. Two parallel roads run south from zone 0 to zone 1: "Fast Road" (motorway,
    10 km, 0.20 h free flow) and "Side Road" (primary, 8 km, 0.25 h); "Back Road" runs north from zone 1 to
    zone 0. Each has one lane of 1000 pcu/h and a linear delay function t = t0 (1 + v / c). Two more links stand
    in for the zone connectors."""
    g = Graph(np.array([0, 0, 1, 0, 1]), np.array([3, 3, 2, 2, 3]), 4)
    net = Network(graph=g, t0=np.array([0.20, 0.25, 0.30, 0.05, 0.05]),
                  capacity=np.array([1000.0, 1000.0, 1000.0, np.inf, np.inf]),
                  alpha=np.array([1.0, 1.0, 1.0, 0.0, 0.0]), beta=np.ones(5))
    links = pd.DataFrame({"link": [1, 2, 3], "a": [1, 1, 2], "b": [4, 4, 3],
                          "name": ["Fast Road", "Side Road", "Back Road"], "highway": ["motorway", "primary", "primary"],
                          "lanes": [1.0, 1.0, 1.0], "capacity": [1000.0, 1000.0, 1000.0], "length_km": [10.0, 8.0, 9.0]})
    return M.RoadModel(net=net, n_road_nodes=4, n_road_links=3, origins=np.array([0, 1]), dests=np.array([2, 3]),
                       links=links, length_km=np.array([10.0, 8.0, 9.0, 1.0, 1.0]))


def _rc(direction="southbound", road="Fast Road", highway="motorway"):
    def e(x):
        return {"value": x, "label": "ILLUSTRATIVE"}
    return {"scheme": {"road_name": e(road), "highway": e(highway), "direction": e(direction), "added_lanes": e(1),
                       "name": e("ds_road")},
            "costs": {"capital_cost_pv_sgd_million": e(2.0), "operating_cost_sgd_million_per_year": e(0.1)}}


CAP = {"motorway": 1000.0, "primary": 1000.0}
Q = np.array([[0.0, 2000.0], [300.0, 0.0]])


# ---- selection and widening -------------------------------------------------------------------------------------
def test_heading_and_selection():
    rm = _toy()
    assert RS.heading(rm.links, XY, "southbound").tolist() == [True, True, False]
    assert RS.heading(rm.links, XY, "northbound").tolist() == [False, False, True]
    assert RS.heading(rm.links, XY, "eastbound").tolist() == [False, False, False]
    assert RS.select_links(rm.links, XY, _rc()).tolist() == [True, False, False]
    assert RS.select_links(rm.links, XY, _rc(road="Back Road", highway="primary", direction="northbound")).tolist() == [
        False, False, True]
    with pytest.raises(ValueError):
        RS.select_links(rm.links, XY, _rc(direction="northbound"))     # the Fast Road has no northbound link
    with pytest.raises(ValueError):
        RS.select_links(rm.links, XY, _rc(highway="primary"))           # right name, wrong class
    with pytest.raises(ValueError):
        RS.heading(rm.links, XY, "upwards")


def test_widen_adds_capacity_to_the_selected_links_only():
    rm = _toy()
    mask = np.array([True, False, False])
    w = RS.widen(rm, mask, 1, CAP)
    assert w.net.capacity.tolist() == [2000.0, 1000.0, 1000.0, np.inf, np.inf]
    assert w.links.capacity.tolist() == [2000.0, 1000.0, 1000.0] and w.links.lanes.tolist() == [2.0, 1.0, 1.0]
    assert rm.net.capacity.tolist()[:3] == [1000.0, 1000.0, 1000.0] and rm.links.lanes.tolist() == [1.0, 1.0, 1.0]
    assert np.array_equal(w.net.t0, rm.net.t0) and w.net.graph is rm.net.graph        # free-flow times unchanged
    # two lanes of a class worth 700 pcu/h per lane on the second link
    w2 = RS.widen(rm, np.array([False, True, False]), 2, {"motorway": 1900.0, "primary": 700.0})
    assert w2.net.capacity.tolist()[:3] == [1000.0, 2400.0, 1000.0]
    with pytest.raises(ValueError):
        RS.widen(rm, np.array([True, False]), 1, CAP)


def test_corridor_ranking_hand():
    lf = pd.DataFrame({"name": ["A", "A", "A", "B", "B", "", "C"], "highway": ["motorway"] * 3 + ["primary"] * 4,
                       "length_km": [1.0, 2.0, 3.0, 4.0, 1.0, 9.0, 2.0], "vc": [1.2, 0.9, 1.01, 1.5, 0.2, 3.0, 1.0]})
    r = RS.corridor_ranking(lf, "vc", 1.0)
    # A: links 1 and 3 over (1 + 3 = 4 km of 6); B: 4 km of 5; C: exactly 1.0 is not over; the unnamed link is left out.
    # Equal km over the threshold: alphabetical order decides
    assert r.name.tolist() == ["A", "B", "C"]
    assert r.km_over_threshold.tolist() == [4.0, 4.0, 0.0]
    assert r.directed_km.tolist() == [6.0, 5.0, 2.0]
    assert r.max_vc.tolist() == [1.2, 1.5, 1.0]
    assert r.mean_vc_km_weighted.iloc[0] == pytest.approx((1.2 + 1.8 + 3.03) / 6)
    assert RS.corridor_ranking(lf, "vc", 1.3).name.iloc[0] == "B"


# ---- the two-route example: equilibrium by hand ------------------------------------------------------------------
def _solve(rm):
    r = assign(rm.net, rm.origins, rm.dests, Q, method="bfw", rgap_target=1e-12, max_iter=2000)
    assert r.converged
    return r.flow


def test_two_route_equilibrium_and_summary_by_hand():
    # Without the scheme, x on the Fast Road and 2000 - x on the Side Road have equal times:
    #   0.20 (1 + x / 1000) = 0.25 (1 + (2000 - x) / 1000)  ->  0.00045 x = 0.55  ->  x = 1222.22, t = 0.444444 h
    # With one more lane on the Fast Road (capacity 2000):
    #   0.20 (1 + x / 2000) = 0.25 (1 + (2000 - x) / 1000)  ->  0.00035 x = 0.55  ->  x = 1571.43, t = 0.357143 h
    rm = _toy()
    mask = RS.select_links(rm.links, XY, _rc())
    rm1 = RS.widen(rm, mask, 1, CAP)
    f0, f1 = _solve(rm), _solve(rm1)
    assert f0[:3] == pytest.approx([1222.2222, 777.7778, 300.0], rel=1e-6)
    assert f1[:3] == pytest.approx([1571.4286, 428.5714, 300.0], rel=1e-6)
    s = RS.summarise(rm, rm1, mask, f0, f1, 1.0)
    assert (s["links"], s["directed_km"], s["lane_km_added"]) == (1, 10.0, 10.0)
    assert s["capacity_added_share"] == pytest.approx(1.0)
    # corridor: V/C 1.2222 -> 0.7857; speed 10 km / 0.444444 h = 22.5 -> 10 / 0.357143 = 28 km/h
    assert s["corridor_without"]["max_vc"] == pytest.approx(1.2222222, rel=1e-6)
    assert s["corridor_with"]["max_vc"] == pytest.approx(0.7857143, rel=1e-6)
    assert s["corridor_without"]["km_over_threshold"] == 10.0 and s["corridor_with"]["km_over_threshold"] == 0.0
    assert s["corridor_without"]["mean_speed_kmh_flow_weighted"] == pytest.approx(22.5, rel=1e-6)
    assert s["corridor_with"]["mean_speed_kmh_flow_weighted"] == pytest.approx(28.0, rel=1e-6)
    assert s["corridor_traffic_growth"] == pytest.approx(1571.4286 / 1222.2222 - 1, rel=1e-6)       # +28.6%
    # 349.21 pcu/h leave the 8 km Side Road: 2793.65 vehicle-km
    assert s["vehicle_km_moved_off_other_roads"] == pytest.approx(349.2063 * 8, rel=1e-6)
    # network: vehicle-km 12222.22 + 6222.22 + 2700 = 21144.44 -> 15714.29 + 3428.57 + 2700 = 21842.86
    assert s["network_without"]["vehicle_km"] == pytest.approx(21144.444, rel=1e-6)
    assert s["network_with"]["vehicle_km"] == pytest.approx(21842.857, rel=1e-6)
    # vehicle-hours: 2000 x 0.444444 + 300 x 0.3 x 1.3 = 1005.89 -> 2000 x 0.357143 + 117 = 831.29
    assert s["network_without"]["vehicle_hours"] == pytest.approx(2000 * 0.4444444 + 117.0, rel=1e-6)
    assert s["network_with"]["vehicle_hours"] == pytest.approx(2000 * 0.3571429 + 117.0, rel=1e-6)
    assert s["other_links_vc_down_by_0_05"] == 1 and s["other_links_vc_up_by_0_05"] == 0


def _toy_ac():
    def e(x):
        return {"value": x, "label": "ILLUSTRATIVE"}
    return {
        "scheme": {"do_minimum": e("dm"), "do_something": e("ds"), "base_year": e(2026), "opening_year": e(2027),
                   "appraisal_years": e(2), "benefit_growth_per_year": e(0.0)},
        "discounting": {"schedule": e([[99, 0.0]]), "schedule_green_book_2026": e([[99, 0.0]]), "high_rate": e(0.07)},
        "values": {"value_of_time_sgd_per_hour": e(10.0), "value_of_time_range": e(0.25),
                   "fuel_litres_per_100km": e(10.0), "fuel_price_sgd_per_litre": e(3.0),
                   "non_fuel_cost_sgd_per_km": e(0.1), "co2_kg_per_vehicle_km": e(0.25),
                   "carbon_price_sgd_per_tonne": e(40.0)},
        "annualisation": {"working_days_per_year": e(200), "return_trip_factor": e(2.0), "road_peak_hours_per_day": e(2.0)},
        "costs": {"capital_cost_pv_sgd_million": e(9.0), "operating_cost_sgd_million_per_year": e(9.0)}}


def test_two_route_appraisal_with_fixed_demand_by_hand(tmp_path):
    rm = _toy()
    mask = RS.select_links(rm.links, XY, _rc())
    rm1 = RS.widen(rm, mask, 1, CAP)
    f0, f1 = _solve(rm), _solve(rm1)
    z = pd.DataFrame({"planning_area": ["NORTHTOWN", "SOUTHTOWN"], "region": ["NORTH REGION", "CENTRAL REGION"]})
    T = np.array([[0.0, 9000.0], [1000.0, 0.0]])
    P = np.array([np.full((2, 2), 0.3), np.full((2, 2), 0.6), np.full((2, 2), 0.1)])
    g_pt = np.full((2, 2), 40.0)
    ac = RS.appraisal_config(_toy_ac(), _rc())
    kw = dict(z=z, T_do_min=T, T_2020=None, P0=P, P1=P, V0=np.log(P), V1=np.log(P), b_time=-0.1, g_pt0=g_pt, g_pt1=g_pt,
              flow0=f0, flow1=f1, rm=rm, rm1=rm1, attendance=0.9, occupancy=1.2, write_json=write_json,
              write_csv=write_csv, ac=ac, out_name="toy_road")
    r = A.run(tmp_path, Q0=Q, Q1=Q, fixed_demand=True, **kw)
    q, b = r["quantities"], r["annual_benefits_sgd"]
    # time: 2000 trips x (0.444444 - 0.357143) h = 174.603 vehicle-hours per peak hour; zone 1 -> 0 unchanged
    assert q["car_vehicle_hours_per_peak_hour"] == pytest.approx(2000 * (0.55 / 0.45 * 0.2 + 0.2 - (0.55 / 0.35 * 0.1 + 0.2)),
                                                                 rel=1e-6)
    assert q["car_vehicle_hours_per_peak_hour"] == pytest.approx(174.60317, rel=1e-6)
    assert q["vehicle_km_change_per_peak_hour"] == pytest.approx(698.41270, rel=1e-6)       # 349.21 x (10 - 8) km
    assert q["fixed_demand_vehicle_km_change_per_peak_hour"] == pytest.approx(698.41270, rel=1e-6)
    assert q["pt_person_hours_per_day_one_way"] == 0.0
    # vehicle-hours on road links, each at its own network's times: 2000 x 0.444444 + 117 -> 2000 x 0.357143 + 117
    assert q["vehicle_hours_do_minimum"] == pytest.approx(2000 * 0.4444444 + 117.0, rel=1e-6)
    assert q["vehicle_hours_do_something"] == pytest.approx(2000 * 0.3571429 + 117.0, rel=1e-6)
    # 2 peak hours x 200 days = 400 hours a year
    assert b["car_user_time"] == pytest.approx(174.60317 * 1.2 * 400 * 10, rel=1e-6)        # 838,095
    assert b["car_user_fuel"] == pytest.approx(-698.41270 * 0.30 * 400, rel=1e-6)           # -83,810 (10 l/100 km x S$3)
    assert b["car_non_fuel_operating"] == pytest.approx(-698.41270 * 0.1 * 400, rel=1e-6)   # -27,937
    assert b["co2"] == pytest.approx(-698.41270 * 0.25 / 1000 * 40 * 400, rel=1e-6)         # -2,794
    assert b["pt_user_time"] == 0.0
    assert b["total"] == pytest.approx(838095.2 - 83809.5 - 27936.5 - 2793.7, rel=1e-6)
    # costs come from the road scheme: 2,000,000 + 2 years x 100,000, no discounting
    assert r["core"]["pvc_sgd"] == pytest.approx(2200000.0)
    assert r["core"]["pvb_sgd"] == pytest.approx(2 * b["total"])
    assert r["scenarios"]["do_something"] == "ds_road" and r["fixed_demand"] is True
    assert "land_use_test" not in r
    d = r["distribution"]
    assert d["by_region"]["NORTH REGION"]["share"] == pytest.approx(1.0)                    # zone 0 makes the faster trips
    assert d["attributed_user_benefit_sgd_per_year"] == pytest.approx(b["car_user_time"])
    assert (tmp_path / "toy_road.json").exists() and (tmp_path / "toy_road_sensitivity.csv").exists()
    assert (tmp_path / "toy_road_benefits_by_planning_area.csv").exists()
    # without the fixed-demand flag the same run counts no fuel; with it, demand must really be the same matrix
    r2 = A.run(tmp_path, Q0=Q, Q1=Q, fixed_demand=False, **kw)
    assert r2["annual_benefits_sgd"]["car_user_fuel"] == 0.0
    assert r2["annual_benefits_sgd"]["car_user_time"] == pytest.approx(b["car_user_time"])
    with pytest.raises(ValueError):
        A.run(tmp_path, Q0=Q, Q1=0.9 * Q, fixed_demand=True, **kw)


def test_first_round_mode_response_by_hand():
    # one zone pair; utilities V_car = -0.1 t_car, V_pt = -0.1 g_pt, "other" switched off with a constant of -50.
    # Equal times of 30 minutes: car probability 0.5. Car 10 minutes faster: 1 / (1 + exp(-1)) = 0.731059
    theta = np.array([0.0, -50.0, -0.1, 0.0, 0.0, 0.0, 0.0, 0.0])
    one, zero = np.array([[30.0]]), np.zeros(1)
    p0 = RS.car_probability_after_time_change(theta, one, np.array([[0.0]]), one, np.array([[5.0]]), zero, zero, zero)
    p1 = RS.car_probability_after_time_change(theta, one, np.array([[-10.0]]), one, np.array([[5.0]]), zero, zero, zero)
    assert p0[0, 0] == pytest.approx(0.5, abs=1e-9)
    assert p1[0, 0] == pytest.approx(0.7310586, rel=1e-6)


def test_appraisal_config_takes_costs_and_name_from_the_scheme():
    base = _toy_ac()
    out = RS.appraisal_config(base, _rc())
    assert out["costs"]["capital_cost_pv_sgd_million"]["value"] == 2.0
    assert out["costs"]["operating_cost_sgd_million_per_year"]["value"] == 0.1
    assert out["scheme"]["do_something"]["value"] == "ds_road" and out["scheme"]["do_minimum"]["value"] == "dm"
    assert out["values"] == base["values"] and out["discounting"] == base["discounting"]     # same basis as the rail line
    assert base["costs"]["capital_cost_pv_sgd_million"]["value"] == 9.0                      # the original is not touched


# ---- the committed scheme ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def committed():
    return (json.loads((RES / "road_scheme.json").read_text(encoding="utf-8")),
            json.loads((RES / "road_scheme_appraisal.json").read_text(encoding="utf-8")), RS.load_config())


def test_config_names_the_corridor_that_the_rule_picks_from_the_committed_flows(committed):
    rs, _, rc = committed
    lf = pd.read_csv(RES / "link_flows.csv", keep_default_na=False, na_values={"vc_dm_2030": [""]})
    rank = RS.corridor_ranking(lf, "vc_dm_2030", rc["selection"]["threshold_vc"]["value"])
    assert rank.name.iloc[0] == rc["scheme"]["road_name"]["value"]
    assert rank.highway.iloc[0] == rc["scheme"]["highway"]["value"]
    assert rank.km_over_threshold.iloc[0] == pytest.approx(rs["selection"]["km_over_threshold"], rel=1e-6)
    assert rs["selection"]["rule_picks"] == rc["scheme"]["road_name"]["value"]
    # every over-capacity km of that road is in the direction the scheme widens
    assert rs["selection"]["km_over_threshold_other_direction"] == 0.0
    assert rs["selection"]["km_over_threshold_in_scheme_direction"] == pytest.approx(rs["selection"]["km_over_threshold"])
    ranking = pd.read_csv(RES / "road_scheme_corridor_ranking.csv")
    assert ranking.name.iloc[0] == rank.name.iloc[0] and len(ranking) == 10
    # the README says the runner-up's highest V/C is above that of every expressway
    assert rank.max_vc.iloc[1] > rank.max_vc[rank.highway == "motorway"].max()


def test_committed_scheme_is_consistent(committed):
    rs, ap, rc = committed
    assert rs["illustrative"] is True and ap["fixed_demand"] is True
    assert rc["costs"]["capital_cost_pv_sgd_million"]["label"] == "ILLUSTRATIVE"
    assert rs["lane_km_added"] == pytest.approx(rs["directed_km"] * rc["scheme"]["added_lanes"]["value"])
    a, q = rs["assignment"], ap["quantities"]
    assert a["converged"] is True and 0 <= a["relative_gap_recomputed"] <= 1.001e-6
    # Fixed demand: the rule of a half over all zone pairs is the fall in shortest-path travel time, and at
    # equilibrium that is the fall in total travel time (connectors included), to within the relative gap
    assert q["car_vehicle_hours_per_peak_hour"] == pytest.approx(-a["shortest_path_travel_time_change_vehicle_hours"], rel=1e-6)
    assert q["car_vehicle_hours_per_peak_hour"] == pytest.approx(-a["total_travel_time_change_vehicle_hours"], rel=1e-3)
    assert q["car_trips_per_peak_hour_do_minimum"] == q["car_trips_per_peak_hour_do_something"] == pytest.approx(
        a["car_trips_per_hour"])
    assert q["vehicle_km_change_per_peak_hour"] == pytest.approx(
        rs["network_with"]["vehicle_km"] - rs["network_without"]["vehicle_km"], rel=1e-6)
    assert q["fixed_demand_vehicle_km_change_per_peak_hour"] == q["vehicle_km_change_per_peak_hour"]
    # more capacity: the corridor carries more traffic at a lower V/C, and the network spends fewer vehicle-hours
    assert rs["corridor_traffic_growth"] > 0
    assert rs["corridor_with"]["mean_vc_km_weighted"] < rs["corridor_without"]["mean_vc_km_weighted"]
    assert rs["corridor_with"]["mean_speed_kmh_flow_weighted"] > rs["corridor_without"]["mean_speed_kmh_flow_weighted"]
    assert rs["network_with"]["vehicle_hours"] < rs["network_without"]["vehicle_hours"]
    assert rs["corridor_with"]["vehicle_km"] - rs["corridor_without"]["vehicle_km"] == pytest.approx(
        rs["vehicle_km_moved_off_other_roads"] + q["vehicle_km_change_per_peak_hour"], rel=1e-6)
    b = ap["annual_benefits_sgd"]
    assert b["pt_user_time"] == 0.0 and b["car_user_time"] > 0
    val, ann = A.load_config()["values"], A.load_config()["annualisation"]
    hours = ann["road_peak_hours_per_day"]["value"] * ann["working_days_per_year"]["value"]
    assert b["car_user_fuel"] == pytest.approx(
        -q["vehicle_km_change_per_peak_hour"] * val["fuel_litres_per_100km"]["value"] / 100
        * val["fuel_price_sgd_per_litre"]["value"] * hours, rel=1e-8)
    assert sum(v for k, v in b.items() if k != "total") == pytest.approx(b["total"], rel=1e-9)
    assert ap["core"]["capital_sgd"] == pytest.approx(rc["costs"]["capital_cost_pv_sgd_million"]["value"] * 1e6)
    r = rs["first_round_mode_response"]
    assert 0 < r["share_of_car_trips"] < 0.01 and r["mean_car_time_change_min"] < 0
    # the README says the two schemes move vehicle-km in opposite directions
    rail = json.loads((RES / "appraisal.json").read_text(encoding="utf-8"))
    assert rail["quantities"]["vehicle_km_change_per_peak_hour"] < 0 < q["vehicle_km_change_per_peak_hour"]
    assert b["co2"] < 0 < rail["annual_benefits_sgd"]["co2"]


def test_rail_appraisal_counts_no_fuel():
    ap = json.loads((RES / "appraisal.json").read_text(encoding="utf-8"))
    assert ap["fixed_demand"] is False and ap["annual_benefits_sgd"]["car_user_fuel"] == 0.0
    assert ap["quantities"]["fixed_demand_vehicle_km_change_per_peak_hour"] == 0.0


def test_road_scheme_config_is_labelled():
    rc = RS.load_config()
    for sec, items in rc.items():
        if sec.startswith("_"):
            continue
        for name, e in items.items():
            assert e["label"] in {"ASSUMPTION", "ILLUSTRATIVE"}, name
    assert all(e["label"] == "ILLUSTRATIVE" for e in rc["costs"].values())
    assert "not an LTA proposal" in rc["_about"]
