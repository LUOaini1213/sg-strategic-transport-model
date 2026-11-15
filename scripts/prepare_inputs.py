"""Turn the raw downloads in data/raw/ into the small committed inputs in data/inputs/.

Needs requirements-tools.txt (geopandas, shapely, pyproj). The model pipeline and the tests only read data/inputs/.

    python scripts/prepare_inputs.py --datamall-dir <folder with the DataMall files>

Steps (each writes one or more files; all coordinates are SVY21 / EPSG:3414 metres):
  zones        MP2019 subzones -> zones.csv, zones_geometry.json (simplified outlines, for maps only)
  census       Census of Population 2020 tables -> census_*.csv (tidy copies of the published numbers)
  landuse      MP2019 land use parcels, assigned to subzones by representative point -> landuse_subzone.csv,
               tengah_parcels.csv
  roads        OpenStreetMap ways motorway..tertiary (and links) -> road_nodes.csv, road_links.csv,
               road_geometry.json
  rail         OpenStreetMap rail stations with LTA station codes -> rail_stations.csv
  bus          LTA DataMall bus origin-destination volumes, weekdays, aggregated to zones -> bus_od_<yyyymm>.csv,
               bus_hourly_<yyyymm>.csv, bus_stop_tld_<yyyymm>.csv
  manifest     SHA-256 of every committed input (LF bytes) and a copy of the raw-download manifest
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "inputs"
ROAD_CLASSES = ["motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary",
                "secondary_link", "tertiary", "tertiary_link"]
BUS_MONTHS = ["202607", "202608"]
BUS_HOURS = [7, 8]          # tap-in hours kept at OD level (07:00-07:59 is the busiest weekday morning hour)


def write_csv(path: Path, header: list[str], rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8",
                    newline="\n")


def r1(v) -> float:
    return round(float(v), 1)


# ---------------------------------------------------------------------------------------------------------------
# zones
# ---------------------------------------------------------------------------------------------------------------
def zones():
    import geopandas as gpd

    sz = gpd.read_file(RAW / "mp2019_subzone.geojson").to_crs(3414)
    sz = sz.sort_values("SUBZONE_C").reset_index(drop=True)
    sz["zone"] = np.arange(1, len(sz) + 1)
    sz["geometry"] = sz.geometry.buffer(0)
    return sz


def write_zones(sz, lu):
    """Zone table and simplified outlines. The centroid is the floor-area-weighted mean of the zone's parcels
    (representative points), moved to the zone's representative point if it falls outside the zone."""
    from shapely.geometry import Point

    rows, geo = [], []
    w = lu.assign(wt=lu.gfa_est_m2.clip(lower=0)).groupby("zone")
    cx = w.apply(lambda g: np.average(g.x, weights=g.wt) if g.wt.sum() > 0 else np.nan)
    cy = w.apply(lambda g: np.average(g.y, weights=g.wt) if g.wt.sum() > 0 else np.nan)
    for _, z in sz.iterrows():
        rp = z.geometry.representative_point()
        x, y = cx.get(z.zone, np.nan), cy.get(z.zone, np.nan)
        moved = False
        if not np.isfinite(x) or not z.geometry.contains(Point(x, y)):
            x, y, moved = rp.x, rp.y, True
        rows.append([z.zone, z.SUBZONE_C, z.SUBZONE_N, z.PLN_AREA_N, z.REGION_N, z.CA_IND,
                     round(z.geometry.area / 1e6, 4), r1(x), r1(y), int(moved)])
        g = z.geometry.simplify(25.0)
        polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        geo.append({"zone": int(z.zone), "rings": [[[r1(a), r1(b)] for a, b in p.exterior.coords]
                                                    for p in polys if p.area > 2000]})
    write_csv(OUT / "zones.csv", ["zone", "subzone_code", "subzone", "planning_area", "region", "central_area",
                                  "area_km2", "x", "y", "centroid_at_rep_point"], rows)
    write_json(OUT / "zones_geometry.json", {"crs": "EPSG:3414 (SVY21), metres; outlines simplified 25 m",
                                             "source": "URA Master Plan 2019 Subzone Boundary (No Sea)",
                                             "zones": geo})


# ---------------------------------------------------------------------------------------------------------------
# census
# ---------------------------------------------------------------------------------------------------------------
def _num(v) -> float:
    v = str(v).strip().replace(",", "")
    return 0.0 if v in ("-", "", "na", "NA") else float(v)


def singstat_rows(path: Path):
    """Yield (planning_area, subzone_or_None, columns) for a SingStat PA/subzone table."""
    data = json.loads(path.read_text(encoding="utf-8"))["Data"]
    pa = None
    for r in data["row"]:
        t = r["rowText"].strip()
        if t == "Total":
            yield None, None, r["columns"]
        elif re.search(r"\s*-\s*Total$", t):
            pa = re.sub(r"\s*-\s*Total$", "", t).strip()
            yield pa, None, r["columns"]
        else:
            yield pa, t, r["columns"]


def census(sz):
    names = {(p.upper(), s.upper()): z for p, s, z in zip(sz.PLN_AREA_N, sz.SUBZONE_N, sz.zone)}
    ages = ["0 - 4", "5 - 9", "10 - 14", "15 - 19", "20 - 24", "25 - 29", "30 - 34", "35 - 39", "40 - 44",
            "45 - 49", "50 - 54", "55 - 59", "60 - 64", "65 - 69", "70 - 74", "75 - 79", "80 - 84", "85 - 89",
            "90 & Over"]
    pop_rows, unmatched, pa_tot = [], [], {}
    for pa, s, cols in singstat_rows(RAW / "singstat_17560_census2020_population_subzone_age_sex.json"):
        tot = next(c for c in cols if c["key"] == "Total")
        vals = {c["key"]: _num(c["value"]) for c in tot["columns"]}
        if s is None:
            if pa is not None:
                pa_tot[pa.upper()] = vals["Total"]
            continue
        z = names.get((pa.upper(), s.upper()))
        if z is None:
            unmatched.append((pa, s))
            continue
        a15_64 = sum(vals[a] for a in ages[3:13])
        a20_64 = sum(vals[a] for a in ages[4:13])
        a15p = sum(vals[a] for a in ages[3:])
        pop_rows.append([z, int(vals["Total"]), int(a15p), int(a15_64), int(a20_64)])
    if unmatched:
        raise SystemExit(f"unmatched subzones in table 17560: {unmatched}")
    pop_rows.sort()
    write_csv(OUT / "census2020_population_subzone.csv", ["zone", "pop_total", "pop_15plus", "pop_15_64",
                                                          "pop_20_64"], pop_rows)

    dw_rows = []
    for pa, s, cols in singstat_rows(RAW / "singstat_17562_census2020_population_subzone_dwelling.json"):
        if s is None:
            continue
        z = names[(pa.upper(), s.upper())]
        top = {c["key"]: c for c in cols}
        hdb = _num(next(c for c in top["HDB Dwellings"]["columns"] if c["key"] == "Total")["value"])
        dw_rows.append([z, int(_num(top["Total"]["value"])), int(hdb),
                        int(_num(top["Condominiums & Other Apartments"]["value"])),
                        int(_num(top["Landed Properties"]["value"])), int(_num(top["Others"]["value"]))])
    dw_rows.sort()
    write_csv(OUT / "census2020_population_dwelling_subzone.csv",
              ["zone", "pop_total", "hdb", "condo_other_apartments", "landed", "others"], dw_rows)

    # Employed residents by planning area of residence and usual mode of transport to work
    m = pd.read_csv(RAW / "census2020_mode_by_planning_area.csv", dtype=str)
    m = m.rename(columns={"Number": "planning_area"})
    for c in m.columns[1:]:
        m[c] = m[c].map(_num).astype(int)
    m.to_csv(OUT / "census2020_mode_residence_pa.csv", index=False, lineterminator="\n")

    # Employed residents by planning area of workplace, usual mode (4 groups) and planning region of residence
    w = pd.read_csv(RAW / "census2020_workplace_mode_region.csv", dtype=str).rename(columns={"Number": "workplace"})
    long = []
    region_key = {"Total": "TOTAL", "CentralRegion": "CENTRAL REGION", "EastRegion": "EAST REGION",
                  "NorthRegion": "NORTH REGION", "North_EastRegion": "NORTH-EAST REGION", "WestRegion": "WEST REGION"}
    mode_key = {"Total": "total", "CombinationsofRail_MRT_LRT_orPublicBus": "pt",
                "CombinationsofRail_MRT_LRT_orPubl": "pt", "CombinationsofRail_MRT_LRT_orPublic": "pt",
                "CombinationsofRail_MRT_LRT_orP": "pt", "CombinationsofRail_MRT_LRT_orPublicB": "pt",
                "CarorTaxi_PrivateHireCarOnly": "car_taxi", "OtherModes": "other", "NoTransportRequired": "none"}
    for c in w.columns[1:]:
        reg, rest = c.split("_", 1) if not c.startswith("North_East") else ("North_EastRegion", c[len("North_EastRegion_"):])
        mode = rest.replace("ModeofTransport_", "")
        mk = mode_key.get(mode)
        if mk is None and mode.startswith("CombinationsofRail"):
            mk = "pt"
        if mk is None:
            raise SystemExit(f"unknown column {c}")
        for wp, v in zip(w.workplace, w[c]):
            long.append([wp, region_key[reg], mk, int(_num(v))])
    write_csv(OUT / "census2020_workplace_region_mode.csv", ["workplace", "region_of_residence", "mode", "persons"],
              long)
    return pa_tot


# ---------------------------------------------------------------------------------------------------------------
# land use
# ---------------------------------------------------------------------------------------------------------------
def landuse(sz):
    import geopandas as gpd

    lu = gpd.read_file(RAW / "mp2019_land_use.geojson", columns=["OBJECTID", "LU_DESC", "GPR"]).to_crs(3414)
    lu["geometry"] = lu.geometry.buffer(0)
    lu["area_m2"] = lu.geometry.area
    rp = lu.geometry.representative_point()
    pts = gpd.GeoDataFrame(lu[["OBJECTID"]], geometry=rp, crs=3414)
    j = gpd.sjoin(pts, sz[["zone", "geometry"]], predicate="within", how="left").drop_duplicates("OBJECTID")
    lu["zone"] = j.set_index("OBJECTID").loc[lu.OBJECTID, "zone"].values
    miss = lu.zone.isna()
    if miss.any():  # points on the coast or slivers: nearest subzone
        near = gpd.sjoin_nearest(pts[miss.values], sz[["zone", "geometry"]], how="left").drop_duplicates("OBJECTID")
        lu.loc[miss, "zone"] = near.set_index("OBJECTID").loc[lu.OBJECTID[miss], "zone"].values
    lu["zone"] = lu.zone.astype(int)
    lu["gpr_num"] = pd.to_numeric(lu.GPR, errors="coerce")
    lu["x"], lu["y"] = rp.x.values, rp.y.values
    # floor-area estimate used only for weights and the centroid: numeric GPR x site area; LND (landed) 1.4 and
    # other codes 1.0 are assumptions (stated in config/model.json, landuse_gfa_defaults)
    gpr_est = lu.gpr_num.copy()
    gpr_est[lu.GPR == "LND"] = 1.4
    gpr_est = gpr_est.fillna(1.0)
    skip = lu.LU_DESC.isin(["ROAD", "WATERBODY", "PARK", "OPEN SPACE", "BEACH AREA", "CEMETERY", "RESERVE SITE",
                            "AGRICULTURE", "SPORTS & RECREATION", "MASS RAPID TRANSIT", "LIGHT RAPID TRANSIT"])
    lu["gfa_est_m2"] = np.where(skip, 0.0, lu.area_m2 * gpr_est)
    # the GFA components are kept apart so that the pipeline applies its own (stated) defaults
    lu["gfa_numeric"] = np.where(lu.gpr_num.notna(), lu.area_m2 * lu.gpr_num.fillna(0), 0.0)
    lu["area_landed"] = np.where(lu.GPR == "LND", lu.area_m2, 0.0)
    lu["area_other_code"] = np.where(lu.gpr_num.isna() & (lu.GPR != "LND"), lu.area_m2, 0.0)
    agg = lu.groupby(["zone", "LU_DESC"]).agg(parcels=("OBJECTID", "size"), site_area_m2=("area_m2", "sum"),
                                              gfa_numeric_gpr_m2=("gfa_numeric", "sum"),
                                              site_area_gpr_lnd_m2=("area_landed", "sum"),
                                              site_area_gpr_other_code_m2=("area_other_code", "sum")
                                              ).reset_index().rename(columns={"LU_DESC": "lu_desc"})
    for c in ["site_area_m2", "gfa_numeric_gpr_m2", "site_area_gpr_lnd_m2", "site_area_gpr_other_code_m2"]:
        agg[c] = agg[c].round(1)
    agg.sort_values(["zone", "lu_desc"]).to_csv(OUT / "landuse_subzone.csv", index=False, lineterminator="\n")

    # Tengah parcels (2030 build-out scenario)
    tz = set(sz.zone[sz.PLN_AREA_N == "TENGAH"])
    t = lu[lu.zone.isin(tz) & ~skip].copy()
    t = t.sort_values("OBJECTID")
    write_csv(OUT / "tengah_parcels.csv", ["ura_objectid", "zone", "lu_desc", "gpr", "site_area_m2", "x", "y"],
              [[int(r.OBJECTID), int(r.zone), r.LU_DESC, r.GPR, r1(r.area_m2), r1(r.x), r1(r.y)]
               for r in t.itertuples()])
    return lu


# ---------------------------------------------------------------------------------------------------------------
# OpenStreetMap: roads and rail stations
# ---------------------------------------------------------------------------------------------------------------
def _iter_osm(path: Path, tags: tuple[str, ...]):
    with gzip.open(path, "rb") as fh:
        for ev, el in ET.iterparse(fh, events=("end",)):
            if el.tag in tags:
                yield el
                el.clear()
            elif el.tag in ("node", "way", "relation"):
                el.clear()


def parse_osm():
    path = RAW / "Singapore.osm.gz"
    keep = set(ROAD_CLASSES)
    ways, station_ways, station_nodes, signal_nodes = [], [], [], set()
    for el in _iter_osm(path, ("node", "way")):
        if el.tag == "node":
            t = {c.get("k"): c.get("v") for c in el.findall("tag")}
            if not t:
                continue
            if t.get("highway") == "traffic_signals":
                signal_nodes.add(int(el.get("id")))
            if t.get("railway") == "station" or t.get("public_transport") == "station":
                station_nodes.append((int(el.get("id")), float(el.get("lat")), float(el.get("lon")), t))
            continue
        t = {c.get("k"): c.get("v") for c in el.findall("tag")}
        nd = [int(c.get("ref")) for c in el.findall("nd")]
        if t.get("highway") in keep and t.get("area") != "yes":
            ways.append((int(el.get("id")), nd, t))
        elif t.get("railway") == "station" or t.get("public_transport") == "station":
            station_ways.append((int(el.get("id")), nd, t))
    need = {n for _, nd, _ in ways for n in nd} | {n for _, nd, _ in station_ways for n in nd}
    coords = {}
    for el in _iter_osm(path, ("node",)):
        i = int(el.get("id"))
        if i in need:
            coords[i] = (float(el.get("lon")), float(el.get("lat")))
    return ways, station_ways, station_nodes, signal_nodes, coords


def _first_int(v):
    if v is None:
        return None
    m = re.findall(r"\d+", str(v))
    return int(m[0]) if m else None


def _maxspeed(v):
    if v is None:
        return None
    m = re.match(r"^\s*(\d+)\s*(mph)?", str(v))
    if not m:
        return None
    s = int(m.group(1))
    return round(s * 1.609) if m.group(2) else s


def roads(ways, signal_nodes, coords, sg_poly):
    from pyproj import Transformer
    from shapely.geometry import Point
    from shapely.prepared import prep

    tr = Transformer.from_crs(4326, 3414, always_xy=True)
    ids = np.array(sorted(coords))
    lon = np.array([coords[i][0] for i in ids])
    lat = np.array([coords[i][1] for i in ids])
    X, Y = tr.transform(lon, lat)
    xy = {int(i): (float(a), float(b)) for i, a, b in zip(ids, X, Y)}
    inside_poly = prep(sg_poly.buffer(50.0))
    inside = {i: inside_poly.contains(Point(*xy[i])) for i in xy}

    use = defaultdict(int)
    for _, nd, _ in ways:
        for k, n in enumerate(nd):
            use[n] += 2 if k in (0, len(nd) - 1) else 1
    # segments between topological nodes
    segs = []
    for wid, nd, t in ways:
        hw = t["highway"]
        ow = t.get("oneway", "")
        if ow in ("yes", "true", "1"):
            dirs = (1,)
        elif ow in ("-1", "reverse"):
            dirs = (-1,)
        elif ow == "no":
            dirs = (1, -1)
        elif hw in ("motorway", "motorway_link") or t.get("junction") in ("roundabout", "circular"):
            dirs = (1,)
        else:
            dirs = (1, -1)
        lanes = _first_int(t.get("lanes"))
        lf, lb = _first_int(t.get("lanes:forward")), _first_int(t.get("lanes:backward"))
        ms = _maxspeed(t.get("maxspeed"))
        start = 0
        for k in range(1, len(nd)):
            if use[nd[k]] >= 2 or k == len(nd) - 1:
                chain = nd[start:k + 1]
                start = k
                if len(chain) < 2 or chain[0] == chain[-1] or not all(inside.get(n, False) for n in chain):
                    continue
                for d in dirs:
                    c = chain if d == 1 else chain[::-1]
                    if len(dirs) == 1:
                        ln, src = (lanes, "tag") if lanes else (None, "default")
                    else:
                        side = lf if d == 1 else lb
                        if side:
                            ln, src = side, "tag"
                        elif lanes:
                            ln, src = max(1, int(math.ceil(lanes / 2))), "tag/2"
                        else:
                            ln, src = None, "default"
                    segs.append({"nodes": c, "highway": hw, "lanes": ln, "lanes_src": src, "maxspeed": ms,
                                 "oneway": int(len(dirs) == 1), "name": t.get("name", ""), "ref": t.get("ref", ""),
                                 "way": wid})

    def seg_len(c):
        return sum(math.dist(xy[a], xy[b]) for a, b in zip(c[:-1], c[1:]))

    # contract degree-2 chains with identical attributes
    def attrs(s):
        return (s["highway"], s["lanes"], s["maxspeed"], s["oneway"])

    live = {i: s for i, s in enumerate(segs)}
    out_by, in_by = defaultdict(set), defaultdict(set)
    for i, s in live.items():
        out_by[s["nodes"][0]].add(i)
        in_by[s["nodes"][-1]].add(i)
    keep_nodes = set(signal_nodes)
    changed = True
    while changed:
        changed = False
        for v in list(in_by):
            if v in keep_nodes:
                continue
            ins, outs = list(in_by[v]), list(out_by[v])
            nb = {live[i]["nodes"][0] for i in ins} | {live[i]["nodes"][-1] for i in outs}
            pairs = None
            if len(ins) == 1 and len(outs) == 1 and len(nb) == 2:
                pairs = [(ins[0], outs[0])]
            elif len(ins) == 2 and len(outs) == 2 and len(nb) == 2:
                u, w = sorted(nb)
                a = [i for i in ins if live[i]["nodes"][0] == u]
                b = [i for i in outs if live[i]["nodes"][-1] == w]
                c = [i for i in ins if live[i]["nodes"][0] == w]
                d = [i for i in outs if live[i]["nodes"][-1] == u]
                if len(a) == len(b) == len(c) == len(d) == 1:
                    pairs = [(a[0], b[0]), (c[0], d[0])]
            if not pairs or not all(attrs(live[i]) == attrs(live[o]) for i, o in pairs):
                continue
            if any(live[i]["nodes"][0] == live[o]["nodes"][-1] for i, o in pairs):
                continue
            for i, o in pairs:
                s_in, s_out = live[i], live.pop(o)
                s_in["nodes"] = s_in["nodes"] + s_out["nodes"][1:]
                if not s_in["name"]:
                    s_in["name"] = s_out["name"]
                if not s_in["ref"]:
                    s_in["ref"] = s_out["ref"]
                in_by[v].discard(i)
                out_by[v].discard(o)
                end = s_in["nodes"][-1]
                in_by[end].discard(o)
                in_by[end].add(i)
            if not in_by[v] and not out_by[v]:
                del in_by[v]
                out_by.pop(v, None)
            changed = True
    segs = list(live.values())
    # split parallel links (same end nodes) at a middle vertex so every directed node pair is unique
    seen = set()
    final = []
    for s in sorted(segs, key=lambda s: (s["nodes"][0], s["nodes"][-1], len(s["nodes"]), s["way"])):
        key = (s["nodes"][0], s["nodes"][-1])
        if key not in seen:
            seen.add(key)
            final.append(s)
            continue
        if len(s["nodes"]) < 3:
            continue  # duplicate straight segment: drop
        m = len(s["nodes"]) // 2
        for part in (s["nodes"][: m + 1], s["nodes"][m:]):
            k2 = (part[0], part[-1])
            if k2 in seen:
                continue
            seen.add(k2)
            final.append({**s, "nodes": part})
    # largest strongly connected component
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    node_ids = sorted({s["nodes"][0] for s in final} | {s["nodes"][-1] for s in final})
    idx = {n: k for k, n in enumerate(node_ids)}
    a = np.array([idx[s["nodes"][0]] for s in final])
    b = np.array([idx[s["nodes"][-1]] for s in final])
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(node_ids), len(node_ids))).tocsr()
    ncomp, lab = connected_components(g, directed=True, connection="strong")
    big = np.bincount(lab).argmax()
    keep_mask = (lab[a] == big) & (lab[b] == big)
    total_km = sum(seg_len(s["nodes"]) for s in final) / 1000
    final = [s for s, k in zip(final, keep_mask) if k]
    kept_km = sum(seg_len(s["nodes"]) for s in final) / 1000
    node_ids = sorted({s["nodes"][0] for s in final} | {s["nodes"][-1] for s in final})
    nid = {n: k + 1 for k, n in enumerate(node_ids)}
    write_csv(OUT / "road_nodes.csv", ["node", "osm_node", "x", "y", "traffic_signals"],
              [[nid[n], n, r1(xy[n][0]), r1(xy[n][1]), int(n in signal_nodes)] for n in node_ids])
    final.sort(key=lambda s: (nid[s["nodes"][0]], nid[s["nodes"][-1]]))
    rows, geom = [], []
    from shapely.geometry import LineString

    for k, s in enumerate(final, 1):
        rows.append([k, nid[s["nodes"][0]], nid[s["nodes"][-1]], round(seg_len(s["nodes"]), 1), s["highway"],
                     s["lanes"] if s["lanes"] else "", s["lanes_src"], s["maxspeed"] if s["maxspeed"] else "",
                     s["oneway"], s["name"], s["ref"], s["way"]])
        ls = LineString([xy[n] for n in s["nodes"]]).simplify(10.0)
        geom.append([[round(x), round(y)] for x, y in ls.coords])
    write_csv(OUT / "road_links.csv", ["link", "a", "b", "length_m", "highway", "lanes_tag", "lanes_src",
                                       "maxspeed_tag_kmh", "oneway_way", "name", "ref", "osm_way"], rows)
    write_json(OUT / "road_geometry.json", {"crs": "EPSG:3414 (SVY21), metres; simplified 10 m; index = link - 1",
                                            "source": "OpenStreetMap contributors (ODbL)", "links": geom})
    return {"ways": len(ways), "links": len(final), "nodes": len(node_ids), "components": int(ncomp),
            "km_all": round(total_km, 1), "km_kept": round(kept_km, 1)}


def rail(station_ways, station_nodes, coords):
    from pyproj import Transformer

    tr = Transformer.from_crs(4326, 3414, always_xy=True)
    rows = {}
    feats = [(("node", i), lat, lon, t) for i, lat, lon, t in station_nodes]
    for wid, nd, t in station_ways:
        pts = [coords[n] for n in nd if n in coords]
        if pts:
            feats.append((("way", wid), float(np.mean([p[1] for p in pts])), float(np.mean([p[0] for p in pts])), t))
    named = {}
    for (kind, i), lat, lon, t in feats:
        if t.get("station") in ("monorail",) or t.get("railway") == "tram_stop":
            continue
        x, y = tr.transform(lon, lat)
        nm = t.get("name", "").strip()
        if nm and (nm.upper() not in named or kind == "node"):
            named[nm.upper()] = [nm, r1(x), r1(y), t.get("railway", ""), t.get("ref", ""), kind, i]
        for code in re.split(r"[;/,\s]+", t.get("ref", "")):
            code = code.strip().upper()
            if not re.fullmatch(r"[A-Z]{2,3}\d{0,2}[A-Z]?|STC|PTC", code):
                continue
            # prefer a node over a way, and the first feature found
            if code in rows and rows[code][5] == "node":
                continue
            rows[code] = [code, t.get("name", ""), r1(x), r1(y), t.get("railway", ""), kind, i]
    write_csv(OUT / "rail_stations_osm.csv", ["code", "name", "x", "y", "osm_railway_tag", "osm_type", "osm_id"],
              [rows[k] for k in sorted(rows)])
    write_csv(OUT / "rail_station_names_osm.csv", ["name", "x", "y", "osm_railway_tag", "ref", "osm_type", "osm_id"],
              [named[k] for k in sorted(named)])
    return len(rows)


def lta_exits():
    """Station positions from LTA's MRT station exits: the mean of each station's exits."""
    import geopandas as gpd

    ex = gpd.read_file(RAW / "lta_mrt_station_exit.geojson").to_crs(3414)
    ex["x"], ex["y"] = ex.geometry.x, ex.geometry.y
    g = ex.groupby("STATION_NA").agg(exits=("EXIT_CODE", "size"), x=("x", "mean"), y=("y", "mean")).reset_index()
    write_csv(OUT / "lta_station_positions.csv", ["station", "exits", "x", "y"],
              [[r.STATION_NA, int(r.exits), r1(r.x), r1(r.y)] for r in g.itertuples()])
    return len(g)


# ---------------------------------------------------------------------------------------------------------------
# bus origin-destination (LTA DataMall)
# ---------------------------------------------------------------------------------------------------------------
def bus(sz, datamall: Path):
    import geopandas as gpd

    stops = pd.DataFrame(json.loads((datamall / "BusStops_20260926.json").read_text(encoding="utf-8")))
    pts = gpd.GeoDataFrame(stops, geometry=gpd.points_from_xy(stops.Longitude, stops.Latitude), crs=4326).to_crs(3414)
    j = gpd.sjoin(pts, sz[["zone", "geometry"]], predicate="within", how="left").drop_duplicates("BusStopCode")
    stop_zone = dict(zip(j.BusStopCode, j.zone))
    sx = dict(zip(j.BusStopCode, j.geometry.x))
    sy = dict(zip(j.BusStopCode, j.geometry.y))
    out = {"stops": len(stops), "stops_outside_zones": int(j.zone.isna().sum())}
    for ym in BUS_MONTHS:
        f = datamall / f"origin_destination_bus_{ym}.csv"
        df = pd.read_csv(f, usecols=["YEAR_MONTH", "DAY_TYPE", "TIME_PER_HOUR", "ORIGIN_PT_CODE",
                                     "DESTINATION_PT_CODE", "TOTAL_TRIPS"],
                         dtype={"YEAR_MONTH": str, "DAY_TYPE": str, "TIME_PER_HOUR": "int16", "ORIGIN_PT_CODE": str,
                                "DESTINATION_PT_CODE": str, "TOTAL_TRIPS": "int64"})
        df = df[df.DAY_TYPE == "WEEKDAY"]
        df["o"] = df.ORIGIN_PT_CODE.str.zfill(5).map(stop_zone)
        df["d"] = df.DESTINATION_PT_CODE.str.zfill(5).map(stop_zone)
        hourly = df.groupby("TIME_PER_HOUR").TOTAL_TRIPS.sum()
        write_csv(OUT / f"bus_hourly_{ym}.csv", ["hour", "weekday_trips_month_total"],
                  [[int(h), int(v)] for h, v in hourly.items()])
        unk = df.o.isna() | df.d.isna()
        out[f"{ym}_weekday_trips"] = int(df.TOTAL_TRIPS.sum())
        out[f"{ym}_trips_stop_not_in_zone"] = int(df.TOTAL_TRIPS[unk].sum())
        k = df[~unk & df.TIME_PER_HOUR.isin(BUS_HOURS)].copy()
        k["o"], k["d"] = k.o.astype(int), k.d.astype(int)
        od = k.groupby(["TIME_PER_HOUR", "o", "d"]).TOTAL_TRIPS.sum().reset_index()
        write_csv(OUT / f"bus_od_{ym}.csv", ["hour", "o_zone", "d_zone", "weekday_trips_month_total"],
                  od.itertuples(index=False))
        # stop-to-stop straight-line trip lengths (context; the model works with zone-to-zone costs)
        oc = k.ORIGIN_PT_CODE.str.zfill(5)
        dc = k.DESTINATION_PT_CODE.str.zfill(5)
        dist = np.hypot(oc.map(sx).values - dc.map(sx).values, oc.map(sy).values - dc.map(sy).values) / 1000
        bins = np.arange(0, 41, 1.0)
        rows = []
        for h in BUS_HOURS:
            m = (k.TIME_PER_HOUR == h).values
            hist, _ = np.histogram(dist[m], bins=bins, weights=k.TOTAL_TRIPS.values[m])
            over = k.TOTAL_TRIPS.values[m][dist[m] >= bins[-1]].sum()
            rows += [[h, f"{lo:g}", f"{hi:g}", int(v)] for lo, hi, v in zip(bins[:-1], bins[1:], hist)]
            rows.append([h, f"{bins[-1]:g}", "inf", int(over)])
        write_csv(OUT / f"bus_stop_tld_{ym}.csv", ["hour", "km_from", "km_to", "weekday_trips_month_total"], rows)
    return out


# ---------------------------------------------------------------------------------------------------------------
def manifest(extra: dict):
    rows = []
    for p in sorted(OUT.iterdir()):
        if p.name in ("manifest.csv", "raw_sources.csv"):
            continue
        b = p.read_bytes().replace(b"\r\n", b"\n")
        rows.append([p.name, hashlib.sha256(b).hexdigest(), len(b)])
    write_csv(OUT / "manifest.csv", ["file", "sha256_lf", "bytes"], rows)
    raw = pd.read_csv(RAW / "manifest.csv", dtype=str)
    raw = pd.concat([raw, pd.DataFrame(extra.get("datamall_rows", []))], ignore_index=True)
    raw.to_csv(OUT / "raw_sources.csv", index=False, lineterminator="\n")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def main(datamall: Path, steps: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sz = zones()
    report = {}
    if "census" in steps:
        census(sz)
    if "landuse" in steps or "zones" in steps:
        lu = landuse(sz)
        write_zones(sz, lu)
    if "roads" in steps or "rail" in steps:
        ways, station_ways, station_nodes, signal_nodes, coords = parse_osm()
        sg = sz.geometry.union_all() if hasattr(sz.geometry, "union_all") else sz.geometry.unary_union
        if "roads" in steps:
            report["roads"] = roads(ways, signal_nodes, coords, sg)
        if "rail" in steps:
            report["rail_codes"] = rail(station_ways, station_nodes, coords)
    if "rail" in steps:
        report["lta_stations"] = lta_exits()
    extra = {}
    if "bus" in steps:
        report["bus"] = bus(sz, datamall)
    files = ["BusStops_20260926.json"] + [f"origin_destination_bus_{m}.csv" for m in BUS_MONTHS]
    extra["datamall_rows"] = [{"file": f"datamall/{f}", "title": f"LTA DataMall: {f}",
                               "source": "LTA DataMall API (Bus Stops; Passenger Volume by Origin Destination Bus "
                                         "Stops). Read from a local folder downloaded earlier with the owner's own "
                                         "AccountKey; not redistributed",
                               "retrieved": "2026-09-26", "how": "read in place",
                               "bytes": (datamall / f).stat().st_size, "sha256": sha256_file(datamall / f)}
                              for f in files if (datamall / f).exists()]
    if report:
        prev = {}
        rp = OUT / "prepare_report.json"
        if rp.exists():
            prev = json.loads(rp.read_text(encoding="utf-8"))
        prev.update(report)
        rp.write_text(json.dumps(prev, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    manifest(extra)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--datamall-dir", default=str(RAW / "datamall"))
    ap.add_argument("--steps", default="census,landuse,zones,roads,rail,bus")
    a = ap.parse_args()
    main(Path(a.datamall_dir), a.steps.split(","))
