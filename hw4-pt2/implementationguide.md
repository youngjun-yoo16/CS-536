The big idea: Integer variables x_{ij} decide how many links go from node i to j (topology), continuous variables f_{ij}^{(s,t)} decide how flow is routed (routing), and a coupling constraint ties them together — total flow on an edge can't exceed the number of links placed there. Maximizing λ pushes throughput as high as the jointly-optimized topology and routing allow.
The document covers the complete formulation (all variables, objective, constraints), the intuition for why it works, variable/constraint counts so the implementer knows the scale (~3,200 variables, ~520 constraints — trivial for Gurobi), a step-by-step implementation guide with the exact Gurobi API calls to use, and a testing strategy with 4 different traffic matrix types.
A few things to flag before you hand this to Claude Code:

The λ · T_{st} term in flow conservation looks bilinear but isn't — T is input data, so it's just a constant coefficient on λ. This is a common implementation pitfall.
Only create flow variables for commodities where T[s][t] > 0 to avoid unnecessary variables.
Gurobi needs an academic license (free) — make sure that's set up on the machine running the code.

Let me know if you want me to adjust anything in the formulation or add more detail to any section.

# Assignment 4 — Part 2: Arbitrary Traffic Matrix (50 pts)

## Problem Recap

We have **n = 8** nodes, each with **d = 4** incoming and **d = 4** outgoing directed links, each of capacity 1. Given a traffic matrix **T** drawn from the hose model:

```
T_hose = { T ∈ R^{8×8}_≥0 | T_ii = 0 ∀i,  Σ_j T_ij ≤ 4 ∀i,  Σ_i T_ij ≤ 4 ∀j }
```

our goal is to find the **topology** (directed graph) that **maximizes the concurrent flow λ** for that specific traffic matrix.

---

## Approach: Joint Topology + Routing ILP

We formulate a **mixed-integer linear program (MILP)** that simultaneously optimizes:

1. **Where to place the links** (topology design), and
2. **How to route all demands** (multi-commodity flow).

This is the natural formulation because the topology and routing are interdependent — you can only route flow over links that exist, and the best link placement depends on which flows need to be routed.

---

## Decision Variables

| Variable | Type | Meaning |
|---|---|---|
| **x_{ij}** ∈ Z_≥0, for i ≠ j | Integer | Number of parallel directed links from node i to node j |
| **f_{ij}^{(s,t)}** ≥ 0, for all i,j,s,t with s ≠ t | Continuous | Amount of commodity (s,t) flow routed on link (i → j) |
| **λ** ≥ 0 | Continuous | Throughput scaling factor (the concurrent flow we maximize) |

**Note on x_{ij}:** These are integers because you can't build half a link. Parallel links between the same pair of nodes are allowed (e.g., x_{ij} = 2 means two directed links from i to j, providing 2 units of capacity on that edge).

---

## Objective Function

```
Maximize  λ
```

We want to scale up all demands as much as possible. At throughput λ, the effective demand from s to t is λ · T_{st}.

---

## Constraints

### 1. Out-Degree Constraint (each node has exactly d outgoing links)

```
Σ_{j ≠ i}  x_{ij}  =  d        for all i ∈ {0, 1, ..., 7}
```

Each node i distributes exactly d = 4 outgoing links among the other 7 nodes.

### 2. In-Degree Constraint (each node has exactly d incoming links)

```
Σ_{i ≠ j}  x_{ij}  =  d        for all j ∈ {0, 1, ..., 7}
```

Each node j receives exactly d = 4 incoming links from the other 7 nodes.

### 3. Link Capacity Constraint (flow cannot exceed available capacity)

```
Σ_{(s,t): s≠t}  f_{ij}^{(s,t)}  ≤  x_{ij}     for all i ≠ j
```

The total flow on edge (i → j), summed across all commodities, cannot exceed the number of parallel links placed on that edge. This is the key coupling constraint between topology and routing.

### 4. Flow Conservation (standard multi-commodity flow)

For each demand pair (s, t) with s ≠ t, and for each node v ∈ {0, ..., 7}:

```
Σ_j f_{vj}^{(s,t)}  −  Σ_j f_{jv}^{(s,t)}  =  
    ⎧  λ · T_{st}     if v = s   (source generates flow)
    ⎨ −λ · T_{st}     if v = t   (sink absorbs flow)
    ⎩  0               otherwise  (transit: flow in = flow out)
```

Note: The summations are over all j ∈ {0,...,7} including j = v; since x_{vv} = 0, there is no capacity on self-loops, so f_{vv}^{(s,t)} will naturally be zero.

### 5. Non-Negativity

```
f_{ij}^{(s,t)} ≥ 0     for all i, j, s, t
λ ≥ 0
x_{ij} ≥ 0             (and integer)
```

---

## Intuition: Why This Works

The formulation captures an important insight: **the best network for a specific traffic matrix concentrates links where demand is heaviest**.

Consider extremes:

- If all traffic goes from node 0 to node 1, the optimal topology puts all 4 of node 0's outgoing links pointing at node 1 (achieving λ = 1 immediately with direct routing, since T_{01} = 4 and we have 4 units of capacity on that edge).

- If traffic is spread across many destinations, the topology must balance between direct links (efficient but limited fan-out) and multi-hop paths (wider reach but consuming transit capacity at intermediate nodes).

The **hose-model constraints** (row sums ≤ 4, column sums ≤ 4) are critical: since d = 4, each node's total outgoing demand never exceeds its total outgoing capacity, and similarly for incoming. This means **the bottleneck is never at a single node's total capacity** — it's about whether the topology provides enough paths between the right pairs.

For many hose-model matrices, the optimal λ = 1 is achievable because the ILP can tailor the topology to the specific demand pattern. However, for adversarial matrices that spread demand thinly across all pairs, multi-hop routing may consume intermediate capacity and force λ < 1.

---

## Variable & Constraint Counts (for n=8, d=4)

Understanding the scale helps with implementation:

- **Topology variables x_{ij}:** 8 × 7 = 56 integer variables
- **Commodities (s,t):** Up to 8 × 7 = 56 demand pairs (those with T_{st} > 0)
- **Flow variables f_{ij}^{(s,t)}:** Up to 56 edges × 56 commodities = 3,136 continuous variables
- **λ:** 1 continuous variable
- **Degree constraints:** 8 (out) + 8 (in) = 16
- **Capacity constraints:** 56 (one per directed edge pair)
- **Flow conservation:** 56 commodities × 8 nodes = 448

**Total:** ~3,193 variables, ~520 constraints. This is a small MILP — Gurobi solves it in seconds.

---

## Gurobi Implementation Guide

### Overall Structure

The implementation should be a single Python file with the following structure:

```
1. Imports (gurobipy, numpy)
2. Parameters (n=8, d=4)
3. Traffic matrix definition (sample T from hose model)
4. Model creation
5. Variable creation
6. Constraint creation
7. Objective setting
8. Solve
9. Extract and print results (optimal λ, topology, flow)
```

### Step-by-Step Implementation Details

#### Step 1: Set Up Parameters and Traffic Matrix

Define n = 8, d = 4. Create a sample traffic matrix T as an 8×8 numpy array satisfying the hose-model constraints (T_ii = 0, row sums ≤ 4, column sums ≤ 4). A simple example:

```
T[i][j] = 4/7  for all i ≠ j,  T[i][i] = 0
```

This gives row sums = 4 and column sums = 4 (uniform hose traffic). You should also test with non-uniform matrices.

#### Step 2: Create the Gurobi Model

Initialize a Gurobi Model object. Set a meaningful model name like "MaxConcurrentFlow_TopologyDesign".

#### Step 3: Add Decision Variables

**Topology variables x_{ij}:**
- Create integer variables for each (i, j) pair where i ≠ j.
- Lower bound = 0, upper bound = d (a node can point all its links at one destination).
- Use a dictionary indexed by tuples (i, j).

**Flow variables f_{ij}^{(s,t)}:**
- Create continuous variables for each (i, j, s, t) where i ≠ j and s ≠ t.
- Only create variables for commodity (s, t) if T[s][t] > 0 (skip zero-demand pairs for efficiency).
- Lower bound = 0.

**Throughput variable λ:**
- Single continuous variable, lower bound = 0.

#### Step 4: Add Constraints

**Out-degree constraints:**
For each node i, add: `sum of x[i,j] for all j ≠ i == d`

**In-degree constraints:**
For each node j, add: `sum of x[i,j] for all i ≠ j == d`

**Capacity constraints:**
For each edge (i, j) where i ≠ j, add:
`sum of f[i,j,s,t] for all active commodities (s,t) <= x[i,j]`

**Flow conservation constraints:**
For each active commodity (s, t) and each node v, add:
`sum of f[v,j,s,t] for all j ≠ v  −  sum of f[j,v,s,t] for all j ≠ v`
equals:
- `λ * T[s][t]` if v == s
- `−λ * T[s][t]` if v == t
- `0` otherwise

**Important implementation note on bilinear terms:** The conservation constraint contains `λ * T[s][t]`. Since T[s][t] is a **known constant** (input data), this is simply a linear coefficient on λ. It is NOT a bilinear term. Write it as: `T[s][t] * lambda_var` in the Gurobi expression.

#### Step 5: Set Objective and Solve

Set the objective to maximize λ. Call `model.optimize()`.

#### Step 6: Extract Results

After solving:
- Print the optimal λ value.
- Print the topology: for each (i, j) with x[i,j] > 0.5 (to handle numerical noise), print the link and its multiplicity.
- Optionally print flow decomposition for verification.
- Verify degree constraints are met in the solution.

### Testing Strategy

Test with at least these traffic matrices:

1. **Uniform:** T[i][j] = 4/7 for i ≠ j. Expected: λ should be achievable at or near 1 depending on topology.

2. **Concentrated:** One source sends all traffic to one destination (T[0][1] = 4, all else 0). Expected: λ = 1 easily.

3. **Permutation:** T is a permutation matrix scaled by 4 (each source sends 4 units to exactly one distinct destination). Expected: λ = 1 if the topology can be a union of matchings covering the permutation.

4. **Adversarial/spread:** Each source sends equal traffic to all destinations. This stresses the topology the most.

### Key Gurobi API Calls Reference

| Action | Gurobi Call |
|---|---|
| Create model | `m = gp.Model("name")` |
| Add integer var | `m.addVar(vtype=GRB.INTEGER, lb=0, ub=d, name="x_i_j")` |
| Add continuous var | `m.addVar(vtype=GRB.CONTINUOUS, lb=0, name="f_i_j_s_t")` |
| Add constraint | `m.addConstr(expr == value, name="...")` |
| Set objective | `m.setObjective(lambda_var, GRB.MAXIMIZE)` |
| Solve | `m.optimize()` |
| Get solution value | `var.X` |
| Check status | `m.status == GRB.OPTIMAL` |

### Output Format

The program should print:
1. The input traffic matrix T.
2. The optimal concurrent flow λ*.
3. The optimal topology as an adjacency list: for each node, list its outgoing neighbors (with multiplicities if parallel links exist).
4. A verification that degree constraints hold (each node has exactly 4 in-links and 4 out-links).

---

## Summary

The key idea is that by formulating topology design and multi-commodity flow routing as a single joint optimization, we let the solver find the best possible network for any given traffic matrix. The integer constraint on link variables ensures a physically realizable topology, while the LP relaxation of the flow variables allows optimal fractional routing. For the small scale of n = 8, d = 4, this MILP is very tractable and Gurobi solves it in under a second.