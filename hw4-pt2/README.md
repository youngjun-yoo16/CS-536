# Assignment 4 -- Part 2: Arbitrary Traffic Matrix (50 pts)

## CS 536: Data Communication and Computer Networks, Spring 2026

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [Approach: Joint Topology + Routing MILP](#approach-joint-topology--routing-milp)
3. [Mathematical Formulation](#mathematical-formulation)
4. [Intuition: Why This Formulation Works](#intuition-why-this-formulation-works)
5. [Implementation](#implementation)
6. [Results](#results)
7. [Analysis and Discussion](#analysis-and-discussion)
8. [How to Run](#how-to-run)

---

## Problem Statement

We have **n = 8** nodes, each with **d = 4** incoming and **d = 4** outgoing directed links, each of capacity 1. Given a traffic matrix **T** drawn from the hose model:

```
T_hose = { T in R^{8x8}_>=0 | T_ii = 0 for all i,
            sum_j T_ij <= 4 for all i,
            sum_i T_ij <= 4 for all j }
```

The goal is to find the **topology** (directed graph) that **maximizes the concurrent flow lambda** for any given traffic matrix from this set.

**Concurrent flow lambda** means we scale all demands uniformly: the effective demand from s to t is lambda * T[s][t]. We want the largest lambda such that all scaled demands can be simultaneously routed.

---

## Approach: Joint Topology + Routing MILP

We formulate a **mixed-integer linear program (MILP)** that simultaneously optimizes:

1. **Where to place the links** (topology design), and
2. **How to route all demands** (multi-commodity flow).

This joint formulation is essential because topology and routing are interdependent:
- You can only route flow over links that exist.
- The best link placement depends on which flows need to be routed.

By solving them together, the optimizer finds the globally best (topology, routing) pair.

---

## Mathematical Formulation

### Decision Variables

| Variable | Type | Meaning |
|---|---|---|
| **x_{ij}** in Z_>=0, for i != j | Integer | Number of parallel directed links from node i to node j |
| **f_{ij}^{(s,t)}** >= 0 | Continuous | Amount of commodity (s,t) flow routed on edge (i -> j) |
| **lambda** >= 0 | Continuous | Throughput scaling factor (what we maximize) |

**Why x_{ij} is integer:** You cannot build half a link. Parallel links between the same pair are allowed (e.g., x_{ij} = 2 means two directed links from i to j providing 2 units of capacity).

### Objective Function

```
Maximize  lambda
```

### Constraints

**1. Out-Degree Constraint** (each node has exactly d outgoing links):

```
sum_{j != i}  x_{ij}  =  d        for all i in {0, 1, ..., 7}
```

Each node distributes exactly d = 4 outgoing links among the other 7 nodes.

**2. In-Degree Constraint** (each node has exactly d incoming links):

```
sum_{i != j}  x_{ij}  =  d        for all j in {0, 1, ..., 7}
```

Each node receives exactly d = 4 incoming links.

**3. Link Capacity Constraint** (flow cannot exceed available capacity):

```
sum_{(s,t): s != t}  f_{ij}^{(s,t)}  <=  x_{ij}     for all i != j
```

The total flow on edge (i -> j), summed across all commodities, cannot exceed the number of parallel links placed on that edge. **This is the key coupling constraint** that ties topology to routing.

**4. Flow Conservation** (standard multi-commodity flow):

For each demand pair (s, t) with s != t, and for each node v:

```
sum_j f_{vj}^{(s,t)}  -  sum_j f_{jv}^{(s,t)}  =
    lambda * T[s][t]     if v = s   (source generates flow)
   -lambda * T[s][t]     if v = t   (sink absorbs flow)
    0                    otherwise  (transit: flow in = flow out)
```

**Important note:** The term `lambda * T[s][t]` looks bilinear but is NOT. Since T[s][t] is input data (a known constant), this is simply a linear coefficient on lambda. The entire formulation is a linear program (with integer constraints on x).

**5. Non-Negativity:**

```
f_{ij}^{(s,t)} >= 0     for all i, j, s, t
lambda >= 0
x_{ij} >= 0              (and integer)
```

### Variable and Constraint Counts (n=8, d=4)

| Component | Count |
|---|---|
| Topology variables x_{ij} | 8 x 7 = 56 integer variables |
| Commodities (s,t) | Up to 56 demand pairs (those with T[s][t] > 0) |
| Flow variables f_{ij}^{(s,t)} | Up to 56 x 56 = 3,136 continuous variables |
| lambda | 1 continuous variable |
| Degree constraints | 8 (out) + 8 (in) = 16 |
| Capacity constraints | 56 (one per directed edge pair) |
| Flow conservation | 56 commodities x 8 nodes = 448 |
| **Total** | **~3,193 variables, ~520 constraints** |

This is a small MILP. With Gurobi's academic license, it solves to proven optimality in seconds.

---

## Intuition: Why This Formulation Works

The formulation captures an essential insight: **the best network for a specific traffic matrix concentrates links where demand is heaviest**.

### Extreme Cases

1. **All traffic from node 0 to node 1** (T[0][1] = 4): The optimal topology puts all 4 of node 0's outgoing links pointing at node 1. This achieves lambda = 1 immediately with direct routing, since T[0][1] = 4 and we have 4 units of capacity on that edge.

2. **Uniform traffic** (T[i][j] = 4/7 for all i != j): Each node must spread its 4 links across 7 destinations. Only 4 get direct links; the other 3 require multi-hop paths. Multi-hop paths consume transit capacity at intermediate nodes, creating contention. This is the hardest case.

### Why the Hose Model Matters

The hose-model constraints (row sums <= 4, column sums <= 4) are critical. Since d = 4, each node's total outgoing demand never exceeds its total outgoing capacity, and similarly for incoming. This means **the bottleneck is never at a single node's total capacity** -- it's about whether the topology provides enough paths between the right pairs.

### The Integrality Gap

The LP relaxation (allowing fractional x_{ij}) always achieves lambda = 1.0 for hose-model traffic, since the continuous relaxation can perfectly spread capacity. The integer constraint creates a gap: with d = 4 links, each node can only directly connect to 4 of 7 neighbors. The remaining pairs must use multi-hop paths that consume shared capacity, potentially forcing lambda < 1.

---

## Implementation

### File Structure

```
CS536HW/
    max_concurrent_flow.py    # MILP solver using Gurobi Python API (gurobipy)
    implementationguide.md    # Formulation reference
    assignment-4.pdf          # Assignment specification
    README.md                 # This file
```

### Gurobi Python API

The implementation uses the **Gurobi Python API (gurobipy)** directly, as required by the assignment. Key API calls used:

| Action | Gurobi Call |
|---|---|
| Create model | `m = gp.Model("MaxConcurrentFlow_TopologyDesign")` |
| Add integer variable | `m.addVar(vtype=GRB.INTEGER, lb=0, ub=D, name="x_i_j")` |
| Add continuous variable | `m.addVar(vtype=GRB.CONTINUOUS, lb=0, name="f_i_j_s_t")` |
| Sum expression | `gp.quicksum(...)` |
| Add constraint | `m.addConstr(expr == value, name="...")` |
| Set objective | `m.setObjective(lam, GRB.MAXIMIZE)` |
| Configure time limit | `m.Params.TimeLimit = 300` |
| Solve | `m.optimize()` |
| Check status | `m.status == GRB.OPTIMAL` |
| Get solution value | `var.X` |
| Get optimality gap | `m.MIPGap` |

### Code Architecture

The implementation is a single Python file with clean separation:

1. **Traffic matrix generators** -- Functions to create test matrices satisfying the hose model.
2. **`solve()` function** -- Builds and solves the MILP using native gurobipy calls. Takes a traffic matrix and returns the optimal lambda, topology, and flow decomposition.
3. **Display helpers** -- Print the traffic matrix, topology adjacency list, degree verification, edge utilization, and summary table.
4. **`main()`** -- Runs all 5 test cases and prints results.

### Key Implementation Details

- **Only active commodities are created:** Flow variables `f_{ij}^{(s,t)}` are only created for demand pairs where `T[s][t] > 0`, avoiding unnecessary variables.
- **`lambda * T[s][t]` is linear, not bilinear:** Since `T[s][t]` is a known constant (input data), the flow conservation constraint is simply `T[s][t] * lam` -- a linear coefficient on the decision variable `lam`.
- **Integer rounding:** Topology variables are rounded to the nearest integer when extracting results (to handle solver numerical noise).
- **MIP gap reporting:** After each solve, `m.MIPGap` is printed to confirm whether the solution is proven optimal (gap = 0) or just the best found within the time limit.
- **License handling:** The free pip-installed Gurobi has a 2000-variable limit. Models with >56 commodities exceed this. An academic license (free from [gurobi.com](https://www.gurobi.com/academia/academic-program-and-licenses/)) removes the limit.

---

## Results

### Test Cases and Results (Gurobi with academic license, 300s time limit)

All five cases solve to **proven optimality** (MIP gap = 0) in under 4 seconds:

| Test Case | lambda* | MIP Gap | Solve Time | Status |
|---|---|---|---|---|
| **Concentrated** (T[0][1]=4, rest 0) | **1.000000** | 0.000000 | 0.01s | Proven optimal |
| **Permutation** (i -> (i+1)%8, weight 4) | **1.000000** | 0.000000 | 0.01s | Proven optimal |
| **Random Hose** (seed=42) | **0.830139** | 0.000000 | 1.2s | Proven optimal |
| **Random Hose** (seed=99) | **0.843766** | 0.000000 | 3.7s | Proven optimal |
| **Uniform** (T[i][j]=4/7 for all i!=j) | **0.700000** | 0.000000 | 0.4s | Proven optimal |

### Detailed Results

#### Test 1: Concentrated Traffic (lambda* = 1.0, proven optimal)

All traffic from node 0 to node 1 (T[0][1] = 4). The solver routes flow via a multi-hop path and concentrates all capacity:

```
Node 0 -> [4(x4)]    Node 4 -> [7(x4)]    Node 7 -> [1(x4)]
```

All 4 units of demand flow along the path 0 -> 4 -> 7 -> 1, fully utilizing each link. The remaining nodes form arbitrary valid pairings to satisfy degree constraints. Lambda = 1 is trivially achievable since each node's demand (4 units to one destination) exactly matches its outgoing capacity.

#### Test 2: Permutation Traffic (lambda* = 1.0, proven optimal)

Each source i sends 4 units to destination (i+1) mod 8. The optimal topology is a directed ring:

```
Node 0 -> [1(x4)]
Node 1 -> [2(x4)]
Node 2 -> [3(x4)]
...
Node 7 -> [0(x4)]
```

Each node concentrates all 4 outgoing links on its single destination. Every edge carries exactly 4 units of flow at 100% utilization. Lambda = 1.

#### Test 3: Random Hose Traffic, seed=42 (lambda* = 0.830139, proven optimal)

The solver tailors the topology to the specific random demand pattern. Each node connects to 4 others (no parallel links), and routing uses multi-hop paths for non-adjacent demand pairs:

```
Node 0 -> [2, 3, 5, 6]    Node 4 -> [0, 1, 2, 7]
Node 1 -> [2, 3, 4, 5]    Node 5 -> [0, 1, 2, 4]
Node 2 -> [3, 4, 6, 7]    Node 6 -> [0, 1, 4, 7]
Node 3 -> [0, 5, 6, 7]    Node 7 -> [1, 3, 5, 6]
```

All edges are fully utilized (100%). The proven optimal lambda = 0.830 means ~83% of all demands can be simultaneously routed.

#### Test 4: Random Hose Traffic, seed=99 (lambda* = 0.843766, proven optimal)

Similar to seed=42, but this traffic matrix allows slightly higher throughput. Notably, node 4 uses a parallel link (x[4,6] = 2), concentrating capacity where the demand pattern requires it.

#### Test 5: Uniform Traffic (lambda* = 0.700000, proven optimal)

This is the hardest case. With uniform T[i][j] = 4/7 for all i != j:

```
Node 0 -> [2, 3, 4, 6]    Node 4 -> [0, 2, 3, 5]
Node 1 -> [3, 5, 6, 7]    Node 5 -> [0, 1, 6, 7]
Node 2 -> [1, 4, 5, 6]    Node 6 -> [1, 2, 4, 7]
Node 3 -> [0, 1, 2, 7]    Node 7 -> [0, 3, 4, 5]
```

- Each node has 4 outgoing links but 7 destinations.
- Only 4 destinations get direct links; the other 3 require multi-hop routing.
- Multi-hop paths consume transit capacity at intermediate nodes.
- The **proven optimal** lambda = 0.7 (MIP gap = 0), meaning exactly 70% of all demands can be simultaneously satisfied.
- The LP relaxation upper bound is 1.0, giving an integrality gap of 0.3 (30%). This gap represents the fundamental cost of discrete topology decisions under uniform demand.

---

## Analysis and Discussion

### Why lambda < 1 for Uniform Traffic

For the uniform traffic matrix, achieving lambda = 1 would require every node to send 4/7 units to each of the 7 other nodes, totaling 4 units outgoing (matching the 4 link capacity). However:

1. Each node can only create 4 direct links (integer constraint).
2. The 3 destinations without direct links must be reached via 2+ hops.
3. Each hop on a multi-hop path consumes capacity at the intermediate node.
4. This "transit tax" reduces the effective throughput below 1.

The LP relaxation avoids this by allowing fractional links (e.g., x_{ij} = 4/7 to every neighbor), which is physically unrealizable.

### How the Topology Adapts to the Traffic Matrix

The MILP formulation automatically adapts the topology to the given traffic matrix:

- **Concentrated traffic:** All links point toward the heavy demand destination.
- **Permutation traffic:** Links form directed paths matching the demand pattern.
- **Random traffic:** Links are distributed proportionally to demand weights, with heavier demand pairs getting direct connections.
- **Uniform traffic:** Links are spread as evenly as possible (each node connects to 4 of 7 neighbors), chosen to minimize the maximum multi-hop path length.

This adaptivity is the key advantage of the joint optimization -- it finds the best possible topology for any specific T.

### Complexity and Scalability

For n = 8, d = 4, the MILP has ~3,193 variables and ~520 constraints. This is a small problem by MILP standards. Gurobi solves it to proven optimality (MIP gap = 0) in seconds with an academic license.

The bottleneck is the 56 integer variables (topology decisions). The branch-and-bound search over these integers is what makes the uniform case harder -- there are many possible 4-regular directed graphs on 8 nodes.

### The Hose Model and Feasibility

The hose model ensures that no single node is asked to send or receive more traffic than its link capacity allows. This is a necessary condition for lambda = 1 to even be theoretically possible. The interesting question is whether the integer topology constraint forces lambda below 1 for specific traffic patterns.

Our results show:
- When traffic is concentrated on few pairs: **lambda = 1 is achievable** (the topology can perfectly match the demand).
- When traffic is spread across many pairs: **lambda < 1** due to the integrality gap (the integer topology cannot simultaneously serve all pairs efficiently).

---

## How to Run

### Prerequisites

```bash
pip install numpy gurobipy
```

A Gurobi academic license is required to solve the full-size models (3,193 variables). The free pip license supports models up to 2,000 variables, which covers the concentrated and permutation test cases.

### Gurobi Academic License Setup

1. Register at [gurobi.com/academia](https://www.gurobi.com/academia/academic-program-and-licenses/).
2. Request a free academic license.
3. Run `grbgetkey <license-key>` to install it.
4. Verify with: `python -c "import gurobipy; print(gurobipy.gurobi.version())"`

### Usage

```bash
# Run all 5 test cases (default: 300s time limit per case)
python max_concurrent_flow.py

# Custom time limit (seconds)
python max_concurrent_flow.py --time-limit 60

# Show full Gurobi solver log
python max_concurrent_flow.py --verbose
```

### Output

The program prints for each test case:
1. The input traffic matrix T with row/column sums.
2. The optimal concurrent flow lambda*.
3. The MIP gap (0 = proven optimal).
4. The optimal topology as an adjacency list with link multiplicities.
5. Verification that all degree constraints are satisfied (4 in, 4 out per node).
6. Edge utilization statistics (top 10 most-loaded edges).
7. A summary table of all results with lambda*, MIP gap, solve time, and status.
