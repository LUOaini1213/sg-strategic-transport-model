"""Design of a household travel survey over the model's zones, and its analysis on SYNTHETIC respondents.

No survey was carried out. The module does four things:

  1. sample sizes for the car share of commuters and for the commuting trip rate in each region, with a design
     effect for the clustering of people in households and an allowance for non-response;
  2. a stratified sampling plan: regions as strata, each region's sample spread over its subzones;
  3. synthetic respondents drawn from the model's own population and trip tables, with a non-response
     mechanism that depends on housing type, region, household composition and, on purpose, on the answer itself
     (households with car commuters respond less);
  4. weighting by raking to Census 2020 margins (region, dwelling type, age group), weighted estimates with
     confidence intervals, and a repeated-sampling check of how close each estimator comes to the known truth.

Because the respondents are simulated, the truth is known exactly: it is the expected value of the process that
generates them.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
MODES = ("car", "pt", "other")
MEASURES = ("car_share", "pt_share", "trip_rate")
METHODS = ("unweighted", "design", "raked")


def load_config(repo: Path = REPO) -> dict:
    return json.loads((repo / "config" / "survey.json").read_text(encoding="utf-8"))


def v(entry):
    return entry["value"]


# ---------------------------------------------------------------------------------------------------------------
# 1. sample size
# ---------------------------------------------------------------------------------------------------------------
def deff_cluster(m: float, rho: float) -> float:
    """Design effect of clusters of m units with intra-cluster correlation rho: 1 + (m - 1) rho."""
    return 1.0 + (m - 1.0) * rho


def mean_cluster_size(size_distribution, q: float = 1.0) -> float:
    """Cluster size as a sampled unit meets it, E[m^2] / E[m], when a household of s persons (probabilities
    ``size_distribution`` for s = 1, 2, ...) holds m ~ Binomial(s, q) units of interest. This, not the plain
    mean E[m], is the m of the design effect 1 + (m - 1) rho when clusters differ in size."""
    p = np.asarray(size_distribution, dtype=float)
    s = np.arange(1, p.size + 1)
    e1 = float(np.sum(p * s * q))
    e2 = float(np.sum(p * (s * q * (1.0 - q) + (s * q) ** 2)))
    return e2 / e1


def kish_deff(w) -> float:
    """Design effect of unequal weights (Kish): n sum(w^2) / (sum w)^2."""
    w = np.asarray(w, dtype=float)
    return float(w.size * np.sum(w ** 2) / np.sum(w) ** 2)


def fpc_adjust(n0: float, N: float | None) -> float:
    """Finite population correction: n = n0 / (1 + (n0 - 1) / N)."""
    return n0 if N is None else n0 / (1.0 + (n0 - 1.0) / N)


def sample_size_proportion(p: float, margin: float, z: float = 1.96, deff: float = 1.0, N: float | None = None) -> float:
    """Units needed to estimate a proportion p within +/- margin: deff x z^2 p (1 - p) / margin^2, with the
    finite population correction applied to the simple-random-sample size."""
    return deff * fpc_adjust(z ** 2 * p * (1.0 - p) / margin ** 2, N)


def sample_size_mean(cv: float, rel_margin: float, z: float = 1.96, deff: float = 1.0, N: float | None = None) -> float:
    """Units needed to estimate a mean within +/- rel_margin of itself, for a coefficient of variation cv."""
    return deff * fpc_adjust((z * cv / rel_margin) ** 2, N)


def margin_proportion(p: float, n: float, z: float = 1.96, deff: float = 1.0) -> float:
    """Half-width of the confidence interval of a proportion from n units."""
    return z * math.sqrt(deff * p * (1.0 - p) / n)


def allocate(weights, total: int) -> np.ndarray:
    """Whole numbers that sum to ``total`` in proportion to ``weights`` (largest remainders)."""
    w = np.asarray(weights, dtype=float)
    if total < 0 or w.sum() <= 0:
        raise ValueError("nothing to allocate")
    exact = w / w.sum() * total
    n = np.floor(exact).astype(int)
    short = int(total - n.sum())
    if short:
        order = np.argsort(-(exact - n), kind="stable")
        n[order[:short]] += 1
    return n


# ---------------------------------------------------------------------------------------------------------------
# 4. weighting and estimation
# ---------------------------------------------------------------------------------------------------------------
def rake(w0, categories, margins, tol: float = 1e-10, max_iter: int = 500):
    """Iterative proportional fitting of weights to several margins.

    ``categories`` is a list of integer arrays (one per dimension, category of each unit); ``margins`` the
    matching list of population totals per category. Returns (weights, iterations, largest relative error)."""
    w = np.asarray(w0, dtype=float).copy()
    cats = [np.asarray(c, dtype=int) for c in categories]
    tgts = [np.asarray(m, dtype=float) for m in margins]
    for c, t in zip(cats, tgts):
        present = np.bincount(c, weights=w, minlength=t.size) > 0
        if np.any(~present & (t > 0)):
            raise ValueError("a category with a population total has no respondent")
    err = np.inf
    for it in range(1, max_iter + 1):
        for c, t in zip(cats, tgts):
            cur = np.bincount(c, weights=w, minlength=t.size)
            w *= np.divide(t, cur, out=np.ones_like(t), where=cur > 0)[c]
        err = max(float(np.max(np.abs(np.bincount(c, weights=w, minlength=t.size) - t) / np.maximum(t, 1e-300)))
                  for c, t in zip(cats, tgts))
        if err < tol:
            break
    return w, it, err


def ratio_estimate(y, x, w, strata, clusters, z: float = 1.96):
    """Weighted ratio sum(w y) / sum(w x) with a linearised standard error for a stratified sample of clusters.

    Residuals e = (y - R x) / sum(w x) are totalled by cluster, and the variance is
    sum over strata of n_h / (n_h - 1) x sum over clusters of (total - stratum mean of totals)^2.
    Returns (estimate, standard error, lower, upper)."""
    y, x, w = (np.asarray(a, dtype=float) for a in (y, x, w))
    X = float(np.sum(w * x))
    if X <= 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    R = float(np.sum(w * y) / X)
    e = w * (y - R * x) / X
    cl, cidx = np.unique(np.asarray(clusters), return_inverse=True)
    tot = np.bincount(cidx, weights=e, minlength=cl.size)
    st = np.zeros(cl.size, dtype=int)
    st[cidx] = np.asarray(strata, dtype=int)
    var = 0.0
    for h in np.unique(st):
        t = tot[st == h]
        if t.size > 1:
            var += t.size / (t.size - 1.0) * float(np.sum((t - t.mean()) ** 2))
    se = math.sqrt(var)
    return R, se, R - z * se, R + z * se


# ---------------------------------------------------------------------------------------------------------------
# 3. the synthetic population and its respondents
# ---------------------------------------------------------------------------------------------------------------
class Frame:
    """What the generator needs to know about zones, and the truth it implies."""

    def __init__(self, z: pd.DataFrame, regions, O, T, P_public, P_private, attendance: float, sc: dict):
        self.nz = len(z)
        self.regions = list(regions)
        self.region = z.region.map({r: k for k, r in enumerate(self.regions)}).values.astype(int)
        self.pop = z.pop_total.values.astype(float)
        self.working = np.divide(z.pop_20_64.values, self.pop, out=np.zeros(self.nz), where=self.pop > 0)
        self.private = np.clip(z.private_share.values.astype(float), 0.0, 1.0)
        pw = z.pop_20_64.values.astype(float)
        self.commuter = np.clip(np.divide(O, pw, out=np.zeros(self.nz), where=pw > 0), 0.0, 1.0)
        self.attendance = float(attendance)
        self.households = self.pop / v(sc["design"]["persons_per_household"])
        rows = T.sum(axis=1, keepdims=True)
        self.dest = np.divide(T, rows, out=np.zeros_like(T), where=rows > 0)
        self.dest_cdf = np.cumsum(self.dest, axis=1)
        self.P = (np.asarray(P_public, dtype=float), np.asarray(P_private, dtype=float))   # [dwelling][mode, i, j]
        self.central = self.regions.index("CENTRAL REGION") if "CENTRAL REGION" in self.regions else -1
        # census margins used for raking
        nr = len(self.regions)
        self.margin_region = np.bincount(self.region, weights=self.pop, minlength=nr)
        priv_pop = float(np.sum(self.pop * self.private))
        self.margin_dwelling = np.array([self.pop.sum() - priv_pop, priv_pop])
        work_pop = float(np.sum(self.pop * self.working))
        self.margin_age = np.array([self.pop.sum() - work_pop, work_pop])

    def truth(self) -> dict:
        """Expected values of the generating process: mode shares of commuters and commuting trips per resident
        per weekday, for the whole island and by region."""
        com = self.pop * self.working * self.commuter
        share = np.zeros((self.nz, 3))
        for m in range(3):
            share[:, m] = ((1.0 - self.private) * (self.dest * self.P[0][m]).sum(axis=1)
                           + self.private * (self.dest * self.P[1][m]).sum(axis=1))
        out = {}
        for name, mask in [("ALL", np.ones(self.nz, dtype=bool))] + [(r, self.region == k)
                                                                    for k, r in enumerate(self.regions)]:
            c = com[mask]
            out[name] = {"car_share": float(np.sum(c * share[mask, 0]) / c.sum()),
                         "pt_share": float(np.sum(c * share[mask, 1]) / c.sum()),
                         "trip_rate": float(2.0 * self.attendance * c.sum() / self.pop[mask].sum()),
                         "commuters": float(c.sum()), "residents": float(self.pop[mask].sum())}
        return out


def draw_survey(fr: Frame, issued_by_region: np.ndarray, sc: dict, seed: int) -> pd.DataFrame:
    """One synthetic survey: every person of every issued household, with the household's response flag.
    Within a region every household has the same chance of selection, so the number issued in a zone is random."""
    s = sc["synthetic"]
    rng = np.random.default_rng(seed)
    per_zone = np.zeros(fr.nz, dtype=np.int64)
    for k, n_k in enumerate(issued_by_region):
        m = fr.region == k
        per_zone[m] = rng.multinomial(int(n_k), fr.households[m] / fr.households[m].sum())
    hz = np.repeat(np.arange(fr.nz), per_zone)
    H = hz.size
    dist = np.asarray(v(sc["design"]["household_size_distribution"]), dtype=float)
    size = rng.choice(dist.size, size=H, p=dist) + 1
    private = rng.random(H) < fr.private[hz]
    u_house = rng.random(H)
    hid = np.repeat(np.arange(H), size)
    pz = hz[hid]
    n = hid.size
    working = rng.random(n) < fr.working[pz]
    commuter = working & (rng.random(n) < fr.commuter[pz])
    travelled = commuter & (rng.random(n) < fr.attendance)
    u_dest = rng.random(n)
    u_own = rng.random(n)
    copy = rng.random(n) < v(s["mode_copy_probability"])
    u_resp = rng.random(H)
    idx = np.where(commuter)[0]
    dest = np.full(n, -1)
    dest[idx] = np.minimum((fr.dest_cdf[pz[idx]] < u_dest[idx, None]).sum(axis=1), fr.nz - 1)
    um = np.where(copy, u_house[hid], u_own)[idx]
    pr = private[hid][idx]
    p_car = np.where(pr, fr.P[1][0][pz[idx], dest[idx]], fr.P[0][0][pz[idx], dest[idx]])
    p_pt = np.where(pr, fr.P[1][1][pz[idx], dest[idx]], fr.P[0][1][pz[idx], dest[idx]])
    mode = np.full(n, -1)
    mode[idx] = np.where(um < p_car, 0, np.where(um < p_car + p_pt, 1, 2))
    car_commuters = np.bincount(hid, weights=(mode == 0).astype(float), minlength=H)
    all_working = np.bincount(hid, weights=working.astype(float), minlength=H) == size
    logit = (v(s["response_intercept"]) + v(s["response_private_housing"]) * private
             + v(s["response_central_region"]) * (fr.region[hz] == fr.central)
             + v(s["response_no_resident_outside_working_age"]) * all_working
             + v(s["response_per_car_commuter"]) * car_commuters)
    responded = u_resp < 1.0 / (1.0 + np.exp(-logit))
    return pd.DataFrame({"household": hid, "zone": pz + 1, "region": fr.region[pz], "private": private[hid].astype(int),
                         "household_size": size[hid], "working_age": working.astype(int),
                         "commuter": commuter.astype(int), "travelled": travelled.astype(int),
                         "trips": 2 * travelled.astype(int), "mode": mode, "workplace_zone": dest + 1,
                         "responded": responded[hid].astype(int)})


def weights(fr: Frame, resp: pd.DataFrame, tol: float):
    """Design weights (households in the frame / responding households, by region) and raked weights."""
    nr = len(fr.regions)
    hh_frame = np.bincount(fr.region, weights=fr.households, minlength=nr)
    hh_resp = resp.groupby("region").household.nunique().reindex(range(nr), fill_value=0).values.astype(float)
    base = (hh_frame / np.maximum(hh_resp, 1.0))[resp.region.values]
    raked, it, err = rake(base, [resp.region.values, resp.private.values, resp.working_age.values],
                          [fr.margin_region, fr.margin_dwelling, fr.margin_age], tol=tol)
    return base, raked, it, err


def estimates(fr: Frame, resp: pd.DataFrame, w_design: np.ndarray, w_raked: np.ndarray, z: float) -> pd.DataFrame:
    """Every measure, domain and method for one respondent file."""
    ones = np.ones(len(resp))
    com = resp.commuter.values.astype(float)
    ys = {"car_share": ((resp["mode"].values == 0).astype(float), com),
          "pt_share": ((resp["mode"].values == 1).astype(float), com),
          "trip_rate": (resp.trips.values.astype(float), ones)}
    ws = {"unweighted": ones, "design": w_design, "raked": w_raked}
    rows = []
    for d, name in [(-1, "ALL")] + list(enumerate(fr.regions)):
        ind = ones if d < 0 else (resp.region.values == d).astype(float)
        for meas, (y, x) in ys.items():
            for meth, w in ws.items():
                est, se, lo, hi = ratio_estimate(y * ind, x * ind, w, resp.region.values, resp.household.values, z)
                rows.append((name, meas, meth, est, se, lo, hi))
    return pd.DataFrame(rows, columns=["domain", "measure", "method", "estimate", "se", "lower", "upper"])


# ---------------------------------------------------------------------------------------------------------------
# 1-2. design
# ---------------------------------------------------------------------------------------------------------------
def design(fr: Frame, census_car_share: np.ndarray, sc: dict):
    """Sample size by region and the plan by zone. ``census_car_share`` is the Census 2020 car share of
    commuters by region, the planning value of the proportion."""
    d = sc["design"]
    zc, rho, pph = v(d["confidence_z"]), v(d["intra_household_correlation"]), v(d["persons_per_household"])
    rr = v(d["expected_response_rate"])
    dist = v(d["household_size_distribution"])
    nr = len(fr.regions)
    pop = fr.margin_region
    com = np.bincount(fr.region, weights=fr.pop * fr.working * fr.commuter, minlength=nr)
    rows = []
    for k, r in enumerate(fr.regions):
        m_com = mean_cluster_size(dist, com[k] / pop[k])    # commuters in the household of a sampled commuter
        deff_mode = deff_cluster(m_com, rho)
        n_com = sample_size_proportion(census_car_share[k], v(d["target_margin_mode_share"]), zc, deff_mode, com[k])
        hh_mode = n_com / (pph * com[k] / pop[k])
        q = fr.attendance * com[k] / pop[k]                  # share of residents commuting on the survey day
        cv = math.sqrt((1.0 - q) / q)
        deff_trip = deff_cluster(mean_cluster_size(dist), rho)
        n_per = sample_size_mean(cv, v(d["target_relative_margin_trip_rate"]), zc, deff_trip, pop[k])
        hh_trip = n_per / pph
        complete = int(math.ceil(max(hh_mode, hh_trip)))
        rows.append({"region": r, "residents": pop[k], "households_frame": pop[k] / pph, "commuters": com[k],
                     "census_car_share": census_car_share[k], "commuters_per_household": pph * com[k] / pop[k],
                     "deff_mode_share": deff_mode, "commuters_needed": n_com, "households_for_mode_share": hh_mode,
                     "trip_rate_cv": cv, "deff_trip_rate": deff_trip, "persons_needed": n_per,
                     "households_for_trip_rate": hh_trip, "completed_households": complete,
                     "issued_households": int(math.ceil(complete / rr)),
                     "binding_target": "mode share" if hh_mode >= hh_trip else "trip rate"})
    reg = pd.DataFrame(rows)
    total = int(reg.completed_households.sum())
    prop = allocate(reg.households_frame.values, total)
    reg["completed_if_proportional"] = prop
    reg["margin_mode_share_if_proportional"] = [
        margin_proportion(p, n * cph, zc, de) for p, n, cph, de in
        zip(reg.census_car_share, prop, reg.commuters_per_household, reg.deff_mode_share)]
    reg["sampling_fraction"] = reg.issued_households / reg.households_frame
    expected = np.zeros(fr.nz)
    for k in range(nr):
        m = fr.region == k
        expected[m] = reg.issued_households[k] * fr.households[m] / fr.households[m].sum()
    return reg, expected


# ---------------------------------------------------------------------------------------------------------------
def run(out: Path, *, z: pd.DataFrame, regions, O: np.ndarray, T: np.ndarray, P_public: np.ndarray,
        P_private: np.ndarray, attendance: float, census_car_share: np.ndarray, write_json, write_csv,
        sc: dict | None = None, replicates: int | None = None) -> dict:
    sc = load_config() if sc is None else sc
    fr = Frame(z, regions, O, T, P_public, P_private, attendance, sc)
    zc = v(sc["design"]["confidence_z"])
    tol = v(sc["weighting"]["raking_tolerance"])
    seed = int(v(sc["synthetic"]["seed"]))
    R = int(v(sc["synthetic"]["replicates"])) if replicates is None else int(replicates)
    reg, expected = design(fr, np.asarray(census_car_share, dtype=float), sc)
    write_csv(out / "survey_sample_size.csv", reg)
    plan = pd.DataFrame({"zone": z.zone.values, "subzone": z.subzone.values, "planning_area": z.planning_area.values,
                         "region": z.region.values, "households_frame": fr.households, "expected_issued_households": expected,
                         "expected_completed_households": expected * v(sc["design"]["expected_response_rate"])})
    write_csv(out / "survey_sampling_plan.csv", plan)
    truth = fr.truth()
    issued_reg = reg.issued_households.values.astype(np.int64)

    # ---- the saved synthetic survey ------------------------------------------------------------------------------
    full = draw_survey(fr, issued_reg, sc, seed)
    resp = full[full.responded == 1].reset_index(drop=True)
    w_d, w_r, it, err = weights(fr, resp, tol)
    est = estimates(fr, resp, w_d, w_r, zc)
    est["truth"] = [truth[d][m] for d, m in zip(est.domain, est.measure)]
    est["truth_inside_interval"] = ((est.lower <= est.truth) & (est.truth <= est.upper)).astype(int)
    write_csv(out / "survey_estimates.csv", est)
    saved = pd.DataFrame({
        "household": resp.household.values + 1, "person": resp.groupby("household").cumcount().values + 1,
        "region": np.asarray([r_.replace(" REGION", "") for r_ in fr.regions])[resp.region.values],
        "zone": resp.zone.values, "dwelling": np.where(resp.private.values == 1, "private", "public"),
        "household_size": resp.household_size.values, "age_group": np.where(resp.working_age.values == 1, "20-64", "other"),
        "commuter": resp.commuter.values, "usual_mode": np.where(resp["mode"].values >= 0,
                                                                 np.asarray(MODES)[np.clip(resp["mode"].values, 0, 2)], ""),
        "workplace_zone": np.where(resp.workplace_zone.values > 0, resp.workplace_zone.values, 0),
        "commute_trips_on_survey_day": resp.trips.values, "design_weight": w_d, "raked_weight": w_r})
    write_csv(out / "survey_synthetic_respondents.csv", saved, sig=6)
    hh_issued = int(issued_reg.sum())
    hh_resp = int(resp.household.nunique())
    com_resp = resp[resp.commuter == 1]

    # ---- repeated sampling: bias, RMSE, coverage ------------------------------------------------------------------
    acc = {}
    resp_rates = []
    for r in range(R):
        f_ = full if r == 0 else draw_survey(fr, issued_reg, sc, seed + r)
        rs = resp if r == 0 else f_[f_.responded == 1].reset_index(drop=True)
        a, b, _, _ = (w_d, w_r, 0, 0) if r == 0 else weights(fr, rs, tol)
        e = est if r == 0 else estimates(fr, rs, a, b, zc)
        resp_rates.append(rs.household.nunique() / hh_issued)
        for row in e.itertuples():
            acc.setdefault((row.domain, row.measure, row.method), []).append((row.estimate, row.lower, row.upper))
    rows = []
    for (dom, meas, meth), vals in acc.items():
        a = np.asarray(vals)
        t = truth[dom][meas]
        rows.append({"domain": dom, "measure": meas, "method": meth, "truth": t, "mean_estimate": float(a[:, 0].mean()),
                     "bias": float(a[:, 0].mean() - t), "rmse": float(np.sqrt(np.mean((a[:, 0] - t) ** 2))),
                     "coverage_95": float(np.mean((a[:, 1] <= t) & (t <= a[:, 2]))),
                     "mean_half_width": float(np.mean(a[:, 2] - a[:, 1]) / 2.0)})
    accd = pd.DataFrame(rows)
    write_csv(out / "survey_accuracy.csv", accd)
    piv = accd.pivot_table(index=["domain", "measure"], columns="method", values="rmse")
    better = piv.raked < piv.unweighted
    worse = [f"{m} / {d}" for (d, m), ok in better.items() if not ok]
    bias = accd.pivot_table(index=["domain", "measure"], columns="method", values="bias")
    cov = accd.pivot_table(index=["domain", "measure"], columns="method", values="coverage_95")
    hw = accd.pivot_table(index=["domain", "measure"], columns="method", values="mean_half_width")
    regs = list(fr.regions)

    def head(meas):
        k = ("ALL", meas)
        return {"truth": truth["ALL"][meas],
                **{f"bias_{m}": float(bias.loc[k, m]) for m in METHODS},
                **{f"rmse_{m}": float(piv.loc[k, m]) for m in METHODS},
                **{f"coverage_{m}": float(cov.loc[k, m]) for m in METHODS},
                "bias_removed_by_raking": float(1.0 - abs(bias.loc[k, "raked"]) / abs(bias.loc[k, "unweighted"]))}

    one = est.set_index(["domain", "measure", "method"])
    res = {
        "no_real_survey": True,
        "design": {
            "completed_households": int(reg.completed_households.sum()), "issued_households": hh_issued,
            "expected_response_rate": v(sc["design"]["expected_response_rate"]),
            "binding_targets": sorted(set(reg.binding_target)),
            "largest_region_sample": reg.loc[reg.completed_households.idxmax(), "region"],
            "completed_min": int(reg.completed_households.min()), "completed_max": int(reg.completed_households.max()),
            "sampling_fraction_min": float(reg.sampling_fraction.min()),
            "sampling_fraction_max": float(reg.sampling_fraction.max()),
            "worst_margin_if_proportional": float(reg.margin_mode_share_if_proportional.max()),
            "worst_margin_region_if_proportional": reg.loc[reg.margin_mode_share_if_proportional.idxmax(), "region"],
            "zones_with_residents": int((fr.pop > 0).sum()),
            "zones_expecting_under_one_household": int(((expected < 1.0) & (fr.pop > 0)).sum()),
            "zones_in_saved_file": int(resp.zone.nunique())},
        "saved_file": {
            "seed": seed, "responding_households": hh_resp, "response_rate": hh_resp / hh_issued,
            "persons": int(len(resp)), "commuters": int(len(com_resp)),
            "raking_iterations": int(it), "raking_max_relative_error": float(err),
            "kish_deff_design_weights": kish_deff(w_d), "kish_deff_raked_weights": kish_deff(w_r),
            "raked_weight_min": float(w_r.min()), "raked_weight_max": float(w_r.max()),
            "unweighted_private_share": float(resp.private.mean()),
            "census_private_share": float(fr.margin_dwelling[1] / fr.margin_dwelling.sum()),
            "unweighted_working_age_share": float(resp.working_age.mean()),
            "census_working_age_share": float(fr.margin_age[1] / fr.margin_age.sum()),
            "estimates_all": {meas: {meth: {"estimate": float(one.loc[("ALL", meas, meth), "estimate"]),
                                            "lower": float(one.loc[("ALL", meas, meth), "lower"]),
                                            "upper": float(one.loc[("ALL", meas, meth), "upper"])} for meth in METHODS}
                              for meas in MEASURES},
            "intervals_containing_truth_raked": int(est[est.method == "raked"].truth_inside_interval.sum()),
            "intervals_raked": int((est.method == "raked").sum())},
        "repeated_sampling": {
            "replicates": R, "mean_response_rate": float(np.mean(resp_rates)),
            "cells": int(len(piv)), "cells_raked_rmse_below_unweighted": int(better.sum()),
            "cells_raked_rmse_not_below_unweighted": worse,
            "cells_raked_rmse_below_design": int((piv.raked < piv.design).sum()),
            "headline": {meas: head(meas) for meas in MEASURES},
            "regions_car_share_bias_raked": {r_: float(bias.loc[(r_, "car_share"), "raked"]) for r_ in regs},
            "raked_coverage_min": float(cov.raked.min()), "raked_coverage_max": float(cov.raked.max()),
            "achieved_margin_car_share_by_region_raked": {r_: float(hw.loc[(r_, "car_share"), "raked"]) for r_ in regs},
            "achieved_relative_margin_trip_rate_by_region_raked": {
                r_: float(hw.loc[(r_, "trip_rate"), "raked"] / truth[r_]["trip_rate"]) for r_ in regs},
            "regions_meeting_trip_rate_margin": int(sum(
                hw.loc[(r_, "trip_rate"), "raked"] / truth[r_]["trip_rate"]
                <= v(sc["design"]["target_relative_margin_trip_rate"]) for r_ in regs)),
            "regions_meeting_mode_share_margin": int(sum(hw.loc[(r_, "car_share"), "raked"]
                                                         <= v(sc["design"]["target_margin_mode_share"]) for r_ in regs))}}
    write_json(out / "survey.json", res)
    return res
