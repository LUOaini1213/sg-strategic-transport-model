"""End-to-end check: re-run the whole model from the committed inputs and compare with the committed results.

The full pipeline (three equilibrium assignments included) takes about a minute, so the test runs it once per
session. Calibration outputs must agree to tight tolerances. Assignment outputs are compared more loosely: two
runs that each stop at a relative gap below 1e-4 can differ slightly when floating-point results differ between
machines, so the test also recomputes the gap of the committed flows independently.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stm import model as M
from stm import pipeline as P
from stm.assignment import equilibrium_gap

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"


@pytest.fixture(scope="session")
def fresh(tmp_path_factory):
    out = tmp_path_factory.mktemp("results")
    summary = P.run(out=out, verbose=False)
    return out, summary


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
    loose = ("assignment.", "road.", "junctions.", "scenario_2030.mode_shares.base_2020.car_trips")
    for k, vo in old.items():
        vn = new[k]
        if isinstance(vo, (int, float)) and not isinstance(vo, bool):
            if "iterations" in k:
                assert abs(vn - vo) <= max(5, 0.25 * vo), k
            elif "relative_gap" in k:
                assert vn <= 1e-4 * 1.01, k
            elif "average_excess_cost" in k:
                assert vn < 0.01, k  # minutes per trip
            elif k.startswith(loose):
                assert vn == pytest.approx(vo, rel=5e-3, abs=0.05), k
            elif k.endswith("max_abs_gradient") or k.endswith("moment_residual"):
                assert abs(vn) < 1e-5, k   # optimiser residuals: only their size matters
            else:
                # calibrated values come out of numerical optimisers; allow for platform differences
                assert vn == pytest.approx(vo, rel=1e-4, abs=1e-6), k
        else:
            assert vn == vo, k


def test_snapshot_calibration_tables_match_committed(fresh):
    out, _ = fresh
    for name in ("calibration_commute_cells.csv", "tld_bus.csv", "bus_pa_pairs_202608.csv", "mode_shares_residence.csv",
                 "mode_shares_workplace.csv", "mode_shares_holdout_cells.csv", "mode_choice_time_profile.csv",
                 "zones_trip_ends.csv"):
        a = pd.read_csv(out / name)
        b = pd.read_csv(RES / name)
        assert list(a.columns) == list(b.columns), name
        assert len(a) == len(b), name
        for c in a.columns:
            if pd.api.types.is_numeric_dtype(b[c]):
                assert np.allclose(a[c].values, b[c].values, rtol=1e-4, atol=1e-4, equal_nan=True), (name, c)
            else:
                assert (a[c].fillna("") == b[c].fillna("")).all(), (name, c)


def test_snapshot_link_flows_close_to_committed(fresh):
    out, _ = fresh
    a = pd.read_csv(out / "link_flows.csv")
    b = pd.read_csv(RES / "link_flows.csv")
    assert len(a) == len(b)
    for n in ("base_2020", "dm_2030", "ds_2030_jrl"):
        d = np.abs(a[f"flow_{n}"].values - b[f"flow_{n}"].values)
        far = d > np.maximum(10.0, 0.02 * b[f"flow_{n}"].values)
        assert far.mean() < 0.01, n


def test_committed_flows_are_user_equilibria():
    """Independent check: one all-or-nothing load at the committed flows' own costs gives a gap <= 1e-4."""
    cfg = M.load_config()
    inp = M.load_inputs()
    z = M.zone_table(inp)
    rm = M.road_model(inp, cfg, z)
    lf = pd.read_csv(RES / "link_flows.csv")
    summary = json.loads((RES / "summary.json").read_text(encoding="utf-8"))
    # rebuild the 2020 car demand with the committed calibration (fast: no re-calibration)
    te = M.trip_ends_2020(inp, cfg, z)
    t_ff, d = M.car_skims(rm, cfg)
    dc = summary["distribution_commute"]
    from stm import gravity as G
    from stm import logit as L

    T = G.gravity(te["O"], te["D"], d, "gamma", dc["a"], dc["b_per_km"])
    g_pt, _, _, _, _ = M.pt_skims(inp, cfg, z, d, with_jrl=False)
    theta = [summary["mode_choice"]["params"][k] for k in L.PARAMS]
    t_car = t_ff + cfg["model"]["mode_choice"]["car_terminal_min"]["value"]
    Pm = L.probabilities(L.utilities(theta, t_car, g_pt, d, z.private_share.values, z.central.values,
                                     M.industrial_share(inp, cfg, len(z))))
    Q = P.car_demand(T, Pm[0], cfg, M.peak_hour_share(inp, cfg, "202607"))
    assert Q.sum() == pytest.approx(summary["assignment"]["base_2020"]["car_trips_per_hour"], rel=1e-6)
    cf = pd.read_csv(RES / "connector_flows.csv")
    g = rm.net.graph
    kc = np.arange(rm.n_road_links, g.n_links)
    assert np.array_equal(cf["tail"].values, g.tail[kc]) and np.array_equal(cf["head"].values, g.head[kc])
    flow = np.concatenate([lf.flow_base_2020.values, cf.flow_base_2020.values])
    gap = equilibrium_gap(rm.net, flow, rm.origins, rm.dests, Q)["relative_gap"]
    assert gap <= 1e-4 * 1.01

