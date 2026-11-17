"""The assignment code against the published Sioux Falls equilibrium (bstabler/TransportationNetworks).

The test network is downloaded, not committed (see DATA_SOURCES.md): run
``python scripts/fetch_data.py --only sioux_falls`` first. Without the files the tests are skipped, unless the
environment variable STM_REQUIRE_SIOUX_FALLS=1 is set (CI sets it), in which case they fail.
"""
import json
import os
from pathlib import Path

import numpy as np
import pytest

from stm import sioux, tntp
from stm.assignment import assign, equilibrium_gap

REPO = Path(__file__).resolve().parents[1]

needs_files = pytest.mark.skipif(not sioux.available() and os.environ.get("STM_REQUIRE_SIOUX_FALLS") != "1",
                                 reason="Sioux Falls files not downloaded (scripts/fetch_data.py --only sioux_falls)")


@pytest.fixture(scope="module")
def check():
    if not sioux.available():
        pytest.fail("Sioux Falls files are required (STM_REQUIRE_SIOUX_FALLS=1) but missing")
    return sioux.verify()


@needs_files
def test_published_flows_are_an_equilibrium_in_this_code(check):
    # the best-known flows must have (almost) zero gap and the published objective under this BPR/Beckmann code
    assert check["published_flows_relative_gap"] < 1e-9
    assert check["published_flows_objective_1e5"] == pytest.approx(sioux.BEST_KNOWN_OBJECTIVE_1E5, rel=1e-12)


@needs_files
def test_bfw_reaches_the_published_solution(check):
    r = check["bfw_1e-06"]
    assert r["converged"] and r["relative_gap"] <= 1e-6
    assert abs(r["objective_rel_diff"]) < 1e-6
    assert r["max_rel_flow_diff"] < 1e-3
    assert r["iterations"] <= 5000   # 970 on Windows, 404 on Linux; plain FW needs far more


@needs_files
def test_bfw_is_faster_than_fw_and_both_converge(check):
    assert check["fw_1e-04"]["converged"] and check["bfw_1e-04"]["converged"]
    assert check["bfw_1e-04"]["iterations"] * 3 < check["fw_1e-04"]["iterations"]
    assert check["fw_1e-04"]["max_rel_flow_diff"] < 1e-2


@needs_files
def test_snapshot_sioux_falls_matches_committed_result(check):
    # The iteration path depends on the last digits of floating-point results, so another machine stops at a
    # slightly different point: objectives agree to within what the gap allows. Iteration counts are not compared
    # (the same run took 970 iterations on Windows and 404 on Linux to reach 1e-6).
    committed = json.loads((REPO / "results" / "sioux_falls_check.json").read_text(encoding="utf-8"))
    for k, rel in (("bfw_1e-04", 2e-4), ("fw_1e-04", 2e-4), ("bfw_1e-06", 2e-6)):
        assert check[k]["objective_1e5"] == pytest.approx(committed[k]["objective_1e5"], rel=rel)
        assert check[k]["converged"]


@needs_files
def test_recomputed_gap_matches_the_algorithm():
    d = sioux.RAW
    net = tntp.network(tntp.read_net(d / "SiouxFalls_net.tntp"))
    od = tntp.read_trips(d / "SiouxFalls_trips.tntp", 24)
    z = np.arange(24)
    r = assign(net, z, z, od, method="bfw", rgap_target=1e-5, max_iter=5000)
    chk = equilibrium_gap(net, r.flow, z, z, od)
    assert r.converged
    assert chk["relative_gap"] <= 1e-5
