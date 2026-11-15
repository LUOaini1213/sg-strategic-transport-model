"""Download the raw public inputs into data/raw/ (git-ignored) and record them in data/raw/manifest.csv.

Everything fetched here is keyless:

* data.gov.sg (v1 poll-download API): URA Master Plan 2019 subzone and planning-area boundaries and land use;
  SingStat Census of Population 2020 tables published on data.gov.sg.
* SingStat Table Builder API: two Census of Population 2020 subzone tables that are fetched from SingStat directly.
* BBBike's weekly OpenStreetMap extract for Singapore (roads and rail stations).
* The Sioux Falls test network from github.com/bstabler/TransportationNetworks at a pinned commit. Its README
  says the data sets are "for academic research purposes only", so the files are downloaded, never committed.

LTA DataMall files (bus origin-destination volumes, bus stops) are NOT downloaded: DataMall needs a personal
AccountKey and none is configured for this repository. Download "Passenger Volume by Origin Destination Bus Stops"
(July and August 2026) and "Bus Stops" yourself and pass the folder to scripts/prepare_inputs.py with
--datamall-dir.

    python scripts/fetch_data.py [--force] [--cache DIR ...] [--only sioux_falls]

--cache DIR: before downloading a file, look for a file with the same name (or a known alias) in DIR and copy it
instead. The manifest then records that the bytes came from a local copy.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = RAW / "manifest.csv"
HDR = {"User-Agent": "sg-strategic-transport-model/0.1 (personal desk study)"}

DATAGOV = {
    # file name: (dataset id, title, aliases used by other local folders)
    "mp2019_subzone.geojson": ("d_8594ae9ff96d0c708bc2af633048edfb",
                               "URA: Master Plan 2019 Subzone Boundary (No Sea)", ["subzone.geojson"]),
    "mp2019_planning_area.geojson": ("d_4765db0e87b9c86336792efe8a1f7a66",
                                     "URA: Master Plan 2019 Planning Area Boundary (No Sea)", ["pa.geojson"]),
    "mp2019_land_use.geojson": ("d_90d86daa5bfaa371668b84fa5f01424f", "URA: Master Plan 2019 Land Use layer",
                                ["mp19_landuse.geojson"]),
    "lta_mrt_station_exit.geojson": ("d_b39d3a0871985372d7e1637193335da5", "LTA: LTA MRT Station Exit (GEOJSON)",
                                     ["lta_mrt_exit.geojson"]),
    "census2020_mode_by_planning_area.csv": (
        "d_1f8f5ec7201964e365c77551cab99503",
        "SingStat: Employed Residents Aged 15 Years and Over by Planning Area of Residence and Usual Mode of "
        "Transport to Work (Census of Population 2020)", []),
    "census2020_workplace_mode_region.csv": (
        "d_5b38192e9c6f8d2c5f38c70939c76e71",
        "SingStat: Employed Residents Aged 15 Years and Over by Planning Area of Workplace, Usual Mode of Transport "
        "to Work and Planning Region of Residence (Census of Population 2020)", []),
}
SINGSTAT = {
    "singstat_17560_census2020_population_subzone_age_sex.json": (
        "17560", "SingStat Table Builder 17560: Resident Population by Planning Area/Subzone of Residence, Age Group "
                 "and Sex (Census of Population 2020)"),
    "singstat_17562_census2020_population_subzone_dwelling.json": (
        "17562", "SingStat Table Builder 17562: Resident Population by Planning Area/Subzone of Residence and Type "
                 "of Dwelling (Census of Population 2020)"),
}
BBBIKE = ("Singapore.osm.gz", "https://download.bbbike.org/osm/bbbike/Singapore/Singapore.osm.gz",
          "OpenStreetMap contributors (ODbL 1.0), BBBike weekly extract for Singapore")
TNTP_COMMIT = "977ee75c6906337c0c7d229a1336107c7cdb533e"
TNTP_FILES = ["SiouxFalls_net.tntp", "SiouxFalls_trips.tntp", "SiouxFalls_flow.tntp"]
# SHA-256 of the three files at the pinned commit, checked after every download.
TNTP_SHA256 = {
    "SiouxFalls_net.tntp": "ace99b24cec69c273ff0cf3d6d074110177f0cc0ae24b0c7a9f4f4cb5e27635c",
    "SiouxFalls_trips.tntp": "56f9566857f3f66730fd5c4232258d7ee3ac2931a476526331afd062f4958de7",
    "SiouxFalls_flow.tntp": "5d0b83a22ecc3ce79dabb2b2972162b78c5eda571dcb5b3687429d8397654fee",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(url: str, **kw):
    import requests

    for attempt in range(6):
        try:
            r = requests.get(url, headers=HDR, timeout=600, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


def datagov(ds: str) -> bytes:
    for _ in range(10):
        meta = _get(f"https://api-open.data.gov.sg/v1/public/api/datasets/{ds}/poll-download").json()
        url = (meta.get("data") or {}).get("url")
        if url:
            return _get(url).content
        time.sleep(3)
    raise RuntimeError(f"no download link for data.gov.sg dataset {ds}")


def main(force: bool = False, caches: list[str] | None = None, only: str | None = None) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    caches = [Path(c) for c in (caches or [])]
    log: dict[str, dict] = {}
    if MANIFEST.exists():
        with MANIFEST.open(encoding="utf-8", newline="") as fh:
            log = {r["file"]: r for r in csv.DictReader(fh)}
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M SGT")

    def record(name: str, source: str, title: str, how: str) -> None:
        p = RAW / name
        log[name] = {"file": name, "title": title, "source": source, "retrieved": now, "how": how,
                     "bytes": p.stat().st_size, "sha256": sha256(p)}
        print(f"{how:>10}  {name}")

    def from_cache(name: str, aliases: list[str]) -> Path | None:
        for c in caches:
            for n in [name, *aliases]:
                if (c / n).is_file():
                    return c / n
        return None

    def want(name: str) -> bool:
        return force or not (RAW / name).exists()

    if only in (None, "public"):
        for name, (ds, title, aliases) in DATAGOV.items():
            if want(name):
                src = from_cache(name, aliases)
                if src is not None:
                    shutil.copyfile(src, RAW / name)
                    how = f"copied from local file {src.name} (originally downloaded from data.gov.sg)"
                else:
                    (RAW / name).write_bytes(datagov(ds))
                    how = "downloaded"
                record(name, f"https://data.gov.sg/datasets/{ds}/view", title, how.split(" (")[0])
                log[name]["how"] = how
                time.sleep(1)
        for name, (tid, title) in SINGSTAT.items():
            if want(name):
                r = _get(f"https://tablebuilder.singstat.gov.sg/api/table/tabledata/{tid}", params={"limit": 5000})
                (RAW / name).write_bytes(r.content)
                record(name, f"https://tablebuilder.singstat.gov.sg/table/CT/{tid}", title, "downloaded")
        name, url, title = BBBIKE
        if want(name):
            src = from_cache(name, [])
            if src is not None:
                shutil.copyfile(src, RAW / name)
                record(name, url, title, "copied")
                log[name]["how"] = (f"copied from a local copy of the same extract (file date "
                                    f"{dt.datetime.fromtimestamp(src.stat().st_mtime):%Y-%m-%d})")
            else:
                (RAW / name).write_bytes(_get(url).content)
                record(name, url, title, "downloaded")
    if only in (None, "sioux_falls"):
        d = RAW / "sioux_falls"
        d.mkdir(exist_ok=True)
        for fn in TNTP_FILES:
            name = f"sioux_falls/{fn}"
            if want(name):
                url = f"https://raw.githubusercontent.com/bstabler/TransportationNetworks/{TNTP_COMMIT}/SiouxFalls/{fn}"
                (RAW / name).write_bytes(_get(url).content)
                if sha256(RAW / name) != TNTP_SHA256[fn]:
                    raise SystemExit(f"{name}: SHA-256 differs from the pinned commit")
                record(name, url, f"TransportationNetworks (bstabler), SiouxFalls/{fn} at commit {TNTP_COMMIT[:7]}; "
                                  "README: 'for academic research purposes only' (not redistributed)", "downloaded")

    with MANIFEST.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ["file", "title", "source", "retrieved", "how", "bytes", "sha256"],
                           lineterminator="\n")
        w.writeheader()
        for k in sorted(log):
            w.writerow(log[k])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="download again even if the file exists")
    ap.add_argument("--cache", action="append", help="folder with local copies to use instead of downloading")
    ap.add_argument("--only", choices=["public", "sioux_falls"], help="fetch only one group")
    a = ap.parse_args()
    main(a.force, a.cache, a.only)
