"""Shortest paths, all-or-nothing loading and skims on a directed graph in compressed (CSR) form.

The graph is given by link arrays ``tail`` and ``head`` (node indices) and a link cost array. ``Graph`` builds the
forward star (links sorted by tail) once; costs can change between calls.

Dijkstra uses a binary heap with lazy deletion. The order in which nodes are settled is a topological order of
the shortest-path tree, so loading walks that order backwards: each node passes the demand of its subtree to its
predecessor link. All functions are compiled with numba; origins are processed in parallel chunks, each chunk
with its own flow array, and the chunks are summed at the end (no shared writes).
"""
from __future__ import annotations

import numpy as np
from numba import njit, prange

INF = np.inf


class Graph:
    """Directed graph with ``n_nodes`` nodes and links ``tail[k] -> head[k]``."""

    def __init__(self, tail: np.ndarray, head: np.ndarray, n_nodes: int):
        tail = np.asarray(tail, dtype=np.int64)
        head = np.asarray(head, dtype=np.int64)
        if tail.shape != head.shape:
            raise ValueError("tail and head must have the same length")
        if tail.size and (tail.min() < 0 or head.min() < 0 or max(tail.max(), head.max()) >= n_nodes):
            raise ValueError("node index out of range")
        self.n_nodes = int(n_nodes)
        self.n_links = int(tail.size)
        self.tail = tail
        self.head = head
        order = np.argsort(tail, kind="stable")
        self.fs_link = order.astype(np.int64)  # links in forward-star order
        counts = np.bincount(tail, minlength=n_nodes)
        self.indptr = np.zeros(n_nodes + 1, dtype=np.int64)
        np.cumsum(counts, out=self.indptr[1:])


@njit(cache=True)
def _heap_push(hk, hv, size, key, val):
    i = size
    hk[i] = key
    hv[i] = val
    while i > 0:
        p = (i - 1) // 2
        if hk[p] <= hk[i]:
            break
        hk[p], hk[i] = hk[i], hk[p]
        hv[p], hv[i] = hv[i], hv[p]
        i = p
    return size + 1


@njit(cache=True)
def _heap_pop(hk, hv, size):
    key = hk[0]
    val = hv[0]
    size -= 1
    hk[0] = hk[size]
    hv[0] = hv[size]
    i = 0
    while True:
        l = 2 * i + 1
        if l >= size:
            break
        r = l + 1
        c = l
        if r < size and hk[r] < hk[l]:
            c = r
        if hk[i] <= hk[c]:
            break
        hk[i], hk[c] = hk[c], hk[i]
        hv[i], hv[c] = hv[c], hv[i]
        i = c
    return key, val, size


@njit(cache=True)
def _dijkstra(src, indptr, fs_link, head, cost, dist, pred, order, hk, hv):
    """Fill dist (cost from src), pred (predecessor link, -1 for none) and order (settle order).
    Returns the number of settled nodes. dist must be +inf and pred -1 on entry."""
    dist[src] = 0.0
    size = _heap_push(hk, hv, 0, 0.0, src)
    n_set = 0
    while size > 0:
        d, u, size = _heap_pop(hk, hv, size)
        if d > dist[u]:
            continue  # stale entry: u was pushed again with a smaller cost
        order[n_set] = u
        n_set += 1
        for q in range(indptr[u], indptr[u + 1]):
            k = fs_link[q]
            v = head[k]
            nd = d + cost[k]
            if nd < dist[v]:
                dist[v] = nd
                pred[v] = k
                size = _heap_push(hk, hv, size, nd, v)
    return n_set


@njit(parallel=True, cache=True)
def _aon(origins, dest_nodes, demand, indptr, fs_link, head, tail, cost, n_nodes, n_chunks):
    """All-or-nothing loading of demand[o, d] (origins[o] -> dest_nodes[d]).
    Returns (link flows, sum of demand x shortest-path cost, number of OD pairs with demand but no path)."""
    n_links = cost.size
    n_o = origins.size
    flows = np.zeros((n_chunks, n_links))
    sptt = np.zeros(n_chunks)
    unreach = np.zeros(n_chunks, dtype=np.int64)
    per = (n_o + n_chunks - 1) // n_chunks
    for c in prange(n_chunks):
        dist = np.empty(n_nodes)
        pred = np.empty(n_nodes, dtype=np.int64)
        order = np.empty(n_nodes, dtype=np.int64)
        node_flow = np.zeros(n_nodes)
        hk = np.empty(n_links + 1)
        hv = np.empty(n_links + 1, dtype=np.int64)
        for o in range(c * per, min(n_o, (c + 1) * per)):
            tot = 0.0
            for d in range(dest_nodes.size):
                tot += demand[o, d]
            if tot <= 0.0:
                continue
            dist[:] = INF
            pred[:] = -1
            n_set = _dijkstra(origins[o], indptr, fs_link, head, cost, dist, pred, order, hk, hv)
            node_flow[:] = 0.0
            for d in range(dest_nodes.size):
                q = demand[o, d]
                if q > 0.0:
                    v = dest_nodes[d]
                    if dist[v] == INF:
                        unreach[c] += 1
                        continue
                    node_flow[v] += q
                    sptt[c] += q * dist[v]
            for i in range(n_set - 1, 0, -1):
                v = order[i]
                f = node_flow[v]
                if f != 0.0:
                    k = pred[v]
                    flows[c, k] += f
                    node_flow[tail[k]] += f
    out = np.zeros(n_links)
    for c in range(n_chunks):
        out += flows[c]
    return out, sptt.sum(), unreach.sum()


@njit(parallel=True, cache=True)
def _skim(origins, dest_nodes, indptr, fs_link, head, tail, cost, extra, n_nodes):
    """Shortest-path cost and the sum of ``extra`` along that path, origins x dest_nodes."""
    n_o = origins.size
    n_d = dest_nodes.size
    n_links = cost.size
    c_out = np.empty((n_o, n_d))
    e_out = np.empty((n_o, n_d))
    for o in prange(n_o):
        dist = np.empty(n_nodes)
        pred = np.empty(n_nodes, dtype=np.int64)
        order = np.empty(n_nodes, dtype=np.int64)
        acc = np.zeros(n_nodes)
        hk = np.empty(n_links + 1)
        hv = np.empty(n_links + 1, dtype=np.int64)
        dist[:] = INF
        pred[:] = -1
        n_set = _dijkstra(origins[o], indptr, fs_link, head, cost, dist, pred, order, hk, hv)
        acc[order[0]] = 0.0
        for i in range(1, n_set):
            v = order[i]
            k = pred[v]
            acc[v] = acc[tail[k]] + extra[k]
        for d in range(n_d):
            v = dest_nodes[d]
            c_out[o, d] = dist[v]
            e_out[o, d] = acc[v] if dist[v] < INF else INF
    return c_out, e_out


def shortest_path_tree(g: Graph, cost: np.ndarray, src: int):
    """(dist, predecessor link) from one source; used by tests and the junction tools."""
    dist = np.full(g.n_nodes, np.inf)
    pred = np.full(g.n_nodes, -1, dtype=np.int64)
    order = np.empty(g.n_nodes, dtype=np.int64)
    hk = np.empty(g.n_links + 1)
    hv = np.empty(g.n_links + 1, dtype=np.int64)
    _dijkstra(int(src), g.indptr, g.fs_link, g.head, np.asarray(cost, dtype=np.float64), dist, pred, order, hk, hv)
    return dist, pred


def aon(g: Graph, cost: np.ndarray, origins: np.ndarray, dest_nodes: np.ndarray, demand: np.ndarray,
        n_chunks: int = 16):
    """All-or-nothing assignment. Returns (link flows, SPTT = sum of demand x shortest cost).
    Raises if any OD pair with demand has no path."""
    cost = np.asarray(cost, dtype=np.float64)
    if np.any(cost < 0) or not np.all(np.isfinite(cost)):
        raise ValueError("link costs must be finite and non-negative")
    demand = np.ascontiguousarray(demand, dtype=np.float64)
    # small problems run in one chunk: thread start-up would cost more than the work (results do not depend on it
    # beyond floating-point summation order, which is fixed for a given problem size)
    n_chunks = 1 if len(origins) < 64 else max(1, min(n_chunks, len(origins)))
    flows, sptt, unreach = _aon(np.asarray(origins, dtype=np.int64), np.asarray(dest_nodes, dtype=np.int64), demand,
                                g.indptr, g.fs_link, g.head, g.tail, cost, g.n_nodes, n_chunks)
    if unreach:
        raise ValueError(f"{unreach} OD pairs with demand have no path")
    return flows, float(sptt)


def skim(g: Graph, cost: np.ndarray, origins: np.ndarray, dest_nodes: np.ndarray, extra: np.ndarray | None = None):
    """Matrices of shortest-path cost and of ``extra`` (for example length) summed along those paths."""
    cost = np.asarray(cost, dtype=np.float64)
    extra = cost if extra is None else np.asarray(extra, dtype=np.float64)
    return _skim(np.asarray(origins, dtype=np.int64), np.asarray(dest_nodes, dtype=np.int64), g.indptr, g.fs_link,
                 g.head, g.tail, cost, extra, g.n_nodes)
