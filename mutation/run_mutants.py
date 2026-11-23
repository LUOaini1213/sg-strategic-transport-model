"""Mutation test of the test suite.

Each mutant is one deliberate bug: a single exact-string replacement in the core logic. For every mutant the files
the tests need are copied to a scratch directory, the bug is applied, and the pytest suite runs there. A mutant is
*killed* when the suite fails. The unmodified suite runs first and must pass.

The snapshot tests (names start with test_snapshot_) compare a fresh run with the committed results and README,
so they fail on almost any change. To show that the hand-worked and property tests catch the bugs on their own,
every mutant is also scored with the snapshot tests switched off ("killed without snapshot").

    python mutation/run_mutants.py [--workers 3]

Writes results/mutation_report.json; run scripts/run_all.py afterwards so README.md shows the result.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COPY = ["stm", "tests", "config", "data/inputs", "data/raw/sioux_falls", "results", "docs", "README.md", "pytest.ini"]

# (id, file, original snippet, mutated snippet, what the bug means)
MUTANTS = [
    ("M01", "stm/gravity.py", "A = np.divide(1.0, s, out=np.zeros_like(s), where=s > 0)",
     "A = np.divide(1.0, np.sqrt(s), out=np.zeros_like(s), where=s > 0)", "Furness: wrong row balancing factor"),
    ("M02", "stm/gravity.py", "T = (A * O)[:, None] * f * (B * D)[None, :]", "T = (A * O)[:, None] * f * B[None, :]",
     "Furness: destination totals left out of the matrix"),
    ("M03", "stm/gravity.py", "return np.power(c, a) * np.exp(-b * c)", "return np.power(c, -a) * np.exp(-b * c)",
     "gamma deterrence: sign of the power term flipped"),
    ("M04", "stm/gravity.py", "return float((T * np.log(c)).sum() / T.sum())", "return float((T * c).sum() / T.sum())",
     "mean log cost computed as mean cost"),
    ("M05", "stm/gravity.py", "return float(np.minimum(p, q).sum() / np.maximum(p, q).sum())",
     "return float(np.minimum(p, q).sum())", "coincidence ratio without the denominator"),
    ("M06", "stm/gravity.py", "return [mean_cost(T, c) / target_mean - 1.0, mean_log_cost(T, c) - target_mean_log]",
     "return [mean_cost(T, c) / target_mean - 1.0, 0.0]", "gamma calibration ignores the log-cost condition"),
    ("M07", "stm/stats.py", "np.divide(2.0 * (m - c) ** 2, s,", "np.divide((m - c) ** 2, s,", "GEH without the factor 2"),
    ("M08", "stm/stats.py", "return float(np.sqrt(np.mean((m - c) ** 2)) / np.mean(c))",
     "return float(np.sqrt(np.mean((m - c) ** 2)) / np.mean(m))", "SRMSE standardised by the modelled mean"),
    ("M09", "stm/logit.py", "return e / e.sum(axis=0, keepdims=True)", "return e / e.sum()",
     "logit probabilities normalised over all pairs instead of over modes"),
    ("M10", "stm/logit.py", "v_car = (asc_car + b_time * t_car + b_priv * private[:, None] + b_central * central[None, :]",
     "v_car = (asc_car + b_time * t_car + b_priv * private[None, :] + b_central * central[None, :]",
     "private-housing share taken at the destination instead of the origin"),
    ("M11", "stm/logit.py", "flows = (P * T[None, :, :]).sum(axis=2 - axis)", "flows = (P * T[None, :, :]).sum(axis=1 + axis)",
     "mode shares grouped by the wrong trip end"),
    ("M12", "stm/assignment.py", "return t0 * (1.0 + alpha * r ** beta)", "return t0 * (1.0 + alpha * r ** (beta - 1.0))",
     "BPR: power beta - 1 instead of beta"),
    ("M13", "stm/assignment.py", "extra = np.where(alpha > 0, alpha * cap / (beta + 1.0) * r ** (beta + 1.0), 0.0)",
     "extra = np.where(alpha > 0, alpha * cap / beta * r ** (beta + 1.0), 0.0)", "Beckmann integral: divided by beta"),
    ("M14", "stm/assignment.py", "out = np.where(alpha > 0, t0 * alpha * beta / cap * r ** (beta - 1.0), 0.0)",
     "out = np.where(alpha > 0, t0 * alpha / cap * r ** (beta - 1.0), 0.0)", "BPR derivative without beta"),
    ("M15", "stm/assignment.py", "        if g(mid) < 0.0:\n            lo = mid", "        if g(mid) > 0.0:\n            lo = mid",
     "line search: bisection moves the wrong end"),
    ("M16", "stm/assignment.py", "return (tstt - sptt) / sptt", "return (tstt - sptt) / (tstt + sptt)",
     "relative gap with the wrong denominator"),
    ("M17", "stm/assignment.py", "return b0 * y + nu * b0 * s1 + mu * b0 * s2", "return b0 * y + mu * b0 * s1 + nu * b0 * s2",
     "bi-conjugate FW: weights of the two previous directions swapped"),
    ("M18", "stm/assignment.py", "    if float(np.dot(t, s - x)) >= 0.0:\n        return y, True",
     "    if False:\n        return y, True", "no fall-back to Frank-Wolfe when the direction is not a descent direction"),
    ("M19", "stm/paths.py", "                    node_flow[tail[k]] += f", "                    node_flow[head[k]] += f",
     "all-or-nothing loading passes flow to the wrong node"),
    ("M20", "stm/paths.py", "            nd = d + cost[k]", "            nd = cost[k]",
     "Dijkstra uses the link cost instead of the path cost"),
    ("M21", "stm/paths.py", "            acc[v] = acc[tail[k]] + extra[k]", "            acc[v] = extra[k]",
     "skim: attribute of the last link only, not summed along the path"),
    ("M22", "stm/model.py", "    d[np.arange(nz), np.arange(nz)] = f * near", "    d[np.arange(nz), np.arange(nz)] = near",
     "intrazonal distance without the factor"),
    ("M23", "stm/model.py", "        prod_pa[m] = P_region[reg] * w_pa[m] / w_pa[m].sum()",
     "        prod_pa[m] = P_region[reg] * w_pa[m] / w_pa.sum()", "regional productions shared over the whole island"),
    ("M24", "stm/model.py", "    return float(h[pk] / h.loc[lo:hi].sum())", "    return float(h[pk + 1] / h.loc[lo:hi].sum())",
     "peak-hour share taken from the wrong hour"),
    ("M25", "stm/pipeline.py", "    Q = T_daily * att * phf * Pcar / M.v(a[\"car_occupancy\"]) * M.v(a[\"background_factor\"])",
     "    Q = T_daily * att * phf * Pcar * M.v(a[\"car_occupancy\"]) * M.v(a[\"background_factor\"])",
     "car occupancy multiplies instead of divides"),
    ("M26", "stm/pipeline.py", "    O_add += np.bincount(r.zone.values - 1, weights=(r.gfa / r.gfa.sum()).values * pop * per_resident, minlength=nz)",
     "    O_add += np.bincount(r.zone.values - 1, weights=(r.gfa / r.gfa.sum()).values * pop, minlength=nz)",
     "Tengah residents counted as commuters"),
    ("M27", "stm/junction.py", "    return float(min(max((1.5 * L + 5.0) / (1.0 - Y), c_min), c_max))",
     "    return float(min(max((1.5 * L + 5.0) / (1.0 + Y), c_min), c_max))", "Webster cycle: 1 + Y instead of 1 - Y"),
    ("M28", "stm/junction.py", "+ X ** 2 / (2 * q * (1 - X))", "+ X ** 2 / (2 * q * (1 + X))",
     "Webster delay: random term with 1 + X"),
    ("M29", "stm/junction.py", "            if abs(d - 180.0) <= tol:", "            if abs(d) <= tol:",
     "phase plan pairs approaches from the same direction instead of opposite ones"),
    ("M30", "stm/junction.py", "        T *= np.divide(a, r, out=np.zeros_like(a), where=r > 0)[:, None]",
     "        T *= np.divide(b, r, out=np.zeros_like(a), where=r > 0)[:, None]",
     "turning-flow Furness: rows scaled to the exit totals"),
    ("M31", "stm/appraisal.py", "    return 0.5 * (T0 + T1) * (c0 - c1)", "    return (T0 + T1) * (c0 - c1)",
     "rule of a half without the half"),
    ("M32", "stm/appraisal.py", "    return 0.5 * (T0 + T1) * (c0 - c1)", "    return 0.5 * (T0 + T1) * (c1 - c0)",
     "rule of a half: sign of the cost change flipped"),
    ("M33", "stm/appraisal.py", "    return 0.5 * (T0 + T1) * (c0 - c1)", "    return 0.5 * (T0 + T0) * (c0 - c1)",
     "rule of a half: new users given the full cost change of existing users (T1 ignored)"),
    ("M34", "stm/appraisal.py", "(logsum(V1) - logsum(V0)) / (-cost_coefficient)", "(logsum(V1) - logsum(V0)) * (-cost_coefficient)",
     "logsum benefit multiplied by the cost coefficient instead of divided"),
    ("M35", "stm/appraisal.py", "        if year_from_base <= last:", "        if year_from_base < last:",
     "discount schedule: the boundary year takes the next rate"),
    ("M36", "stm/appraisal.py", "        f[k] = f[k - 1] / (1.0 + annual_rate(k, schedule))",
     "        f[k] = f[k - 1] * (1.0 - annual_rate(k, schedule))", "discount factor (1 - r) instead of 1 / (1 + r)"),
    ("M37", "stm/appraisal.py", "    s[first_year:] = annual * (1.0 + growth) ** np.arange(n_years)",
     "    s[first_year:] = annual * (1.0 + growth) ** np.arange(1, n_years + 1)",
     "benefit stream: growth already applied in the opening year"),
    ("M38", "stm/appraisal.py", "    return base_value * (pvc - pv_other) / pv_part_linear",
     "    return base_value * (pvc + pv_other) / pv_part_linear", "switching value: fixed benefits added to the costs"),
    ("M39", "stm/appraisal.py", '        "car_user_time": day["car_vehicle_hours_per_peak_hour"] * occupancy * road * vot,',
     '        "car_user_time": day["car_vehicle_hours_per_peak_hour"] / occupancy * road * vot,',
     "vehicle-hours divided by car occupancy instead of multiplied"),
    ("M40", "stm/appraisal.py", '        "car_non_fuel_operating": -day["vehicle_km_change_per_peak_hour"]',
     '        "car_non_fuel_operating": day["vehicle_km_change_per_peak_hour"]',
     "fewer vehicle-km counted as a cost"),
    ("M41", "stm/appraisal.py", "    pvc = capital + pv_op", "    pvc = capital", "operating costs left out of the present value of costs"),
    ("M42", "stm/appraisal.py", "    pv_op = present_value(benefit_stream(operating, first, years, 0.0), schedule)",
     "    pv_op = operating * years", "operating costs not discounted"),
    ("M43", "stm/appraisal.py", "    N1 = T_do_min * attendance * P1[1]", "    N1 = T_do_min * attendance * P0[1]",
     "appraisal: with-scheme public-transport demand taken from the without-scheme mode shares"),
    ("M44", "stm/appraisal.py", "    th, _ = skim(rm.net.graph, rm.net.time(flow), rm.origins, rm.dests)",
     "    th, _ = skim(rm.net.graph, rm.net.t0, rm.origins, rm.dests)",
     "appraisal: car times taken at free flow, so decongestion is never seen"),
    ("M45", "stm/appraisal.py", "    zone_pt = pt_min.sum(axis=1) / 60.0", "    zone_pt = pt_min.sum(axis=0) / 60.0",
     "benefits attributed to the workplace zone instead of the zone of residence"),
    ("M46", "stm/survey.py", "    return 1.0 + (m - 1.0) * rho", "    return 1.0 + m * rho", "design effect 1 + m rho"),
    ("M47", "stm/survey.py", "    e2 = float(np.sum(p * (s * q * (1.0 - q) + (s * q) ** 2)))", "    e2 = float(np.sum(p * (s * q) ** 2))",
     "cluster size: binomial variance left out of E[m^2]"),
    ("M48", "stm/survey.py", "    return float(w.size * np.sum(w ** 2) / np.sum(w) ** 2)", "    return float(np.sum(w ** 2) / np.sum(w) ** 2)",
     "Kish design effect without n"),
    ("M49", "stm/survey.py", "    return n0 if N is None else n0 / (1.0 + (n0 - 1.0) / N)", "    return n0 if N is None else n0 / (1.0 + n0 / N)",
     "finite population correction with n0 instead of n0 - 1"),
    ("M50", "stm/survey.py", "    return deff * fpc_adjust(z ** 2 * p * (1.0 - p) / margin ** 2, N)",
     "    return deff * fpc_adjust(z * p * (1.0 - p) / margin ** 2, N)", "sample size for a proportion with z instead of z squared"),
    ("M51", "stm/survey.py", "    return deff * fpc_adjust((z * cv / rel_margin) ** 2, N)", "    return deff * fpc_adjust(z * cv / rel_margin ** 2, N)",
     "sample size for a mean: only the margin squared"),
    ("M52", "stm/survey.py", "        order = np.argsort(-(exact - n), kind=\"stable\")", "        order = np.argsort(exact - n, kind=\"stable\")",
     "allocation: spare units go to the smallest remainders"),
    ("M53", "stm/survey.py", "            w *= np.divide(t, cur, out=np.ones_like(t), where=cur > 0)[c]",
     "            w *= np.divide(cur, t, out=np.ones_like(t), where=cur > 0)[c]", "raking factor inverted"),
    ("M54", "stm/survey.py", "    e = w * (y - R * x) / X", "    e = w * y / X", "linearised variance from y instead of the residual y - R x"),
    ("M55", "stm/survey.py", "            var += t.size / (t.size - 1.0) * float(np.sum((t - t.mean()) ** 2))",
     "            var += float(np.sum((t - t.mean()) ** 2))", "variance without the n / (n - 1) factor"),
    ("M56", "stm/survey.py", "    tot = np.bincount(cidx, weights=e, minlength=cl.size)", "    tot = e\n    cidx = np.arange(e.size)\n    cl = cidx",
     "clustering ignored: every person treated as an independent draw"),
    ("M57", "stm/survey.py", '                         "trip_rate": float(2.0 * self.attendance * c.sum() / self.pop[mask].sum()),',
     '                         "trip_rate": float(self.attendance * c.sum() / self.pop[mask].sum()),',
     "truth of the trip rate counts one trip per commuter instead of two"),
    ("M58", "stm/survey.py", "            share[:, m] = ((1.0 - self.private) * (self.dest * self.P[0][m]).sum(axis=1)\n                           + self.private * (self.dest * self.P[1][m]).sum(axis=1))",
     "            share[:, m] = (self.dest * self.P[0][m]).sum(axis=1)",
     "truth of the mode shares ignores private housing"),
    ("M59", "stm/survey.py", "    mode[idx] = np.where(um < p_car, 0, np.where(um < p_car + p_pt, 1, 2))",
     "    mode[idx] = np.where(um < p_car, 0, np.where(um < p_pt, 1, 2))", "synthetic mode draw: public transport cut at its own probability, not the cumulative one"),
    ("M60", "stm/survey.py", "    base = (hh_frame / np.maximum(hh_resp, 1.0))[resp.region.values]",
     "    base = (hh_resp / np.maximum(hh_frame, 1.0))[resp.region.values]", "design weight inverted"),
    ("M61", "stm/survey.py", '                     "issued_households": int(math.ceil(complete / rr)),',
     '                     "issued_households": int(math.ceil(complete * rr)),', "issued sample multiplied by the response rate"),
    ("M62", "stm/survey.py", "        complete = int(math.ceil(max(hh_mode, hh_trip)))", "        complete = int(math.ceil(min(hh_mode, hh_trip)))",
     "sample size set by the easier of the two precision targets"),
    ("M63", "stm/survey.py", "        per_zone[m] = rng.multinomial(int(n_k), fr.households[m] / fr.households[m].sum())",
     "        per_zone[m] = rng.multinomial(int(n_k), np.full(int(m.sum()), 1.0 / m.sum()))",
     "households drawn equally from every subzone regardless of its size"),
]

# Mutants that cannot change behaviour on any reachable input, with the reason. Reported as survivors, not hidden.
EQUIVALENT: dict[str, str] = {}


def run_pytest(cwd: Path, extra: list[str], timeout: int = 1800) -> tuple[bool, str]:
    env = dict(os.environ, STM_REQUIRE_SIOUX_FALLS="1", NUMBA_CACHE_DIR=str(cwd / ".numba_cache"),
               OPENBLAS_NUM_THREADS="1")
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", "-p", "no:warnings",
                            *extra], cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return False, "timeout (counted as killed)"
    lines = [ln for ln in p.stdout.strip().splitlines() if ln.strip()]
    failed = [ln for ln in lines if ln.startswith("FAILED") or ln.startswith("ERROR")]
    tail = (failed[:1] or lines[-1:] or [p.stderr.strip()[-200:]])[0]
    return p.returncode == 0, tail


def make_copy(dst: Path) -> None:
    for rel in COPY:
        src = REPO / rel
        if src.is_dir():
            shutil.copytree(src, dst / rel, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        elif src.exists():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst / rel)


def one(m: tuple) -> dict:
    mid, rel, old, new, what = m
    with tempfile.TemporaryDirectory(prefix=f"mut_{mid}_") as tmp:
        work = Path(tmp)
        make_copy(work)
        f = work / rel
        text = f.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"{mid}: snippet found {text.count(old)} times in {rel}, expected exactly once")
        f.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
        ok_ns, tail_ns = run_pytest(work, ["-k", "not test_snapshot_"])
        if not ok_ns:
            ok_all, tail_all = False, "(killed already without the snapshot tests)"
        else:
            ok_all, tail_all = run_pytest(work, [])
    r = {"id": mid, "file": rel, "what": what, "original": old, "mutated": new, "killed": not ok_all,
         "killed_without_snapshot": not ok_ns, "pytest_without_snapshot": tail_ns, "pytest_full": tail_all}
    if mid in EQUIVALENT:
        r["equivalent"] = EQUIVALENT[mid]
    print(f"{mid}: {'killed' if r['killed'] else 'SURVIVED'} ({'killed' if r['killed_without_snapshot'] else 'survived'}"
          f" without snapshot)  {tail_ns[:110]}", flush=True)
    return r


def count_tests() -> int:
    p = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "-p",
                        "no:cacheprovider"], cwd=REPO,
                       capture_output=True, text=True, env=dict(os.environ, STM_REQUIRE_SIOUX_FALLS="1"))
    m = re.search(r"(\d+) tests? collected", p.stdout)
    return int(m.group(1)) if m else -1


def main(workers: int) -> None:
    with tempfile.TemporaryDirectory(prefix="mut_base_") as tmp:
        make_copy(Path(tmp))
        ok, tail = run_pytest(Path(tmp), [])
        if not ok:
            raise SystemExit(f"the unmodified suite fails: {tail}")
        print("unmodified suite passes:", tail, flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, MUTANTS))
    killed = sum(r["killed"] for r in results)
    killed_ns = sum(r["killed_without_snapshot"] for r in results)
    report = {"date": datetime.date.today().isoformat(), "tests_collected": count_tests(), "total": len(results),
              "killed": killed, "killed_without_snapshot": killed_ns, "mutants": results}
    # The first run after the list of mutants changes is kept, so that later runs (after tests were added for the
    # survivors) do not erase what the suite missed at first.
    path = REPO / "results" / "mutation_report.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    ids = [r["id"] for r in results]
    if old.get("first_run") and old["first_run"].get("mutant_ids") == ids:
        report["first_run"] = old["first_run"]
    else:
        brief = [{"id": r["id"], "file": r["file"], "what": r["what"]} for r in results]
        report["first_run"] = {
            "date": report["date"], "tests_collected": report["tests_collected"], "total": len(results),
            "killed": killed, "killed_without_snapshot": killed_ns, "mutant_ids": ids,
            "survivors": [b for b, r in zip(brief, results) if not r["killed"]],
            "survivors_without_snapshot": [b for b, r in zip(brief, results) if not r["killed_without_snapshot"]]}
    (REPO / "results" / "mutation_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8",
                                                          newline="\n")
    print(f"{killed}/{len(results)} killed; {killed_ns}/{len(results)} without the snapshot tests")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workers", type=int, default=3)
    main(ap.parse_args().workers)
