"""Checks of the model logic on the real inputs: totals, allocations and the scenario arithmetic."""
import json

import numpy as np
import pandas as pd
import pytest

from stm import model as M
from stm import pipeline as P


@pytest.fixture(scope="module")
def base():
    cfg = M.load_config()
    inp = M.load_inputs()
    z = M.zone_table(inp)
    te = M.trip_ends_2020(inp, cfg, z)
    return cfg, inp, z, te


def test_trip_ends_equal_census_totals(base):
    cfg, inp, z, te = base
    wp = inp["workplace"]
    named = wp[~wp.workplace.isin(M.NON_WORKPLACE) & (wp.region_of_residence != "TOTAL")]
    travellers = named[named["mode"].isin(["pt", "car_taxi", "other"])].persons.sum()
    assert te["O"].sum() == pytest.approx(travellers)
    assert te["D"].sum() == pytest.approx(travellers)
    for k, reg in enumerate(M.REGIONS):
        m = z.region.values == reg
        assert te["O"][m].sum() == pytest.approx(te["N_region_workplace"][k].sum())
    for j, pa in enumerate(te["workplaces"]):
        m = z.planning_area.values == pa
        assert te["D"][m].sum() == pytest.approx(te["N_region_workplace"][:, j].sum())


def test_census_workplace_table_hand_values(base):
    cfg, inp, z, te = base
    # Census 2020 workplace table, row "Jurong East", West Region columns (copied by hand from the published CSV):
    # total 32,802 = PT 20,805 + car/taxi 6,785 + other 3,530 + no transport 1,682 -> 31,120 travelling commuters
    wp = inp["workplace"]
    row = wp[(wp.workplace == "Jurong East") & (wp.region_of_residence == "WEST REGION")].set_index("mode").persons
    assert (row["total"], row["pt"], row["car_taxi"], row["other"], row["none"]) == (32802, 20805, 6785, 3530, 1682)
    j = te["workplaces"].index("JURONG EAST")
    k = list(M.REGIONS).index("WEST REGION")
    assert te["N_region_workplace"][k, j] == pytest.approx(31120)


def test_productions_follow_residents_20_64_within_a_planning_area(base):
    cfg, inp, z, te = base
    for pa in ("JURONG WEST", "TAMPINES", "BEDOK"):
        m = (z.planning_area == pa).values
        w = z.pop_20_64.values[m]
        assert te["O"][m] / te["O"][m].sum() == pytest.approx(w / w.sum())


def test_zero_trip_ends_where_census_has_none(base):
    cfg, inp, z, te = base
    assert np.all(te["O"][z.pop_20_64.values == 0] == 0)
    assert np.all(te["D"][te["zone_workplace"] < 0] == 0)


def test_peak_hour_share_is_the_bus_ratio(base):
    cfg, inp, z, te = base
    h = inp["bus_hourly_202607"].set_index("hour").weekday_trips_month_total
    assert M.peak_hour_share(inp, cfg, "202607") == pytest.approx(h[7] / h.loc[5:10].sum())


def test_car_demand_formula():
    cfg = M.load_config()
    a = cfg["model"]["assignment"]
    T = np.array([[100.0, 200.0], [300.0, 400.0]])
    P_car = np.full((2, 2), 0.25)
    Q = P.car_demand(T, P_car, cfg, 0.3)
    k = 0.9 * 0.3 * 0.25 / a["car_occupancy"]["value"] * a["background_factor"]["value"]
    assert Q[0, 1] == pytest.approx(200 * k)
    assert Q[1, 0] == pytest.approx(300 * k)
    assert Q[0, 0] == 0 and Q[1, 1] == 0


def test_tengah_additions(base):
    cfg, inp, z, te = base
    O_add, D_add, info = P.tengah_2030(inp, cfg, z, te)
    s = cfg["model"]["scenario_2030"]
    pop = s["tengah_homes"]["value"] * s["persons_per_home"]["value"]
    assert info["population"] == pytest.approx(pop)
    assert O_add.sum() == pytest.approx(pop * info["commuters_per_resident_west"])
    tz = (z.planning_area == "TENGAH").values
    assert O_add[~tz].sum() == 0 and D_add[~tz].sum() == 0
    assert O_add[tz].sum() > 0


def test_zone_of_points_on_the_real_outlines():
    geom = json.loads((M.INPUTS / "zones_geometry.json").read_text(encoding="utf-8"))
    z = pd.read_csv(M.INPUTS / "zones.csv")
    inside = z[z.centroid_at_rep_point == 0].head(40)
    got = P.zone_of_points(inside[["x", "y"]].values, geom)
    # centroids lie in their own zone (outlines are simplified, so allow a few on the edge)
    assert np.mean(got == inside.zone.values - 1) > 0.9


def test_industrial_share_bounds(base):
    cfg, inp, z, te = base
    s = M.industrial_share(inp, cfg, len(z))
    assert np.all((s >= 0) & (s <= 1))
    tuas = (z.planning_area == "TUAS").values
    core = (z.planning_area == "DOWNTOWN CORE").values
    assert s[tuas].mean() > 0.5 > s[core].mean()


def test_car_skim_is_symmetricish_and_intrazonal_rule(base):
    cfg, inp, z, te = base
    rm = M.road_model(inp, cfg, z)
    t, d = M.car_skims(rm, cfg)
    nz = len(z)
    off = d + np.diag(np.full(nz, np.inf))
    assert d[np.arange(nz), np.arange(nz)] == pytest.approx(0.5 * off.min(axis=1))
    # road distance can never be shorter than the straight line between centroids (connectors add 30%)
    xy = z[["x", "y"]].values / 1000.0
    straight = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    mask = ~np.eye(nz, dtype=bool)
    assert np.all(d[mask] >= straight[mask] * 0.999)
