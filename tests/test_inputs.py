"""Integrity of the committed inputs and configuration."""
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
INP = REPO / "data" / "inputs"
LABELS = {"REAL", "DERIVED", "ASSUMPTION", "ILLUSTRATIVE", "SYNTHETIC"}


def test_manifest_hashes_match_committed_inputs():
    rows = list(csv.DictReader((INP / "manifest.csv").open(encoding="utf-8", newline="")))
    assert len(rows) >= 20
    for r in rows:
        b = (INP / r["file"]).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(b).hexdigest() == r["sha256_lf"], r["file"]
        assert len(b) == int(r["bytes"]), r["file"]


def _walk(d, path=""):
    for k, v in d.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and "value" in v:
            yield f"{path}{k}", v
        elif isinstance(v, dict):
            yield from _walk(v, f"{path}{k}.")


def test_every_parameter_is_labelled():
    cfg = json.loads((REPO / "config" / "model.json").read_text(encoding="utf-8"))
    items = list(_walk(cfg))
    assert len(items) > 40
    for name, v in items:
        assert v.get("label") in LABELS, name
        if v["label"] == "REAL":
            assert v.get("note"), f"{name}: a REAL value needs its source"


def test_rail_stations_resolve_to_published_positions():
    rail = json.loads((REPO / "config" / "rail.json").read_text(encoding="utf-8"))
    lta = set(pd.read_csv(INP / "lta_station_positions.csv").station)
    for lname, ln in rail["lines"].items():
        suffix = ln.get("lta_suffix", "MRT")
        for code, name in ln["stations"]:
            key = rail["lta_name_overrides"].get(code, f"{name.upper()} {suffix} STATION")
            assert key in lta, (lname, code, key)
    jrl_codes = {c for ln in rail["jrl"]["lines"].values() for c, _ in ln["stations"]}
    assert len(jrl_codes) == 24 and "JS2A" not in jrl_codes


def test_no_raw_datamall_rows_are_committed():
    od = pd.read_csv(INP / "bus_od_202608.csv")
    assert list(od.columns) == ["hour", "o_zone", "d_zone", "weekday_trips_month_total"]
    assert od.o_zone.max() <= 332 and od.d_zone.max() <= 332


def test_text_files_use_lf():
    files = list(INP.glob("*.csv")) + list(INP.glob("*.json")) + list((REPO / "results").glob("*.csv"))
    files += list((REPO / "results").glob("*.json")) + [REPO / "README.md"] + list((REPO / "docs").glob("*.md"))
    files += list((REPO / "config").glob("*.json"))
    for p in files:
        assert b"\r\n" not in p.read_bytes(), p.name
