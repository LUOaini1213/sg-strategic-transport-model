"""Hand-worked checks of the core formulas. Expected values are worked out by hand in the comments, not taken
from the code's own output."""
import math

import numpy as np
import pytest

from stm import gravity as G
from stm import junction as J
from stm import logit as L
from stm import stats as S
from stm.assignment import (Network, assign, bpr_derivative, bpr_integral, bpr_time, equilibrium_gap, line_search,
                            relative_gap)
from stm.paths import Graph, aon, shortest_path_tree, skim


# ---- gravity --------------------------------------------------------------------------------------------------
def test_furness_symmetric_case():
    # O = D = (100, 100), f = [[1, .5], [.5, 1]]: by symmetry T = 100 f / 1.5
    T, it, err = G.furness([100, 100], [100, 100], np.array([[1.0, 0.5], [0.5, 1.0]]))
    assert T == pytest.approx(np.array([[66.6666667, 33.3333333], [33.3333333, 66.6666667]]), rel=1e-7)


def test_furness_cross_ratio_case():
    # O = (300, 100), D = (200, 200), f = [[1, 1], [1, 4]]. With T11 = x the margins give
    # T = [[x, 300 - x], [200 - x, x - 100]] and the balanced matrix keeps the cross ratio of f:
    # x (x - 100) = 4 (300 - x)(200 - x)  ->  3 x^2 - 1900 x + 240000 = 0  ->  x = (1900 - sqrt(730000)) / 6
    x = (1900 - math.sqrt(730000)) / 6  # 174.266605
    T, _, _ = G.furness([300, 100], [200, 200], np.array([[1.0, 1.0], [1.0, 4.0]]))
    assert T == pytest.approx(np.array([[x, 300 - x], [200 - x, x - 100]]), rel=1e-8)
    assert T[0, 0] == pytest.approx(174.266605, rel=1e-6)


def test_furness_rescales_destinations_to_origin_total():
    T, _, _ = G.furness([10, 30], [1, 1], np.ones((2, 2)))
    assert T.sum(0) == pytest.approx([20, 20])
    assert T.sum(1) == pytest.approx([10, 30])


def test_deterrence_values():
    # gamma: 2^-0.5 * exp(-0.2) = 0.7071068 * 0.8187308 = 0.5789301
    assert G.deterrence(2.0, "gamma", -0.5, 0.1) == pytest.approx(0.5789301, rel=1e-6)
    # exponential: exp(-0.3 * 5) = 0.2231302
    assert G.deterrence(5.0, "exponential", b=0.3) == pytest.approx(0.2231302, rel=1e-6)
    with pytest.raises(ValueError):
        G.deterrence(1.0, "nonsense")


def test_mean_costs_and_tld():
    T = np.array([[1.0, 3.0]])
    c = np.array([[2.0, 4.0]])
    assert G.mean_cost(T, c) == pytest.approx((2 + 12) / 4)          # 3.5
    assert G.mean_log_cost(T, c) == pytest.approx((math.log(2) + 3 * math.log(4)) / 4)
    edges, h = G.tld(T, c, bin_km=1.0, max_km=5.0)
    assert h.tolist() == [0, 0, 1, 0, 3]


def test_coincidence_ratio_hand():
    # min: .25 + .5 + 0 = .75; max: .5 + .5 + .25 = 1.25; CR = 0.6
    assert G.coincidence_ratio([0.5, 0.5, 0.0], [0.25, 0.5, 0.25]) == pytest.approx(0.6)
    assert G.coincidence_ratio([2, 2], [1, 1]) == pytest.approx(1.0)


def _synthetic(seed=7, n=12):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(0, 20, size=(n, 2))
    c = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1)) + 0.5
    O = rng.uniform(50, 150, n)
    D = rng.uniform(50, 150, n)
    return O, D, c


def test_gamma_moment_calibration_recovers_parameters():
    O, D, c = _synthetic()
    Tt = G.gravity(O, D, c, "gamma", -0.7, 0.25)
    a, b, res = G.calibrate_gamma_moments(O, D, c, G.mean_cost(Tt, c), G.mean_log_cost(Tt, c))
    assert (a, b) == pytest.approx((-0.7, 0.25), abs=1e-5)


def test_exponential_mean_calibration_meets_target():
    O, D, c = _synthetic()
    b = G.calibrate_exponential_mean(O, D, c, 6.0)
    assert G.mean_cost(G.gravity(O, D, c, "exponential", b=b), c) == pytest.approx(6.0, rel=1e-6)


def test_aggregate_calibration_recovers_parameters():
    O, D, c = _synthetic(n=20)
    Tt = G.gravity(O, D, c, "gamma", -0.4, 0.15)
    rg = np.arange(20) % 4
    cg = np.arange(20) // 5
    obs = np.zeros((4, 4))
    np.add.at(obs, (rg[:, None].repeat(20, 1), cg[None, :].repeat(20, 0)), Tt)
    a, b, ll, Mg = G.calibrate_gamma_aggregate(O, D, c, rg, cg, obs * 100)
    assert (a, b) == pytest.approx((-0.4, 0.15), abs=2e-3)
    assert Mg.sum() == pytest.approx(O.sum())


# ---- statistics -------------------------------------------------------------------------------------------------
def test_geh_hand():
    # sqrt(2 * 50^2 / 250) = sqrt(20) = 4.4721
    assert S.geh(150.0, 100.0) == pytest.approx(math.sqrt(20))
    assert S.geh(np.array([0.0]), np.array([0.0])).tolist() == [0.0]


def test_r2_and_srmse_hand():
    assert S.r_squared([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    # errors (1, -1): RMSE 1, mean observed 2 -> SRMSE 0.5
    assert S.srmse([2, 2], [1, 3]) == pytest.approx(0.5)
    assert S.share_within([1, 6, 4, 10], 5) == pytest.approx(0.5)


# ---- logit ------------------------------------------------------------------------------------------------------
def test_logit_shares_hand():
    # exp(0) : exp(ln 2) : exp(ln 3) = 1 : 2 : 3
    P = L.probabilities(np.array([0.0, math.log(2), math.log(3)]))
    assert P == pytest.approx([1 / 6, 2 / 6, 3 / 6])
    # adding a constant to every utility changes nothing
    assert L.probabilities(np.array([5.0, 5 + math.log(2), 5 + math.log(3)])) == pytest.approx([1 / 6, 2 / 6, 3 / 6])


def test_utilities_hand():
    theta = [0.5, -1.0, -0.1, 2.0, -0.3, -0.2, 0.4, 1.0]
    t_car = np.array([[10.0]])
    g_pt = np.array([[30.0]])
    dist = np.array([[4.0]])
    V = L.utilities(theta, t_car, g_pt, dist, np.array([0.25]), np.array([1.0]), np.array([0.5]))
    # car: 0.5 - 1.0 + 0.5 - 0.3 + 0.2 = -0.1; pt: -3.0; other: -1.0 - 0.8 + 0.5 = -1.3
    assert V[:, 0, 0] == pytest.approx([-0.1, -3.0, -1.3])


def test_group_shares_by_origin_and_destination():
    T = np.array([[10.0, 30.0], [20.0, 40.0]])
    P = np.stack([np.full((2, 2), 0.25), np.full((2, 2), 0.75)])
    P[0, 0, 1], P[1, 0, 1] = 1.0, 0.0
    # origin zone 0: mode 0 = (10 * .25 + 30 * 1) / 40 = 0.8125
    S0 = L.group_shares(T, P, np.array([0, 1]), 2, axis=0)
    assert S0[0] == pytest.approx([0.8125, 0.1875])
    # destination zone 1: mode 0 = (30 * 1 + 40 * .25) / 70 = 0.5714286
    S1 = L.group_shares(T, P, np.array([0, 1]), 2, axis=1)
    assert S1[1, 0] == pytest.approx(40 / 70)


def test_logit_calibration_recovers_parameters():
    rng = np.random.default_rng(3)
    n = 30
    T = rng.uniform(10, 100, (n, n))
    t_car = rng.uniform(5, 40, (n, n))
    g_pt = t_car * rng.uniform(1.5, 3.5, (n, n))
    dist = t_car / 2
    priv = rng.uniform(0, 0.6, n)
    cen = (rng.uniform(0, 1, n) < 0.2).astype(float)
    ind = rng.uniform(0, 1, n) * (1 - cen)
    true = np.array([-0.5, -1.2, -0.06, 1.5, -0.8, -0.05, 0.3, 1.2])
    P = L.probabilities(L.utilities(true, t_car, g_pt, dist, priv, cen, ind))
    g = np.arange(n) % 10
    h = np.arange(n) // 3
    obs_r = np.stack([np.bincount(g, (P[m] * T).sum(1), 10) for m in range(3)], 1) * 50
    obs_w = np.stack([np.bincount(h, (P[m] * T).sum(0), 10) for m in range(3)], 1) * 50
    theta, ll, res = L.calibrate(T, (t_car, g_pt, dist, priv, cen, ind), obs_r, g, obs_w, h)
    assert res.success
    assert theta == pytest.approx(true, abs=0.03)


# ---- BPR, line search, gap ------------------------------------------------------------------------------------
def test_bpr_hand():
    # t0 = 10, c = 1000: at x = c: 10 * 1.15 = 11.5; at x = 2c: 10 * (1 + .15 * 16) = 34
    assert bpr_time(10.0, 1000.0, 1000.0, 0.15, 4.0) == pytest.approx(11.5)
    assert bpr_time(10.0, 1000.0, 2000.0, 0.15, 4.0) == pytest.approx(34.0)
    # integral 0..1000: 10 * (1000 + .15 * 1000 / 5) = 10300
    assert bpr_integral(10.0, 1000.0, 1000.0, 0.15, 4.0) == pytest.approx(10300.0)
    # derivative at 1000: 10 * .15 * 4 / 1000 = 0.006
    assert bpr_derivative(10.0, 1000.0, 1000.0, 0.15, 4.0) == pytest.approx(0.006)
    # connectors (alpha = 0, infinite capacity) keep their free-flow time
    assert bpr_time(3.0, np.inf, 1e9, 0.0, 1.0) == pytest.approx(3.0)


def _two_links():
    # two parallel links 0 -> 1, linear costs t = t0 (1 + x / 1000): t1 = 10 + 0.01 x, t2 = 15 + 0.015 x
    g = Graph(np.array([0, 0]), np.array([1, 1]), 2)
    return Network(graph=g, t0=np.array([10.0, 15.0]), capacity=np.array([1000.0, 1000.0]), alpha=np.ones(2),
                   beta=np.ones(2))


def test_parallel_links_cannot_share_node_pair_in_aon():
    # the AON keeps one predecessor link per node: with two parallel links it loads only the cheaper one
    net = _two_links()
    y, sptt = aon(net.graph, net.t0, np.array([0]), np.array([1]), np.array([[1500.0]]))
    assert y.tolist() == [1500.0, 0.0]
    assert sptt == pytest.approx(15000.0)


def test_gap_and_line_search_hand():
    net = _two_links()
    x = np.array([1500.0, 0.0])
    # at x: t1 = 25, t2 = 15. TSTT = 1500 * 25 = 37500; SPTT = 1500 * 15 = 22500; gap = 15000 / 22500
    t = net.time(x)
    assert t.tolist() == pytest.approx([25.0, 15.0])
    assert relative_gap(float(x @ t), 22500.0) == pytest.approx(2 / 3)
    # towards y = (0, 1500): g(lam) = 1500 (-10 + 37.5 lam) = 0 at lam = 10 / 37.5
    lam = line_search(net, x, np.array([-1500.0, 1500.0]))
    assert lam == pytest.approx(10 / 37.5, abs=1e-9)
    # which is the equilibrium: x1 = 1100, x2 = 400, both 21
    xe = x + lam * np.array([-1500.0, 1500.0])
    assert xe == pytest.approx([1100.0, 400.0], abs=1e-6)
    assert net.time(xe) == pytest.approx([21.0, 21.0], abs=1e-8)


def _braess_like():
    # 0 -> 1 -> 3 and 0 -> 2 -> 3 with a free middle link 1 -> 2; linear costs
    tail = np.array([0, 0, 1, 2, 1])
    head = np.array([1, 2, 3, 3, 2])
    g = Graph(tail, head, 4)
    t0 = np.array([1.0, 50.0, 50.0, 1.0, 10.0])
    cap = np.array([10.0, 1e9, 1e9, 10.0, 1e9])
    alpha = np.array([1.0, 0.0, 0.0, 1.0, 0.0])
    return Network(graph=g, t0=t0, capacity=cap, alpha=alpha, beta=np.ones(5))


def test_braess_equilibrium_hand():
    # Braess (1968) numbers: t(0->1) = 10 x, t(2->3) = 10 x (t0 = 1 and 1/c * t0 * x ~ x/10 ... see below)
    # Here t(0->1) = 1 + x/10, t(2->3) = 1 + x/10, t(0->2) = t(1->3) = 50, t(1->2) = 10, demand 60.
    # Route costs: A (0-1-3) = 51 + x01/10, B (0-2-3) = 51 + x23/10, C (0-1-2-3) = 12 + (x01 + x23)/10.
    # All 60 on C gives 12 + 12 = 24 < 51 + 6 = 57, so the equilibrium is everything on C: cost 24.
    net = _braess_like()
    r = assign(net, np.array([0]), np.array([3]), np.array([[60.0]]), method="bfw", rgap_target=1e-10)
    assert r.flow == pytest.approx([60, 0, 0, 60, 60], abs=1e-6)
    assert r.sptt == pytest.approx(60 * 24.0)


def test_fw_and_bfw_agree_on_small_network():
    rng = np.random.default_rng(11)
    n = 9
    tail, head = [], []
    for i in range(n):
        for j in range(n):
            if i != j and (abs(i % 3 - j % 3) + abs(i // 3 - j // 3)) == 1:
                tail.append(i)
                head.append(j)
    tail, head = np.array(tail), np.array(head)
    g = Graph(tail, head, n)
    net = Network(graph=g, t0=rng.uniform(1, 3, tail.size), capacity=rng.uniform(50, 150, tail.size),
                  alpha=np.full(tail.size, 0.15), beta=np.full(tail.size, 4.0))
    od = rng.uniform(0, 30, (n, n))
    np.fill_diagonal(od, 0)
    z = np.arange(n)
    a = assign(net, z, z, od, method="fw", rgap_target=1e-7, max_iter=50000)
    b = assign(net, z, z, od, method="bfw", rgap_target=1e-7, max_iter=50000)
    assert a.converged and b.converged
    assert b.iterations < a.iterations
    assert a.flow == pytest.approx(b.flow, rel=2e-3, abs=0.05)
    assert equilibrium_gap(net, b.flow, z, z, od)["relative_gap"] <= 1e-7 * 1.0001


def test_dijkstra_and_skim_against_brute_force():
    rng = np.random.default_rng(5)
    n = 7
    pairs = [(i, j) for i in range(n) for j in range(n) if i != j and rng.uniform() < 0.5]
    tail = np.array([p[0] for p in pairs])
    head = np.array([p[1] for p in pairs])
    cost = rng.uniform(1, 10, len(pairs))
    g = Graph(tail, head, n)
    # Floyd-Warshall by hand loop
    D = np.full((n, n), np.inf)
    np.fill_diagonal(D, 0)
    for (i, j), c in zip(pairs, cost):
        D[i, j] = min(D[i, j], c)
    for k in range(n):
        D = np.minimum(D, D[:, [k]] + D[[k], :])
    c_sk, e_sk = skim(g, cost, np.arange(n), np.arange(n), np.ones(len(pairs)))
    assert np.allclose(np.where(np.isinf(D), -1, D), np.where(np.isinf(c_sk), -1, c_sk))
    dist, pred = shortest_path_tree(g, cost, 0)
    assert np.allclose(np.where(np.isinf(D[0]), -1, D[0]), np.where(np.isinf(dist), -1, dist))
    # the extra attribute (here 1 per link) counts links on the path
    fin = np.isfinite(D)
    assert np.all(e_sk[fin] >= 0)
    assert np.all(e_sk[np.eye(n, dtype=bool)] == 0)


def test_aon_loads_every_trip_along_the_tree():
    # path 0 -> 1 -> 2 (cost 1 + 1) beats 0 -> 2 (cost 5); demand 0->2 = 7, 0->1 = 3
    g = Graph(np.array([0, 1, 0]), np.array([1, 2, 2]), 3)
    y, sptt = aon(g, np.array([1.0, 1.0, 5.0]), np.array([0]), np.array([1, 2]), np.array([[3.0, 7.0]]))
    assert y.tolist() == [10.0, 7.0, 0.0]
    assert sptt == pytest.approx(3 * 1 + 7 * 2)
    with pytest.raises(ValueError):
        aon(g, np.array([1.0, 1.0, 5.0]), np.array([2]), np.array([0]), np.array([[1.0]]))


# ---- junction -----------------------------------------------------------------------------------------------------
def test_webster_cycle_hand():
    # L = 12 s, Y = 0.8: (1.5 * 12 + 5) / 0.2 = 115 s
    assert J.webster_cycle(0.8, 12.0, 60, 150) == pytest.approx(115.0)
    # L = 8, Y = 0.5: 17 / 0.5 = 34 s -> raised to the 60 s minimum
    assert J.webster_cycle(0.5, 8.0, 60, 150) == pytest.approx(60.0)
    assert J.webster_cycle(1.2, 8.0, 60, 150) == pytest.approx(150.0)


def test_webster_delay_hand():
    # C = 60, g = 27 (lam .45), q = 600 veh/h (1/6 per s), X = .8:
    # 60 * .55^2 / (2 (1 - .36)) = 14.1797; .64 / (2 * (1/6) * .2) = 9.6;
    # .65 * (60 / (1/36))^(1/3) * .8^4.25 = .65 * 12.92661 * .387376 = 3.25486  ->  d = 20.5248 s
    assert J.webster_delay(60.0, 27.0, 600.0, 0.8) == pytest.approx(20.5248, abs=2e-3)
    assert math.isnan(J.webster_delay(60.0, 27.0, 600.0, 1.0))


def test_furness_turns_hand():
    T = J.furness_turns(np.array([[0.0, 1.0], [1.0, 0.0]]), [100, 50], [50, 100])
    assert T == pytest.approx(np.array([[0, 100], [50, 0]]))
    T = J.furness_turns(np.ones((2, 2)), [60, 40], [50, 50])
    assert T.sum(1) == pytest.approx([60, 40])
    assert T.sum(0) == pytest.approx([50, 50])


def test_phase_plan_and_signal_check_hand():
    assert J.phase_plan([0, 90, 180, 270]) == [[0, 2], [1, 3]]
    assert J.phase_plan([0, 90, 200]) == [[0, 2], [1]]
    # two phases, ratios .3 (max of .3, .2) and .4 -> Y = .7; L = 8 s; C = (12 + 5) / .3 = 56.7 -> 60 s
    r = J.signal_check([570, 380, 760, 400], [1900, 1900, 1900, 1900], [0, 90, 180, 270], 4.0, 60, 150)
    assert r["Y"] == pytest.approx(0.3 + 0.4)
    assert r["cycle_s"] == pytest.approx(60.0)
    # green of phase 1 = (60 - 8) * .3 / .7 = 22.2857; X of approach 0 = 570 * 60 / (1900 * 22.2857) = 0.8077
    assert r["X"][0] == pytest.approx(570 * 60 / (1900 * 52 * 0.3 / 0.7))
    assert J.bearing_deg(0, 0, 1, 0) == pytest.approx(90.0)
