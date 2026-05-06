"""
Assignment 4 - Part 2: Arbitrary Traffic Matrix
CS 536: Data Communication and Computer Networks, Spring 2026

Joint Topology Design + Multi-Commodity Flow Routing MILP
using the Gurobi Python API (gurobipy).

Given n=8 nodes each with d=4 incoming and d=4 outgoing directed links
(each of capacity 1), and a traffic matrix T drawn from the hose model,
find the topology that maximizes the concurrent flow lambda.

Formulation (MILP):
    max  lambda
    s.t.
        sum_{j!=i} x_{ij} = d                      for all i     (out-degree)
        sum_{i!=j} x_{ij} = d                      for all j     (in-degree)
        sum_{(s,t)} f_{ij}^{(s,t)} <= x_{ij}       for all i!=j  (capacity)
        flow conservation for each commodity (s,t)                 (MCF)
        x_{ij} in Z_>=0,  f_{ij}^{(s,t)} >= 0,  lambda >= 0

Usage:
    python max_concurrent_flow.py                   # default (300s limit)
    python max_concurrent_flow.py --time-limit 60   # custom time limit
    python max_concurrent_flow.py --verbose          # show Gurobi solver log

Requires: gurobipy (with academic license for full-size models)
          numpy
"""

import numpy as np
import gurobipy as gp
from gurobipy import GRB
import argparse
import time

# ────────────────────────── Parameters ────────────────────────────
N = 8   # number of nodes
D = 4   # in-degree = out-degree per node
DEFAULT_TIME_LIMIT = 300  # seconds


# ─────────────────── Traffic Matrix Generators ────────────────────

def uniform_traffic():
    """Uniform hose-model matrix: T[i][j] = d/(n-1) for i != j."""
    T = np.full((N, N), D / (N - 1))
    np.fill_diagonal(T, 0.0)
    return T


def concentrated_traffic():
    """All traffic from node 0 to node 1: T[0][1] = 4."""
    T = np.zeros((N, N))
    T[0][1] = D
    return T


def permutation_traffic():
    """Permutation matrix scaled by d: source i -> dest (i+1) mod n."""
    T = np.zeros((N, N))
    for i in range(N):
        T[i][(i + 1) % N] = D
    return T


def random_hose_traffic(seed=42):
    """
    Random hose-model matrix via iterative proportional fitting.
    Produces T >= 0 with T_ii = 0, row sums <= d, col sums <= d.
    """
    rng = np.random.default_rng(seed)
    T = rng.random((N, N))
    np.fill_diagonal(T, 0.0)
    for _ in range(200):
        row_sums = T.sum(axis=1, keepdims=True)
        row_sums = np.maximum(row_sums, 1e-12)
        T = T * np.minimum(1.0, D / row_sums)
        col_sums = T.sum(axis=0, keepdims=True)
        col_sums = np.maximum(col_sums, 1e-12)
        T = T * np.minimum(1.0, D / col_sums)
    np.fill_diagonal(T, 0.0)
    return T


# ──────────────────── MILP Solver (Gurobi) ────────────────────────

def solve(T, verbose=False, time_limit=DEFAULT_TIME_LIMIT):
    """
    Solve the joint topology-design + multi-commodity flow MILP
    using the Gurobi Python API.

    Parameters
    ----------
    T : np.ndarray, shape (N, N)
        Traffic matrix satisfying the hose model.
    verbose : bool
        If True, print full Gurobi solver log.
    time_limit : int
        Maximum solve time in seconds.

    Returns
    -------
    dict with keys: lambda, topology, flows, status, mip_gap
    """

    # Active commodities (skip zero-demand pairs)
    commodities = [(s, t) for s in range(N) for t in range(N)
                   if s != t and T[s][t] > 1e-12]

    # All directed edge pairs
    edges = [(i, j) for i in range(N) for j in range(N) if i != j]

    # ── Create model ──
    m = gp.Model("MaxConcurrentFlow_TopologyDesign")
    m.Params.OutputFlag = 1 if verbose else 0
    m.Params.TimeLimit = time_limit

    # ── Decision variables ──

    # x[i,j]: number of parallel directed links from i to j (integer)
    x = {}
    for (i, j) in edges:
        x[i, j] = m.addVar(vtype=GRB.INTEGER, lb=0, ub=D,
                            name=f"x_{i}_{j}")

    # f[i,j,s,t]: flow of commodity (s,t) on edge (i -> j)
    f = {}
    for (i, j) in edges:
        for (s, t) in commodities:
            f[i, j, s, t] = m.addVar(vtype=GRB.CONTINUOUS, lb=0,
                                      name=f"f_{i}_{j}_{s}_{t}")

    # lambda: throughput scaling factor
    lam = m.addVar(vtype=GRB.CONTINUOUS, lb=0, name="lambda")

    m.update()

    # ── Constraints ──

    # 1. Out-degree: each node has exactly d outgoing links
    for i in range(N):
        m.addConstr(
            gp.quicksum(x[i, j] for j in range(N) if j != i) == D,
            name=f"out_degree_{i}")

    # 2. In-degree: each node has exactly d incoming links
    for j in range(N):
        m.addConstr(
            gp.quicksum(x[i, j] for i in range(N) if i != j) == D,
            name=f"in_degree_{j}")

    # 3. Link capacity: total flow on edge <= number of links
    for (i, j) in edges:
        m.addConstr(
            gp.quicksum(f[i, j, s, t] for (s, t) in commodities) <= x[i, j],
            name=f"cap_{i}_{j}")

    # 4. Flow conservation for each commodity at each node
    for (s, t) in commodities:
        for v in range(N):
            outflow = gp.quicksum(f[v, j, s, t]
                                  for j in range(N) if j != v)
            inflow  = gp.quicksum(f[j, v, s, t]
                                  for j in range(N) if j != v)

            if v == s:
                rhs = T[s][t] * lam      # source generates lambda * T_st
            elif v == t:
                rhs = -T[s][t] * lam     # sink absorbs lambda * T_st
            else:
                rhs = 0.0                 # transit: flow in = flow out

            m.addConstr(outflow - inflow == rhs,
                        name=f"flow_{s}_{t}_at_{v}")

    # ── Objective ──
    m.setObjective(lam, GRB.MAXIMIZE)

    # ── Solve ──
    try:
        m.optimize()
    except gp.GurobiError as e:
        if "size-limited" in str(e) or "Model too large" in str(e):
            n_vars = len(x) + len(f) + 1
            return {
                "lambda":   None,
                "topology": None,
                "flows":    None,
                "status":   f"license_limit ({n_vars} vars exceeds "
                            f"free-tier 2000 limit; install academic "
                            f"license from gurobi.com/academia)",
                "mip_gap":  None,
            }
        raise

    # ── Extract results ──
    if m.status in (GRB.OPTIMAL, GRB.TIME_LIMIT) and m.SolCount > 0:
        topo = {}
        for (i, j) in edges:
            val = round(x[i, j].X)
            if val > 0:
                topo[i, j] = val

        flow_vals = {}
        for key in f:
            val = f[key].X
            if val > 1e-9:
                flow_vals[key] = val

        status = "optimal" if m.status == GRB.OPTIMAL else "time_limit"
        return {
            "lambda":   lam.X,
            "topology": topo,
            "flows":    flow_vals,
            "status":   status,
            "mip_gap":  m.MIPGap,
        }
    else:
        status_names = {
            GRB.INFEASIBLE:  "infeasible",
            GRB.INF_OR_UNBD: "infeasible_or_unbounded",
            GRB.UNBOUNDED:   "unbounded",
            GRB.TIME_LIMIT:  "time_limit_no_solution",
        }
        return {
            "lambda":   None,
            "topology": None,
            "flows":    None,
            "status":   status_names.get(m.status, f"gurobi_status_{m.status}"),
            "mip_gap":  None,
        }


# ────────────────────── Display Helpers ───────────────────────────

def print_traffic_matrix(T, label="Traffic Matrix T"):
    print(f"\n{'='*64}")
    print(f"  {label}")
    print(f"{'='*64}")
    header = "       " + "  ".join(f" d={j} " for j in range(N))
    print(header)
    for i in range(N):
        row = "  ".join(f"{T[i][j]:5.3f}" for j in range(N))
        print(f"  s={i}  {row}")
    row_sums = [f"{T[i].sum():.3f}" for i in range(N)]
    col_sums = [f"{T[:, j].sum():.3f}" for j in range(N)]
    print(f"  Row sums: [{', '.join(row_sums)}]")
    print(f"  Col sums: [{', '.join(col_sums)}]")


def print_results(result, label=""):
    if label:
        print(f"\n{'#'*64}")
        print(f"  RESULT: {label}")
        print(f"{'#'*64}")

    status  = result["status"]
    mip_gap = result["mip_gap"]

    if status not in ("optimal", "time_limit"):
        print(f"  Solver status: {status}")
        return

    if status == "time_limit":
        print("  NOTE: Time limit reached -- solution is best found, "
              "not proven optimal.")

    lam_val = result["lambda"]
    topo    = result["topology"]
    flows   = result["flows"]

    print(f"\n  Optimal lambda* = {lam_val:.6f}")
    if mip_gap is not None:
        print(f"  MIP gap         = {mip_gap:.6f}  "
              f"({'proven optimal' if mip_gap < 1e-6 else 'gap remains'})")

    # Topology adjacency list
    print("\n  Optimal Topology (adjacency list):")
    for i in range(N):
        neighbors = []
        for j in range(N):
            if (i, j) in topo:
                cnt = topo[i, j]
                neighbors.append(f"{j}" if cnt == 1 else f"{j}(x{cnt})")
        print(f"    Node {i} -> [{', '.join(neighbors)}]")

    # Degree verification
    print("\n  Degree Verification:")
    all_ok = True
    for i in range(N):
        out_deg = sum(topo.get((i, j), 0) for j in range(N))
        in_deg  = sum(topo.get((j, i), 0) for j in range(N))
        ok = out_deg == D and in_deg == D
        if not ok:
            all_ok = False
        sym_out = "OK" if out_deg == D else "FAIL"
        sym_in  = "OK" if in_deg == D else "FAIL"
        print(f"    Node {i}: out={out_deg} [{sym_out}]  "
              f"in={in_deg} [{sym_in}]")
    if all_ok:
        print("    All degree constraints satisfied.")

    # Edge utilization
    if flows:
        print("\n  Edge Utilization (top 10 most-loaded edges):")
        edge_load = {}
        for (i, j, s, t), fval in flows.items():
            edge_load[(i, j)] = edge_load.get((i, j), 0.0) + fval
        sorted_edges = sorted(edge_load.items(), key=lambda e: e[1],
                               reverse=True)
        for (i, j), load in sorted_edges[:10]:
            cap = topo.get((i, j), 0)
            pct = (load / cap * 100) if cap > 0 else 0
            print(f"    ({i}->{j}): flow={load:.4f} / cap={cap}  "
                  f"({pct:.1f}%)")

    # Total links
    total_links = sum(topo.values())
    print(f"\n  Total directed links placed: {total_links}  "
          f"(expected: {N * D})")


# ──────────────────────── Main ────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Assignment 4 Part 2: Max Concurrent Flow "
                    "Topology Design (Gurobi)")
    parser.add_argument("--time-limit", type=int, default=DEFAULT_TIME_LIMIT,
                        help=f"Time limit per solve in seconds "
                             f"(default: {DEFAULT_TIME_LIMIT})")
    parser.add_argument("--verbose", action="store_true",
                        help="Show full Gurobi solver log")
    args = parser.parse_args()

    time_limit = args.time_limit
    verbose    = args.verbose

    print(f"Solver         : Gurobi {gp.gurobi.version()}")
    print(f"Time limit     : {time_limit}s per test case")
    print(f"Network        : n={N} nodes, d={D} in/out degree, "
          f"link capacity=1")

    test_cases = [
        ("1. Concentrated (T[0][1]=4, rest 0)",  concentrated_traffic()),
        ("2. Permutation (i -> (i+1)%8, w=4)",   permutation_traffic()),
        ("3. Random Hose (seed=42)",              random_hose_traffic(42)),
        ("4. Random Hose (seed=99)",              random_hose_traffic(99)),
        ("5. Uniform (T[i][j] = 4/7 for i!=j)",  uniform_traffic()),
    ]

    summary = []

    for label, T in test_cases:
        print_traffic_matrix(T, label)
        t0 = time.time()
        result = solve(T, verbose=verbose, time_limit=time_limit)
        elapsed = time.time() - t0
        print_results(result, label)
        summary.append((label,
                        result.get("lambda"),
                        elapsed,
                        result["status"],
                        result.get("mip_gap")))
        print(f"\n  Solve time: {elapsed:.2f}s")
        print()

    # Summary table
    print("\n" + "=" * 78)
    print("  SUMMARY OF RESULTS")
    print("=" * 78)
    print(f"  {'Test Case':<45s} {'lambda*':>8s}  "
          f"{'MIP Gap':>8s}  {'Time':>6s}  Status")
    print(f"  {'-'*45} {'-'*8}  {'-'*8}  {'-'*6}  {'-'*10}")
    for label, lam_val, elapsed, status, gap in summary:
        lam_str = f"{lam_val:8.6f}" if lam_val is not None else "   N/A  "
        gap_str = f"{gap:8.6f}" if gap is not None else "   N/A  "
        print(f"  {label:<45s} {lam_str}  "
              f"{gap_str}  {elapsed:5.1f}s  {status}")
    print()


if __name__ == "__main__":
    main()
