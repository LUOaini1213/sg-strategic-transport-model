"""Readers for the TNTP text format used by github.com/bstabler/TransportationNetworks."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .assignment import Network
from .paths import Graph


def read_net(path: Path) -> dict:
    rows = []
    started = False
    for line in Path(path).read_text().splitlines():
        if "<END OF METADATA>" in line:
            started = True
            continue
        if not started or not line.strip() or line.strip().startswith("~"):
            continue
        parts = line.strip().rstrip(";").split()
        rows.append([float(p) for p in parts[:10]])
    a = np.array(rows)
    return {"init": a[:, 0].astype(int), "term": a[:, 1].astype(int), "capacity": a[:, 2], "length": a[:, 3],
            "fftime": a[:, 4], "b": a[:, 5], "power": a[:, 6]}


def read_trips(path: Path, n_zones: int) -> np.ndarray:
    text = Path(path).read_text()
    od = np.zeros((n_zones, n_zones))
    for block in text.split("Origin")[1:]:
        head, _, body = block.partition("\n")
        o = int(head.strip())
        for d, v in re.findall(r"(\d+)\s*:\s*([0-9.eE+-]+)", body):
            od[o - 1, int(d) - 1] = float(v)
    return od


def read_flow(path: Path) -> dict:
    rows = []
    for line in Path(path).read_text().splitlines()[1:]:
        p = line.split()
        if len(p) >= 4:
            rows.append([float(p[0]), float(p[1]), float(p[2]), float(p[3])])
    a = np.array(rows)
    return {"init": a[:, 0].astype(int), "term": a[:, 1].astype(int), "volume": a[:, 2], "cost": a[:, 3]}


def network(net: dict) -> Network:
    n_nodes = int(max(net["init"].max(), net["term"].max()))
    g = Graph(net["init"] - 1, net["term"] - 1, n_nodes)
    return Network(graph=g, t0=net["fftime"].astype(float), capacity=net["capacity"].astype(float),
                   alpha=net["b"].astype(float), beta=net["power"].astype(float))
