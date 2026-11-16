"""Figures for the README and the validation report (matplotlib, offline). Every figure is drawn from files in
results/ and data/inputs/ only.

Colours: categorical slots in a fixed order (blue, orange, aqua); magnitudes on one blue ramp, light to dark;
changes on a blue-red diverging scale with a grey midpoint.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap, TwoSlopeNorm, LinearSegmentedColormap  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RES = REPO / "results"
FIG = RES / "figures"
INP = REPO / "data" / "inputs"

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb"
RAMP = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
DIVERGING = LinearSegmentedColormap.from_list("bluered", ["#1c5cab", "#86b6ef", "#f0efec", "#f19b9a", "#c23534"])
ATTRIB = "Map data (c) OpenStreetMap contributors (ODbL); boundaries URA Master Plan 2019 (Singapore Open Data Licence)"


def _style():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10,
        "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 2.0,
    })


def _zones():
    g = json.loads((INP / "zones_geometry.json").read_text(encoding="utf-8"))
    return g["zones"]


def _outline(ax, zones, face=None, values=None, cmap=None, norm=None, lw=0.25):
    polys, vals = [], []
    for zg in zones:
        for ring in zg["rings"]:
            polys.append(np.asarray(ring) / 1000.0)
            vals.append(values[zg["zone"] - 1] if values is not None else 0)
    pc = PolyCollection(polys, edgecolors="#ffffff" if values is not None else "#c9c8c2", linewidths=lw)
    if values is not None:
        pc.set_array(np.asarray(vals, dtype=float))
        pc.set_cmap(cmap)
        pc.set_norm(norm)
    else:
        pc.set_facecolor(face or "#f2f1ed")
    ax.add_collection(pc)
    return pc


def _map_axes(ax, title):
    ax.set_aspect("equal")
    ax.set_xlim(1.5, 51.5)
    ax.set_ylim(24.0, 50.5)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, loc="left")


def _road_lines(sel=None):
    geo = json.loads((INP / "road_geometry.json").read_text(encoding="utf-8"))["links"]
    if sel is None:
        sel = range(len(geo))
    return [np.asarray(geo[i]) / 1000.0 for i in sel]


def fig_zones(summary):
    zt = pd.read_csv(RES / "zones_trip_ends.csv")
    zz = pd.read_csv(INP / "zones.csv")
    dens = zt.productions_2020.values / np.maximum(zz.area_km2.values, 0.05)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9))
    for ax, vals, title, lab in ((axes[0], dens, "Commuters living per km2 (Census 2020)", "residents"),
                                 (axes[1], zt.attractions_2020.values / np.maximum(zz.area_km2.values, 0.05),
                                  "Commuters working per km2 (Census 2020, spread by MP2019 floor area)", "jobs")):
        bounds = [0, 500, 2000, 5000, 10000, 1e9]
        cm = ListedColormap(["#f2f1ed"] + RAMP[1:])
        pc = _outline(ax, _zones(), values=vals, cmap=cm, norm=BoundaryNorm(bounds, cm.N))
        _map_axes(ax, title)
        cb = fig.colorbar(pc, ax=ax, shrink=0.7, ticks=[250, 1250, 3500, 7500, 15000])
        cb.ax.set_yticklabels(["< 500", "500-2k", "2k-5k", "5k-10k", "> 10k"])
        cb.outline.set_visible(False)
    fig.text(0.01, 0.01, f"{summary['zones']['n']} zones = URA Master Plan 2019 subzones. " + ATTRIB, fontsize=6.5,
             color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "zones.png", dpi=150)
    plt.close(fig)


def fig_desire_lines():
    zt = pd.read_csv(RES / "zones_trip_ends.csv")
    zz = pd.read_csv(INP / "zones.csv")
    cells = pd.read_csv(RES / "calibration_commute_cells.csv")
    # planning-area-to-planning-area flows are not stored; draw region-of-residence -> workplace cells instead
    reg_xy = zz.groupby("region")[["x", "y"]].mean() / 1000.0
    pa_xy = zz.groupby("planning_area")[["x", "y"]].mean() / 1000.0
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.9))
    for ax, col, title in ((axes[0], "census_commuters", "Census 2020: commuters by region of residence -> workplace"),
                           (axes[1], "modelled_commuters", "Gravity model, aggregated to the same cells")):
        _outline(ax, _zones(), face="#f2f1ed")
        c = cells[cells[col] > 3000].sort_values(col)
        segs = [[reg_xy.loc[r].values, pa_xy.loc[w].values] for r, w in zip(c.region_of_residence, c.workplace)]
        lw = 0.3 + 5.5 * c[col].values / cells.census_commuters.max()
        ax.add_collection(LineCollection(segs, linewidths=lw, colors=BLUE, alpha=0.55, capstyle="round"))
        ax.scatter(reg_xy.x, reg_xy.y, s=28, color=ORANGE, zorder=3, edgecolor=SURFACE, linewidth=1.5)
        for r, (x, y) in reg_xy.iterrows():
            ax.annotate(r.replace(" REGION", "").title(), (x, y), xytext=(4, 4), textcoords="offset points",
                        fontsize=7, color=INK2)
        _map_axes(ax, title)
    fig.text(0.01, 0.01, "Lines: cells with more than 3,000 commuters; width proportional to commuters. Orange dots: "
             "region centroids. " + ATTRIB, fontsize=6.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "desire_lines.png", dpi=150)
    plt.close(fig)


def fig_calibration(summary):
    tld = pd.read_csv(RES / "tld_bus.csv")
    cells = pd.read_csv(RES / "calibration_commute_cells.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    for ax, ym, role in ((axes[0], 202607, "calibration"), (axes[1], 202608, "validation")):
        t = tld[(tld.month == ym) & (tld.km_from < 25)]
        x = t.km_from + 0.5
        tot = tld[tld.month == ym].observed_trips.sum()
        ax.bar(x, t.observed_trips / tot * 100, width=0.86, color="#b7d3f6", label="observed (DataMall)")
        ax.plot(x, t.modelled_trips_gamma / tld[tld.month == ym].modelled_trips_gamma.sum() * 100, color=BLUE,
                label="gamma gravity")
        ax.plot(x, t.modelled_trips_exponential / tld[tld.month == ym].modelled_trips_exponential.sum() * 100,
                color=ORANGE, linestyle="--", linewidth=1.5, label="exponential")
        b = summary["distribution_bus"][role]
        ax.set_title(f"Bus trips 07:00-08:00, {str(ym)[:4]}-{str(ym)[4:]} ({role})", loc="left")
        ax.set_xlabel("zone-to-zone road distance (km)")
        ax.set_ylabel("% of trips")
        ax.text(0.98, 0.95, f"coincidence ratio {b['coincidence_ratio']:.2f}\nmean {b['mean_km_observed']:.2f} km "
                f"observed\n{b['mean_km_model']:.2f} km modelled", transform=ax.transAxes, ha="right", va="top",
                fontsize=7.5, color=INK2)
        ax.legend(loc="center right", fontsize=7.5)
    ax = axes[2]
    m = cells.census_commuters > 0
    ax.loglog(cells.census_commuters[m], cells.modelled_commuters[m], "o", ms=4, color=BLUE, alpha=0.7,
              markeredgecolor=SURFACE, markeredgewidth=0.5)
    lim = [50, 2e5]
    ax.plot(lim, lim, color=MUTED, linewidth=1)
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("Census 2020 commuters (region -> workplace)")
    ax.set_ylabel("modelled commuters")
    dc = summary["distribution_commute"]
    ax.set_title("Commuter gravity model vs Census cells", loc="left")
    ax.text(0.04, 0.95, f"{dc['cells']} cells, R2 {dc['r2_cells']:.3f}", transform=ax.transAxes, va="top", fontsize=7.5,
            color=INK2)
    fig.tight_layout()
    fig.savefig(FIG / "calibration.png", dpi=150)
    plt.close(fig)


def fig_bus_pairs(summary):
    p = pd.read_csv(RES / "bus_pa_pairs_202608.csv")
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    m = (p.observed_trips > 0) & (p.modelled_trips > 0)
    ok = p.geh < 5
    ax.loglog(p.observed_trips[m & ok], p.modelled_trips[m & ok], "o", ms=3, color=BLUE, alpha=0.6, label="GEH < 5")
    ax.loglog(p.observed_trips[m & ~ok], p.modelled_trips[m & ~ok], "o", ms=3, color=ORANGE, alpha=0.6,
              label="GEH >= 5")
    lim = [0.5, 1e5]
    ax.plot(lim, lim, color=MUTED, linewidth=1)
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    v = summary["distribution_bus"]["validation"]
    ax.set_xlabel("observed bus trips, 07:00-08:00 (August 2026)")
    ax.set_ylabel("modelled bus trips")
    ax.set_title("Planning-area pairs, validation month", loc="left")
    ax.text(0.04, 0.95, f"{v['pa_pairs']} pairs; GEH < 5: {v['geh_lt5_share_pa_pairs']:.0%}; R2 {v['r2_pa_pairs']:.3f}",
            transform=ax.transAxes, va="top", fontsize=7.5, color=INK2)
    ax.legend(loc="lower right", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(FIG / "bus_pa_pairs.png", dpi=150)
    plt.close(fig)


def fig_mode(summary):
    r = pd.read_csv(RES / "mode_shares_residence.csv")
    w = pd.read_csv(RES / "mode_shares_workplace.csv")
    h = pd.read_csv(RES / "mode_shares_holdout_cells.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.7))
    for ax, df, title in ((axes[0], r, "By planning area of residence (calibration)"),
                          (axes[1], w, "By planning area of workplace (calibration)"),
                          (axes[2], h, "Region x workplace cells (not fitted)")):
        for col, colr, lab in (("car", BLUE, "car"), ("pt", ORANGE, "public transport")):
            ax.plot(df[f"census_{col}"] * 100, df[f"model_{col}"] * 100, "o", ms=4, color=colr, alpha=0.7,
                    label=lab, markeredgecolor=SURFACE, markeredgewidth=0.5)
        ax.plot([0, 100], [0, 100], color=MUTED, linewidth=1)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 100)
        ax.set_xlabel("Census 2020 share (%)")
        ax.set_ylabel("modelled share (%)")
        ax.set_title(title, loc="left")
        ax.legend(loc="lower right", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(FIG / "mode_shares.png", dpi=150)
    plt.close(fig)


def fig_vc():
    lf = pd.read_csv(RES / "link_flows.csv", keep_default_na=False, na_values=[""])
    fig, ax = plt.subplots(figsize=(10, 5.6))
    _outline(ax, _zones(), face="#f2f1ed")
    order = np.argsort(lf.vc_base_2020.values)
    lines = _road_lines(order)
    vc = lf.vc_base_2020.values[order]
    hw = lf.highway.values[order]
    width = np.where(np.isin(hw, ["motorway", "trunk"]), 1.5, np.where(np.char.endswith(hw.astype(str), "_link"), 0.5, 0.8))
    bounds = [0, 0.5, 0.85, 1.0, 10]
    cm = ListedColormap([RAMP[0], RAMP[2], RAMP[3], "#c23534"])
    lc = LineCollection(lines, linewidths=width, cmap=cm, norm=BoundaryNorm(bounds, cm.N))
    lc.set_array(vc)
    ax.add_collection(lc)
    _map_axes(ax, "Modelled volume / capacity, AM peak hour 07:00-08:00, 2020 base")
    cb = fig.colorbar(lc, ax=ax, shrink=0.6, ticks=[0.25, 0.675, 0.925, 5.5])
    cb.ax.set_yticklabels(["< 0.5", "0.5-0.85", "0.85-1.0", "> 1.0"])
    cb.outline.set_visible(False)
    fig.text(0.01, 0.01, "No traffic counts were used: these are model outputs, not observations. " + ATTRIB,
             fontsize=6.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "vc_base.png", dpi=150)
    plt.close(fig)


def fig_scenario(summary):
    lf = pd.read_csv(RES / "link_flows.csv", keep_default_na=False, na_values=[""])
    rail = json.loads((REPO / "config" / "rail.json").read_text(encoding="utf-8"))
    st = pd.read_csv(INP / "rail_stations_osm.csv", keep_default_na=False).set_index("code")
    nm = pd.read_csv(INP / "rail_station_names_osm.csv", keep_default_na=False)
    lta = pd.read_csv(INP / "lta_station_positions.csv").set_index("station")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [1.35, 1]})
    ax = axes[0]
    _outline(ax, _zones(), face="#f2f1ed")
    d = (lf.vc_ds_2030_jrl - lf.vc_dm_2030).values
    m = np.abs(d) >= 0.01
    sel = np.where(m)[0][np.argsort(np.abs(d[m]))]
    lc = LineCollection(_road_lines(sel), linewidths=1.6, cmap=DIVERGING, norm=TwoSlopeNorm(0, -0.15, 0.15))
    lc.set_array(d[sel])
    ax.add_collection(lc)
    # Jurong Region Line
    pos = {}
    for code in ["JS1", "JS8", "JE5"]:
        key = rail["jrl"]["existing_interchanges"][code]
        pos[code] = (lta.loc[key, "x"] / 1000, lta.loc[key, "y"] / 1000)
    for ln in rail["jrl"]["lines"].values():
        for code, name in ln["stations"]:
            if code in pos:
                continue
            if code in st.index:
                pos[code] = (st.loc[code, "x"] / 1000, st.loc[code, "y"] / 1000)
            else:
                r = nm[nm.name.str.upper() == name.upper()].iloc[0]
                pos[code] = (r.x / 1000, r.y / 1000)
    for ln in rail["jrl"]["lines"].values():
        xy = np.array([pos[c] for c, _ in ln["stations"]])
        ax.plot(xy[:, 0], xy[:, 1], color=AQUA, linewidth=2.2, zorder=4)
        ax.scatter(xy[:, 0], xy[:, 1], s=14, color=SURFACE, edgecolor=AQUA, linewidth=1.5, zorder=5)
    _map_axes(ax, "Change in V/C, 2030 with JRL minus without (links changing by 0.01+)")
    ax.set_xlim(3, 26)
    ax.set_ylim(28, 45)
    cb = fig.colorbar(lc, ax=ax, shrink=0.75)
    cb.set_label("V/C change")
    cb.outline.set_visible(False)
    n_jrl = len({c for ln in rail["jrl"]["lines"].values() for c, _ in ln["stations"]})
    ax.plot([], [], color=AQUA, linewidth=2.2, label=f"Jurong Region Line ({n_jrl} stations)")
    ax.legend(loc="lower left", fontsize=7.5)
    ax = axes[1]
    ms = pd.read_csv(RES / "scenario_mode_share_west.csv")
    ms = ms[ms.commuters_ds_2030_jrl > 2000].sort_values("pt_ds_2030_jrl")
    y = np.arange(len(ms))
    # dot plot (not bars): the axis does not start at zero
    for _, r in ms.reset_index(drop=True).iterrows():
        vals = [r[f"pt_{n}"] * 100 for n in ("base_2020", "dm_2030", "ds_2030_jrl") if np.isfinite(r[f"pt_{n}"])]
        ax.plot([min(vals), max(vals)], [_ + 0, _ + 0], color=GRID, linewidth=2, zorder=1)
    for name, colr, lab, mk in (("base_2020", "#86b6ef", "2020 base", "o"), ("dm_2030", BLUE, "2030 without JRL", "s"),
                                ("ds_2030_jrl", ORANGE, "2030 with JRL", "D")):
        ax.scatter(ms[f"pt_{name}"] * 100, y, s=34, color=colr, marker=mk, label=lab, zorder=3, edgecolor=SURFACE,
                   linewidth=1.0)
    ax.set_yticks(y)
    ax.set_yticklabels([p.title() for p in ms.planning_area])
    ax.set_xlabel("public transport share of commuters living there (%)")
    ax.set_title("West Region planning areas", loc="left")
    ax.legend(loc="lower right", fontsize=7.5)
    ax.grid(axis="y", visible=False)
    fig.text(0.01, 0.01, ATTRIB + ". JRL stations: LTA project page (stages) and OpenStreetMap (positions).",
             fontsize=6.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "scenario_2030.png", dpi=150)
    plt.close(fig)


def fig_convergence():
    c = pd.read_csv(RES / "assignment_convergence.csv")
    fig, ax = plt.subplots(figsize=(5.2, 3.4))
    for (name, g), colr in zip(c.groupby("scenario", sort=False), (BLUE, ORANGE, AQUA)):
        ax.semilogy(g.iteration, g.relative_gap, color=colr, label=name.replace("_", " "))
    tgt = json.loads((REPO / "config" / "model.json").read_text(encoding="utf-8"))["assignment"]["rgap_target"]["value"]
    ax.axhline(tgt, color=MUTED, linewidth=1, linestyle=":")
    ax.text(1, 1.15 * tgt, f"target {tgt:.0e}", fontsize=7, color=INK2)
    ax.set_xlabel("bi-conjugate Frank-Wolfe iteration")
    ax.set_ylabel("relative gap")
    ax.set_title("Assignment convergence", loc="left")
    ax.legend(fontsize=7.5)
    fig.tight_layout()
    fig.savefig(FIG / "convergence.png", dpi=150)
    plt.close(fig)


def make_all():
    _style()
    FIG.mkdir(parents=True, exist_ok=True)
    summary = json.loads((RES / "summary.json").read_text(encoding="utf-8"))
    fig_zones(summary)
    fig_desire_lines()
    fig_calibration(summary)
    fig_bus_pairs(summary)
    fig_mode(summary)
    fig_vc()
    fig_scenario(summary)
    fig_convergence()
