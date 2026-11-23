"""End-to-end checks against the committed results.

What runs by default (and in CI): the whole model is rebuilt from the committed inputs, except that the three
equilibrium assignments are not solved again. Their saved flows (results/link_flows.csv, connector_flows.csv) are
reused together with the demand matrices they were solved for (results/car_demand_*.npy), and the tests then check

  * that everything upstream of the assignment (trip ends, calibrations, mode choice, demand) and everything
    downstream of it (V/C, screenlines, junctions) comes out as committed;
  * independently, that each saved flow vector is a user equilibrium for its saved demand (one all-or-nothing
    load), and that the saved demand equals the freshly computed one;
  * that a fresh assignment of the base year, run from scratch to the looser reference gap, lands on the saved
    flows to within what that gap allows.

Why the assignments are not solved again by default: the path of the iterations depends on the last digits of
floating-point results, so two machines stop at slightly different flows. Set STM_FULL=1 to solve all three again
and compare (several minutes).
"""
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stm import model as M
from stm import pipeline as P
from stm.assignment import assign, equilibrium_gap

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"
SCENARIOS = ("base_2020", "dm_2030", "ds_2030_jrl")
SAVED = ["link_flows.csv", "connector_flows.csv", "assignment_convergence.csv", "assignment_tightness.csv"] + [
    f"car_demand_{n}.npy" for n in SCENARIOS]


@pytest.fixture(scope="session")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    for name in SAVED:
        shutil.copy2(RES / name, out / name)
    summary = P.run(out=out, assign_scenarios=False, verbose=False)
    return out, summary


@pytest.fixture(scope="session")
def road():
    cfg = M.load_config()
    inp = M.load_inputs()
    z = M.zone_table(inp)
    return cfg, M.road_model(inp, cfg, z)


def _leaves(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _leaves(v, f"{prefix}{k}.")
    elif isinstance(d, list):
        for k, v in enumerate(d):
            yield from _leaves(v, f"{prefix}{k}.")
    else:
        yield prefix[:-1], d


def test_snapshot_summary_matches_committed(fresh):
    out, _ = fresh
    new = dict(_leaves(json.loads((out / "summary.json").read_text(encoding="utf-8"))))
    old = dict(_leaves(json.loads((RES / "summary.json").read_text(encoding="utf-8"))))
    assert new.keys() == old.keys()
    for k, vo in old.items():
        vn = new[k]
        if isinstance(vo, (int, float)) and not isinstance(vo, bool):
            if k.endswith("max_abs_gradient") or k.endswith("moment_residual"):
                assert abs(vn) < 1e-5, k   # optimiser residuals: only their size matters
            elif k.endswith("saved_demand_max_diff_from_fresh_run"):
                assert vn < 1e-3, k
            elif "relative_gap" in k or "average_excess_cost" in k:
                assert vn == pytest.approx(vo, rel=1e-2, abs=1e-9), k
            else:
                # calibrated values come out of numerical optimisers; allow for platform differences
                assert vn == pytest.approx(vo, rel=1e-4, abs=1e-6), k
        else:
            assert vn == vo, k


def test_snapshot_tables_match_committed(fresh):
    out, _ = fresh
    for name in ("calibration_commute_cells.csv", "tld_bus.csv", "bus_pa_pairs_202608.csv", "mode_shares_residence.csv",
                 "mode_shares_workplace.csv", "mode_shares_holdout_cells.csv", "mode_choice_time_profile.csv",
                 "zones_trip_ends.csv", "link_flows.csv", "vc_by_class_base.csv", "scenario_mode_share_west.csv",
                 "junction_growth_factors.csv", "junction_example_turns.csv", "screenlines.csv"):
        a = pd.read_csv(out / name, keep_default_na=False, na_values=[""])
        b = pd.read_csv(RES / name, keep_default_na=False, na_values=[""])
        assert list(a.columns) == list(b.columns), name
        assert len(a) == len(b), name
        for c in a.columns:
            if pd.api.types.is_numeric_dtype(b[c]):
                assert np.allclose(a[c].values, b[c].values, rtol=1e-4, atol=1e-4, equal_nan=True), (name, c)
            else:
                assert (a[c].fillna("") == b[c].fillna("")).all(), (name, c)


def _saved_flow(rm, name):
    lf = pd.read_csv(RES / "link_flows.csv", usecols=[f"flow_{name}"])
    cf = pd.read_csv(RES / "connector_flows.csv")
    g = rm.net.graph
    kc = np.arange(rm.n_road_links, g.n_links)
    assert np.array_equal(cf["tail"].values, g.tail[kc]) and np.array_equal(cf["head"].values, g.head[kc])
    return np.concatenate([lf[f"flow_{name}"].values, cf[f"flow_{name}"].values])


def _numbers_close(new, old, rel, abs_, loose=()):
    new, old = dict(_leaves(new)), dict(_leaves(old))
    assert new.keys() == old.keys()
    for k, vo in old.items():
        vn = new[k]
        if isinstance(vo, (int, float)) and not isinstance(vo, bool):
            tol = loose[1] if loose and any(s in k for s in loose[0]) else abs_
            assert vn == pytest.approx(vo, rel=rel, abs=tol), k
        else:
            assert vn == vo, k


def _tables_close(out, names, rtol, atol):
    for name in names:
        a = pd.read_csv(out / name, keep_default_na=False, na_values=[""])
        b = pd.read_csv(RES / name, keep_default_na=False, na_values=[""])
        assert list(a.columns) == list(b.columns), name
        assert len(a) == len(b), name
        for c in a.columns:
            if pd.api.types.is_numeric_dtype(b[c]):
                assert np.allclose(a[c].values, b[c].values, rtol=rtol, atol=atol, equal_nan=True), (name, c)
            else:
                assert (a[c].fillna("") == b[c].fillna("")).all(), (name, c)


def test_snapshot_appraisal_matches_committed(fresh):
    out, _ = fresh
    _numbers_close(json.loads((out / "appraisal.json").read_text(encoding="utf-8")),
                   json.loads((RES / "appraisal.json").read_text(encoding="utf-8")), rel=1e-4, abs_=1e-6)
    _tables_close(out, ("appraisal_benefits_by_planning_area.csv", "appraisal_sensitivity.csv"), 1e-4, 1e-6)


def test_snapshot_survey_matches_committed(fresh):
    """The synthetic respondents come from a seeded generator, but the probabilities they are drawn with come
    out of numerical optimisers, so on another platform a handful of draws may fall differently: the tolerances
    allow for that."""
    out, _ = fresh
    _numbers_close(json.loads((out / "survey.json").read_text(encoding="utf-8")),
                   json.loads((RES / "survey.json").read_text(encoding="utf-8")), rel=5e-3, abs_=2e-3,
                   loose=(("coverage",), 0.0251))
    _tables_close(out, ("survey_sample_size.csv", "survey_sampling_plan.csv"), 1e-6, 1e-6)
    _tables_close(out, ("survey_estimates.csv",), 5e-3, 2e-3)
    a, b = pd.read_csv(out / "survey_accuracy.csv"), pd.read_csv(RES / "survey_accuracy.csv")
    for c in ("truth", "mean_estimate", "bias", "rmse", "mean_half_width"):
        assert np.allclose(a[c].values, b[c].values, rtol=5e-3, atol=2e-3), c
    n_new = len(pd.read_csv(out / "survey_synthetic_respondents.csv", usecols=["household"]))
    n_old = len(pd.read_csv(RES / "survey_synthetic_respondents.csv", usecols=["household"]))
    assert abs(n_new - n_old) <= 0.005 * n_old


def test_road_times_at_equilibrium_reproduce_the_shortest_path_travel_time(road):
    """The appraisal's car times are the quickest-path times at the saved flows; demand times those must equal
    the shortest-path total travel time that the equilibrium check computes by all-or-nothing loading."""
    from stm import appraisal as A
    cfg, rm = road
    Q = np.load(RES / "car_demand_dm_2030.npy")
    flow = _saved_flow(rm, "dm_2030")
    th = A.road_times(rm, flow)
    assert float((Q * th).sum()) == pytest.approx(equilibrium_gap(rm.net, flow, rm.origins, rm.dests, Q)["sptt"], rel=1e-9)
    free = A.road_times(rm, np.zeros_like(flow))
    off = ~np.eye(len(Q), dtype=bool)
    assert np.all(th[off] >= free[off] - 1e-12) and th[off].mean() > 1.02 * free[off].mean()


@pytest.mark.parametrize("name", SCENARIOS)
def test_committed_flows_are_user_equilibria(road, name):
    """Independent of the solver: one all-or-nothing load at the saved flows' own costs gives the gap."""
    cfg, rm = road
    target = cfg["model"]["assignment"]["rgap_target"]["value"]
    Q = np.load(RES / f"car_demand_{name}.npy")
    flow = _saved_flow(rm, name)
    gap = equilibrium_gap(rm.net, flow, rm.origins, rm.dests, Q)["relative_gap"]
    assert 0 <= gap <= target * 1.001
    # flow conservation: what leaves the zone connectors is the demand
    g = rm.net.graph
    out_of_zones = np.bincount(g.tail, weights=flow, minlength=g.n_nodes)[rm.origins]
    assert out_of_zones == pytest.approx(Q.sum(axis=1), rel=1e-6, abs=1e-3)


def test_saved_demand_is_the_fresh_demand(fresh):
    _, summary = fresh
    for name in SCENARIOS:
        assert summary["assignment"][name]["saved_demand_max_diff_from_fresh_run"] < 1e-3
        assert summary["assignment"][name]["converged"] is True


def test_assignment_from_scratch_approaches_committed_flows(road):
    """Solve the base year again, to the looser reference gap, and compare with the saved (tighter) flows."""
    cfg, rm = road
    ref = cfg["model"]["assignment"]["rgap_reference"]["value"]
    Q = np.load(RES / "car_demand_base_2020.npy")
    r = assign(rm.net, rm.origins, rm.dests, Q, method="bfw", rgap_target=ref, max_iter=500)
    assert r.converged
    n = rm.n_road_links
    saved = _saved_flow(rm, "base_2020")[:n]
    km = rm.links.length_km.values
    assert np.dot(r.flow[:n], km) == pytest.approx(np.dot(saved, km), rel=2e-3)        # vehicle-km
    d = np.abs(r.flow[:n] - saved)
    assert np.mean(d > np.maximum(25.0, 0.05 * saved)) < 0.03
    assert np.corrcoef(r.flow[:n], saved)[0, 1] > 0.9995


@pytest.mark.skipif(os.environ.get("STM_FULL") != "1", reason="set STM_FULL=1 to solve the three assignments again")
def test_full_rerun_reproduces_flows(tmp_path):
    P.run(out=tmp_path, assign_scenarios=True, verbose=False)
    a = pd.read_csv(tmp_path / "link_flows.csv")
    b = pd.read_csv(RES / "link_flows.csv")
    for name in SCENARIOS:
        x, y = a[f"flow_{name}"].values, b[f"flow_{name}"].values
        assert np.dot(x, b.length_km.values) == pytest.approx(np.dot(y, b.length_km.values), rel=1e-4)
        assert np.mean(np.abs(x - y) > np.maximum(10.0, 0.02 * y)) < 0.01, name
