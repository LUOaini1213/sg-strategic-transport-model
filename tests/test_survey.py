"""Survey design and analysis: hand-worked formulas, properties of the synthetic generator on a small frame, and
checks of the committed (SYNTHETIC) respondent file against the Census margins. No real survey exists."""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stm import model as M
from stm import survey as SV

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"


# ---- sample size ------------------------------------------------------------------------------------------------
def test_sample_size_proportion_hand():
    # 1.96^2 x 0.5 x 0.5 / 0.05^2 = 384.16
    assert SV.sample_size_proportion(0.5, 0.05) == pytest.approx(384.16)
    # design effect 1.5: 576.24
    assert SV.sample_size_proportion(0.5, 0.05, deff=1.5) == pytest.approx(576.24)
    # population of 1000: 384.16 / (1 + 383.16 / 1000) = 277.74
    assert SV.sample_size_proportion(0.5, 0.05, N=1000) == pytest.approx(277.7408, rel=1e-6)
    # p = 0.2, margin 0.02, z = 2: 4 x 0.16 / 0.0004 = 1600
    assert SV.sample_size_proportion(0.2, 0.02, z=2.0) == pytest.approx(1600.0)


def test_sample_size_mean_hand():
    # z = 2, cv = 1, +/- 10%: (2 x 1 / 0.1)^2 = 400; cv = 1.5: 900; with deff 1.63: 652
    assert SV.sample_size_mean(1.0, 0.1, z=2.0) == pytest.approx(400.0)
    assert SV.sample_size_mean(1.5, 0.1, z=2.0) == pytest.approx(900.0)
    assert SV.sample_size_mean(1.0, 0.1, z=2.0, deff=1.63) == pytest.approx(652.0)


def test_margin_is_the_inverse_of_the_sample_size():
    n = SV.sample_size_proportion(0.27, 0.025, deff=1.12)
    assert SV.margin_proportion(0.27, n, deff=1.12) == pytest.approx(0.025)
    # 400 units, p = 0.5: 1.96 x sqrt(0.25 / 400) = 0.049
    assert SV.margin_proportion(0.5, 400) == pytest.approx(0.049)


def test_design_effects_hand():
    assert SV.deff_cluster(3.0, 0.5) == pytest.approx(2.0)        # 1 + 2 x 0.5
    assert SV.deff_cluster(1.0, 0.9) == pytest.approx(1.0)        # one unit per cluster: no clustering
    assert SV.kish_deff([2.0, 2.0, 2.0, 2.0]) == pytest.approx(1.0)
    assert SV.kish_deff([1.0, 3.0]) == pytest.approx(1.25)        # 2 x (1 + 9) / 16


def test_mean_cluster_size_hand():
    # households of 1 or 2 persons, half each. Everyone counts (q = 1): E[m] = 1.5, E[m^2] = 2.5 -> 5/3
    assert SV.mean_cluster_size([0.5, 0.5]) == pytest.approx(5 / 3)
    # each person counts with probability 0.5: E[m] = 0.75; E[m^2] = 0.5 x 0.5 + 0.5 x (0.5 + 1) = 1 -> 4/3
    assert SV.mean_cluster_size([0.5, 0.5], 0.5) == pytest.approx(4 / 3)
    assert SV.mean_cluster_size([1.0]) == pytest.approx(1.0)       # one-person households: no clustering


def test_allocate_largest_remainders():
    assert SV.allocate([50, 30, 20], 10).tolist() == [5, 3, 2]
    # exact shares 3.33 each: one unit left over goes to the first
    assert SV.allocate([1, 1, 1], 10).tolist() == [4, 3, 3]
    # exact 0.7, 2.6, 6.7: floors 0, 2, 6; the two units left go to the two largest remainders (0.7 and 0.7)
    assert SV.allocate([7, 26, 67], 10).tolist() == [1, 2, 7]
    assert SV.allocate([0.2, 0.9, 8.9], 10).tolist() == [0, 1, 9]
    with pytest.raises(ValueError):
        SV.allocate([0, 0], 5)


# ---- raking -----------------------------------------------------------------------------------------------------
def test_rake_two_by_two_hand():
    # one respondent in each cell of a 2 x 2 table; rows must total 60 and 40, columns 70 and 30.
    # Starting from equal weights the fit is the independence table r_i c_j / 100: 42, 18, 28, 12
    w, it, err = SV.rake(np.ones(4), [np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1])],
                         [np.array([60.0, 40.0]), np.array([70.0, 30.0])])
    assert w == pytest.approx([42.0, 18.0, 28.0, 12.0], rel=1e-9)
    assert err < 1e-10


def test_rake_keeps_the_odds_ratio_of_the_starting_weights():
    # starting weights 4, 1, 1, 1 (odds ratio 4); margins rows 50/50, columns 50/50.
    # Fitted table [[a, 50 - a], [50 - a, a]] with a^2 / (50 - a)^2 = 4 -> a = 100 / 3
    w, _, _ = SV.rake(np.array([4.0, 1.0, 1.0, 1.0]), [np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1])],
                      [np.array([50.0, 50.0]), np.array([50.0, 50.0])])
    assert w == pytest.approx([100 / 3, 50 / 3, 50 / 3, 100 / 3], rel=1e-8)


def test_rake_leaves_matching_weights_alone_and_refuses_empty_categories():
    w0 = np.array([10.0, 20.0, 30.0])
    w, it, _ = SV.rake(w0, [np.array([0, 1, 1])], [np.array([10.0, 50.0])])
    assert w == pytest.approx(w0) and it == 1
    with pytest.raises(ValueError):
        SV.rake(np.ones(2), [np.array([0, 0])], [np.array([5.0, 5.0])])


# ---- weighted estimates -----------------------------------------------------------------------------------------
def test_ratio_estimate_simple_random_sample_hand():
    # y = 1, 2, 3, 4, each its own cluster, one stratum, equal weights: mean 2.5, s^2 = 5/3, se = sqrt(s^2 / 4)
    est, se, lo, hi = SV.ratio_estimate([1, 2, 3, 4], np.ones(4), np.ones(4), np.zeros(4), np.arange(4))
    assert est == pytest.approx(2.5)
    assert se == pytest.approx(math.sqrt(5 / 3 / 4))             # 0.645497
    assert (lo, hi) == pytest.approx((2.5 - 1.96 * 0.645497, 2.5 + 1.96 * 0.645497), rel=1e-6)


def test_ratio_estimate_clusters_widen_the_interval():
    # the same four values in two clusters (1, 2) and (3, 4): cluster totals of (y - 2.5) / 4 are -0.5 and +0.5,
    # variance 2 / 1 x (0.25 + 0.25) = 1, se = 1
    est, se, _, _ = SV.ratio_estimate([1, 2, 3, 4], np.ones(4), np.ones(4), np.zeros(4), np.array([0, 0, 1, 1]))
    assert est == pytest.approx(2.5) and se == pytest.approx(1.0)


def test_ratio_estimate_weights_and_strata_hand():
    # stratum 0: y = 0, 1 with weight 3 each; stratum 1: y = 1, 1 with weight 1 each.
    # estimate (0 + 3 + 1 + 1) / 8 = 0.625. Residuals w (y - R) / 8: -0.234375, 0.140625 | 0.046875, 0.046875
    # stratum 0: 2 x 2 x 0.1875^2 = 0.140625 (two deviations of 0.1875 from the stratum mean); stratum 1: 0
    est, se, _, _ = SV.ratio_estimate([0, 1, 1, 1], np.ones(4), [3, 3, 1, 1], [0, 0, 1, 1], np.arange(4))
    assert est == pytest.approx(0.625)
    assert se == pytest.approx(math.sqrt(0.140625))             # 0.375


def test_ratio_estimate_domain_share():
    # share of y among units with x = 1: units (y, x) = (1,1), (0,1), (0,0), (0,0) -> 0.5
    est, se, _, _ = SV.ratio_estimate([1, 0, 0, 0], [1, 1, 0, 0], np.ones(4), np.zeros(4), np.arange(4))
    assert est == pytest.approx(0.5)
    # residuals (y - 0.5 x) / 2 = 0.25, -0.25, 0, 0: variance 4/3 x 0.125 = 1/6
    assert se == pytest.approx(math.sqrt(1 / 6))
    assert math.isnan(SV.ratio_estimate([0, 0], [0, 0], [1, 1], [0, 0], [0, 1])[0])


# ---- the generator on a small frame -----------------------------------------------------------------------------
def _small_frame(car_effect=0.0, other_effects=0.0):
    z = pd.DataFrame({"zone": [1, 2, 3, 4], "region": ["CENTRAL REGION", "CENTRAL REGION", "WEST REGION", "WEST REGION"],
                      "pop_total": [40000.0, 20000.0, 30000.0, 10000.0], "pop_20_64": [28000.0, 12000.0, 18000.0, 7000.0],
                      "private_share": [0.5, 0.0, 0.2, 1.0]})
    O = np.array([14000.0, 9000.0, 9000.0, 3500.0])
    T = np.array([[1.0, 2.0, 1.0, 0.0], [1.0, 1.0, 0.0, 0.0], [3.0, 0.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]])
    T = T / T.sum(1, keepdims=True) * O[:, None]
    pub = np.stack([np.full((4, 4), 0.2), np.full((4, 4), 0.7), np.full((4, 4), 0.1)])
    prv = np.stack([np.full((4, 4), 0.6), np.full((4, 4), 0.3), np.full((4, 4), 0.1)])
    sc = SV.load_config()
    s = sc["synthetic"]
    s["response_per_car_commuter"]["value"] = car_effect
    for k in ("response_private_housing", "response_central_region", "response_no_resident_outside_working_age"):
        s[k]["value"] = other_effects * s[k]["value"]
    fr = SV.Frame(z, ["CENTRAL REGION", "WEST REGION"], O, T, pub, prv, 0.9, sc)
    return fr, sc


def test_truth_by_hand_on_the_small_frame():
    fr, _ = _small_frame()
    t = fr.truth()
    # commuters = O (every O is below the 20-64 population). Car share by zone: 0.2 + 0.4 x private share
    #   zone 1: 0.4, zone 2: 0.2, zone 3: 0.28, zone 4: 0.6
    # Central: (14000 x 0.4 + 9000 x 0.2) / 23000 = 0.321739; West: (9000 x 0.28 + 3500 x 0.6) / 12500 = 0.3696
    assert t["CENTRAL REGION"]["car_share"] == pytest.approx(7400 / 23000)
    assert t["WEST REGION"]["car_share"] == pytest.approx(4620 / 12500)
    assert t["ALL"]["car_share"] == pytest.approx(12020 / 35500)
    assert t["ALL"]["pt_share"] == pytest.approx((35500 * 0.7 - 0.4 * (14000 * 0.5 + 9000 * 0.2 + 3500)) / 35500)
    # trips per resident: 2 x 0.9 x 35500 / 100000 = 0.639
    assert t["ALL"]["trip_rate"] == pytest.approx(0.639)
    assert t["WEST REGION"]["trip_rate"] == pytest.approx(2 * 0.9 * 12500 / 40000)
    # census margins used for raking: private residents 20000 + 0 + 6000 + 10000; aged 20-64: 65000
    assert fr.margin_dwelling == pytest.approx([64000.0, 36000.0])
    assert fr.margin_age == pytest.approx([35000.0, 65000.0])
    assert fr.margin_region == pytest.approx([60000.0, 40000.0])


def test_draw_is_reproducible_and_structured():
    fr, sc = _small_frame()
    a = SV.draw_survey(fr, np.array([300, 200]), sc, 7)
    b = SV.draw_survey(fr, np.array([300, 200]), sc, 7)
    c = SV.draw_survey(fr, np.array([300, 200]), sc, 8)
    assert a.equals(b) and not a.equals(c)
    assert a.household.nunique() == 500
    assert a.groupby("region").household.nunique().tolist() == [300, 200]
    assert (a.groupby("household").size() == a.groupby("household").household_size.first()).all()
    assert set(a["mode"].unique()) <= {-1, 0, 1, 2}
    assert ((a["mode"] >= 0) == (a.commuter == 1)).all()
    assert (a.commuter <= a.working_age).all() and (a.travelled <= a.commuter).all()
    assert (a.trips == 2 * a.travelled).all()
    assert (a.workplace_zone[a.commuter == 1] >= 1).all() and (a.workplace_zone[a.commuter == 0] == 0).all()
    assert a[a.zone == 2].private.sum() == 0 and a[a.zone == 4].private.min() == 1     # private shares 0 and 1
    assert a[(a.zone == 2) & (a.commuter == 1)].workplace_zone.isin([1, 2]).all()      # zone 2 only sends to 1 and 2
    assert a.groupby("household").responded.nunique().max() == 1                        # households respond as a whole


def _replicate_means(fr, sc, n_rep, issued=(1500, 1500)):
    truth = fr.truth()
    out = {m: [] for m in SV.METHODS}
    for r in range(n_rep):
        f = SV.draw_survey(fr, np.array(issued), sc, 100 + r)
        resp = f[f.responded == 1].reset_index(drop=True)
        wd, wr, _, _ = SV.weights(fr, resp, 1e-10)
        e = SV.estimates(fr, resp, wd, wr, 1.96).set_index(["domain", "measure", "method"])
        for m in SV.METHODS:
            out[m].append([e.loc[("ALL", k, m), "estimate"] for k in SV.MEASURES])
    return truth, {m: np.array(x) for m, x in out.items()}


def test_generator_agrees_with_its_truth_when_response_is_unrelated_to_anything():
    # no response effect at all: design-weighted and raked estimates must be unbiased for the stated truth
    fr, sc = _small_frame(car_effect=0.0, other_effects=0.0)
    truth, est = _replicate_means(fr, sc, 40)
    for k, meas in enumerate(SV.MEASURES):
        for m in ("design", "raked"):
            x = est[m][:, k]
            assert abs(x.mean() - truth["ALL"][meas]) < 4 * x.std(ddof=1) / math.sqrt(len(x)), (meas, m)


def test_raking_removes_bias_that_runs_through_the_margins_only():
    # response depends on housing type, region and age composition, not on the mode itself
    fr, sc = _small_frame(car_effect=0.0, other_effects=1.0)
    truth, est = _replicate_means(fr, sc, 40)
    t = truth["ALL"]["car_share"]
    raw, raked = est["unweighted"][:, 0], est["raked"][:, 0]
    assert raw.mean() < t - 0.01                               # private housing under-represented: car share too low
    assert abs(raked.mean() - t) < 0.3 * abs(raw.mean() - t)   # raking removes most of that bias


def test_raking_cannot_remove_bias_that_depends_on_the_answer_itself():
    fr, sc = _small_frame(car_effect=-0.6, other_effects=0.0)
    truth, est = _replicate_means(fr, sc, 40)
    t = truth["ALL"]["car_share"]
    raked = est["raked"][:, 0]
    assert raked.mean() < t - 0.02                              # still clearly too low after raking


def test_design_weights_gross_up_to_the_household_frame():
    fr, sc = _small_frame(other_effects=1.0)
    f = SV.draw_survey(fr, np.array([400, 300]), sc, 3)
    resp = f[f.responded == 1].reset_index(drop=True)
    wd, wr, it, err = SV.weights(fr, resp, 1e-10)
    first = resp.groupby("household").head(1)
    hh = np.bincount(first.region.values, weights=wd[first.index.values], minlength=2)
    assert hh == pytest.approx([60000 / 3.1, 40000 / 3.1])     # households in the frame, by region
    for cat, margin in ((resp.region.values, fr.margin_region), (resp.private.values, fr.margin_dwelling),
                        (resp.working_age.values, fr.margin_age)):
        assert np.bincount(cat, weights=wr, minlength=2) == pytest.approx(margin, rel=1e-8)


def test_design_table_by_hand_on_the_small_frame():
    fr, sc = _small_frame()
    reg, expected = SV.design(fr, np.array([0.3, 0.25]), sc)
    r = reg.set_index("region").loc["WEST REGION"]
    # West: 40,000 residents, 12,500 commuters, so a person is a commuter with q = 0.3125. Household sizes 1-6
    # with probabilities .14 .22 .24 .25 .10 .05: sum p s = 3.1, sum p s^2 = 11.48.
    #   E[m] = 3.1 x 0.3125 = 0.96875; E[m^2] = 3.1 x 0.3125 x 0.6875 + 11.48 x 0.3125^2 = 1.787109
    #   m = 1.844758, design effect 1 + 0.844758 x 0.3 = 1.253427
    # n0 = 1.96^2 x 0.25 x 0.75 / 0.025^2 = 1152.48, with the finite population correction
    # 1152.48 / (1 + 1151.48 / 12500) = 1055.27, x 1.253427 commuters, / 0.96875 commuters per household
    assert r.deff_mode_share == pytest.approx(1.253427, rel=1e-6)
    assert r.commuters_needed == pytest.approx(1.253427 * 1152.48 / (1 + 1151.48 / 12500), rel=1e-6)
    assert r.households_for_mode_share == pytest.approx(1.253427 * 1152.48 / (1 + 1151.48 / 12500) / 0.96875, rel=1e-6)
    # trip rate: q = 0.9 x 0.3125 = 0.28125, cv = sqrt(0.71875 / 0.28125) = 1.598611; persons per household as a
    # sampled person meets them 11.48 / 3.1 = 3.703226, design effect 1 + 2.703226 x 0.3 = 1.810968;
    # n0 = (1.96 x 1.598611 / 0.05)^2 = 3926.97 persons, corrected for 40,000 residents, x 1.810968, / 3.1
    n0 = (1.96 * math.sqrt(0.71875 / 0.28125) / 0.05) ** 2
    assert r.trip_rate_cv == pytest.approx(1.598611, rel=1e-6)
    assert r.deff_trip_rate == pytest.approx(1.810968, rel=1e-6)
    assert r.households_for_trip_rate == pytest.approx(1.810968 * n0 / (1 + (n0 - 1) / 40000) / 3.1, rel=1e-6)
    assert r.completed_households == math.ceil(max(r.households_for_mode_share, r.households_for_trip_rate))
    assert r.issued_households == math.ceil(r.completed_households / 0.55)
    assert r.binding_target == "trip rate"
    # expected households by zone: in proportion to residents within the region
    assert expected[2:] == pytest.approx(r.issued_households * np.array([0.75, 0.25]))
    assert reg.completed_if_proportional.sum() == reg.completed_households.sum()


# ---- the committed synthetic survey -----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def saved():
    return (pd.read_csv(RES / "survey_synthetic_respondents.csv", keep_default_na=False),
            json.loads((RES / "survey.json").read_text(encoding="utf-8")))


def test_saved_file_is_marked_synthetic_and_consistent(saved):
    df, js = saved
    assert js["no_real_survey"] is True
    assert len(df) == js["saved_file"]["persons"]
    assert df.household.nunique() == js["saved_file"]["responding_households"]
    assert int(df.commuter.sum()) == js["saved_file"]["commuters"]
    assert set(df.usual_mode[df.commuter == 1]) <= {"car", "pt", "other"}
    assert (df.usual_mode[df.commuter == 0] == "").all()
    assert set(df.commute_trips_on_survey_day.unique()) <= {0, 2}
    assert list(df.columns[:3]) == ["household", "person", "region"]


def test_saved_raked_weights_reproduce_the_census_margins(saved):
    """Independent of the survey code: the margins are recomputed here from the committed Census inputs."""
    df, _ = saved
    z = M.zone_table(M.load_inputs())
    pop = z.groupby(z.region.str.replace(" REGION", "")).pop_total.sum()
    got = df.groupby("region").raked_weight.sum()
    assert got.reindex(pop.index).values == pytest.approx(pop.values, rel=1e-4)
    private = float((z.condo_other_apartments + z.landed).clip(upper=z.pop_total).sum())
    assert df.raked_weight[df.dwelling == "private"].sum() == pytest.approx(private, rel=1e-4)
    assert df.raked_weight[df.age_group == "20-64"].sum() == pytest.approx(z.pop_20_64.sum(), rel=1e-4)
    assert df.raked_weight.sum() == pytest.approx(z.pop_total.sum(), rel=1e-4)


def test_saved_estimates_can_be_recomputed_from_the_saved_file(saved):
    df, js = saved
    com = df[df.commuter == 1]
    e = js["saved_file"]["estimates_all"]
    assert (com.usual_mode == "car").mean() == pytest.approx(e["car_share"]["unweighted"]["estimate"], rel=1e-9)
    assert np.average(com.usual_mode == "car", weights=com.raked_weight) == pytest.approx(
        e["car_share"]["raked"]["estimate"], rel=1e-4)
    assert np.average(com.usual_mode == "pt", weights=com.design_weight) == pytest.approx(
        e["pt_share"]["design"]["estimate"], rel=1e-4)
    assert np.average(df.commute_trips_on_survey_day, weights=df.raked_weight) == pytest.approx(
        e["trip_rate"]["raked"]["estimate"], rel=1e-4)
    est = pd.read_csv(RES / "survey_estimates.csv")
    west = est[(est.domain == "WEST REGION") & (est.measure == "car_share") & (est.method == "raked")].iloc[0]
    w = com[com.region == "WEST"]
    assert np.average(w.usual_mode == "car", weights=w.raked_weight) == pytest.approx(west.estimate, rel=1e-4)
    assert west.lower < west.estimate < west.upper
    assert SV.kish_deff(df.raked_weight) == pytest.approx(js["saved_file"]["kish_deff_raked_weights"], rel=1e-4)


def test_accuracy_table_is_internally_consistent(saved):
    _, js = saved
    acc = pd.read_csv(RES / "survey_accuracy.csv")
    assert len(acc) == 18 * 3
    assert (acc.mean_estimate - acc.truth).values == pytest.approx(acc.bias.values, abs=1e-6)
    assert (acc.rmse >= acc.bias.abs() - 1e-9).all()
    assert acc.coverage_95.between(0, 1).all()
    h = js["repeated_sampling"]["headline"]
    row = acc[(acc.domain == "ALL") & (acc.measure == "car_share") & (acc.method == "raked")].iloc[0]
    assert row.bias == pytest.approx(h["car_share"]["bias_raked"], rel=1e-5)
    piv = acc.pivot_table(index=["domain", "measure"], columns="method", values="rmse")
    assert int((piv.raked < piv.unweighted).sum()) == js["repeated_sampling"]["cells_raked_rmse_below_unweighted"]


def test_survey_config_is_labelled():
    sc = SV.load_config()
    for sec, items in sc.items():
        if sec.startswith("_"):
            continue
        for name, e in items.items():
            assert e["label"] in {"REAL", "ASSUMPTION", "SYNTHETIC"}, name
    assert all(e["label"] == "SYNTHETIC" for e in sc["synthetic"].values())
    dist = sc["design"]["household_size_distribution"]["value"]
    assert sum(dist) == pytest.approx(1.0)
    assert np.dot(dist, np.arange(1, 7)) == pytest.approx(sc["design"]["persons_per_household"]["value"])
