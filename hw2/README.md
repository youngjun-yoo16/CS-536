## Homework 2 – Throughput Client, TCP Stats, and ML Congestion Control

This directory contains the code and scripts for **CS536 Homework 2**:

- An iperf3‑compatible TCP client that runs throughput tests against public
  iperf3 servers (Q1/Q2).
- Instrumentation to collect TCP socket statistics (TCP_INFO) during the tests.
- An ML pipeline that learns a congestion window update rule from the traces
  and visualizes the learned behavior (Q3).

---

## Q1/Q2 – iPerf Throughput Client and TCP Stats

All client code lives under `hw2/client/`.

### Main Scripts

- **`client/control.py`**  
  Implements the iperf3 control and data connections:
  - Establishes the control connection.
  - Performs JSON‑based parameter exchange.
  - Opens the data connection, sends data continuously for a given duration.
  - Samples the Linux `TCP_INFO` struct every 200 ms and records:
    - RTT, cwnd (`snd_cwnd`), retransmissions/loss, bytes acked/sent, pacing rate,
      etc.
  - Computes per‑interval goodput based on bytes acked.

- **`client/main.py`**  
  Multi‑server throughput test driver:
  - Loads the public server list from `listed_iperf3_servers.csv`
    (exported from https://iperf3serverlist.net).
  - Picks **n** random destination servers (`-n, --num-servers`, default 10).
  - For each destination:
    - Negotiates iperf3 parameters.
    - Sends data for **d** seconds (`-d, --duration`, default 10).
    - Handles non‑responsive/invalid servers with retries and automatic
      replacement.
    - Logs per‑interval TCP stats and goodput into a per‑destination CSV:
      `<host>_<port>.csv`.
  - Prints per‑server and aggregate throughput statistics.

These traces (the `<host>_<port>.csv` files) are the input for Q3.

---

## Q3 – ML Model + Congestion Control

The ML pipeline lives in **`hw2/client/ml_pipeline.py`** and is driven by the
per‑destination CSV logs produced by `client/main.py`.

### What `ml_pipeline.py` Does

- Discovers per‑destination trace CSVs in the traces directory
  (e.g., `speedtest.foo.net_5201.csv`).
- For each trace, builds feature/label pairs at each time instance:
  - **Label** \(y(t)\):
    - \(y(t) = Δ\text{snd\_cwnd}(t) = \text{snd\_cwnd}(t) - \text{snd\_cwnd}(t-1)\).
  - **Base features** \(X(t)\):
    - `goodput_Mbps`, `rtt_ms`, `snd_cwnd`, `loss_rate`
      (derived from TCP loss/retrans counters),
    - `rttvar_ms`, `pacing_rate_bps`, `bytes_acked`, `bytes_sent`.
  - **Lag features** (one‑step history):
    - `goodput_prev`, `rtt_prev`, `cwnd_prev`, `loss_prev`.
- Combines all traces into a **single global dataset**, and for each trace:
  - Sorts by time and splits 70%/30% into train/test along the time axis.
- Trains a **GradientBoostingRegressor** to predict Δcwnd using MSE loss.
- Uses the assignment’s objective as a **model‑selection metric**:
  \[
  η(t-1) = \text{goodput}(t) - α\cdot\text{RTT}(t) - β\cdot\text{loss}(t)
  \]
  For each hyperparameter configuration, the pipeline:
  - Computes η on a validation subset.
  - Chooses the model with the best correlation between predicted Δcwnd and η.
- After training, it:
  - Prints test MSE on Δcwnd.
  - Prints feature importances (e.g., `cwnd_prev`, `loss_rate`, `snd_cwnd`, RTT,
    goodput, etc.).
  - For up to **5 traces**, rolls out predicted cwnd on the **test** horizon and
    generates cwnd time‑series plots:
    - `client/q3_outputs/q3_cwnd_trace_0.pdf` … `q3_cwnd_trace_4.pdf`,
      each showing ground‑truth cwnd and predicted cwnd (test only).

---

## One-shot HW2 pipeline (`hw2/main.py`)

To follow the assignment requirement that a **single script** runs all
experiments and plots in one shot, the top-level driver lives at
`hw2/main.py`. From the **repo root**:

```bash
python3 hw2/main.py \
  --server-list hw2/client/listed_iperf3_servers.csv \
  --num-servers 5 \
  --duration 10 \
  --timeout 30 \
  --alpha 0.01 \
  --beta 1.0
```

This script:

- Runs the iperf3-compatible client (Q1) to generate per-destination CSV traces
  under `hw2/client/`.
- Invokes `hw2/client/plot.py` to generate all Q1/Q2 PDF plots from those
  traces.
- Invokes `hw2/client/ml_pipeline.py` to train the ML model using an
  **η-weighted MSE objective** and produce Q3 cwnd time-series plots under
  `hw2/client/q3_outputs/`.

## Running Experiments with Docker

Because macOS does not expose `socket.TCP_INFO`, the experiments are run in a
Linux Docker container (Ubuntu 24.04) as required by the assignment.

### 1. Build the Docker image

From the **CS536 repo root** (one level above `hw2`):

```bash
cd ~/Downloads/CS536   # adjust to your repo location
docker build -t cs536-hw2 -f hw2/Dockerfile .
```

The Dockerfile:

- Installs Python 3 and system dependencies.
- Creates a virtualenv at `/venv` inside the container and installs:
  - Packages from `hw1/req.txt`.
  - `scikit-learn` for the ML pipeline.

### 2. Run the full pipeline inside Docker

From the repo root:

```bash
docker run --rm \
  -v ~/Downloads/CS536:/workspace \
  cs536-hw2
```

- The image’s default command runs `hw2/main.py` inside the container,
  executing Q1, Q2, and Q3 end-to-end.
- The bind mount `~/Downloads/CS536:/workspace` ensures that all generated
  CSVs and PDFs appear on your host under `hw2/client/`.

---

## Brief Summary of Results

In a representative run with 5 destinations:

- The throughput client achieved:
  - Average throughput ≈ **239 Mbps**,
  - Max ≈ **345 Mbps**, Min ≈ **145 Mbps**,
  - Total data sent ≈ **1.39 GB**.
- The ML model (Gradient Boosting) achieved a test MSE of about **1.0** on
  Δcwnd, which is small relative to typical cwnd magnitudes. In the generated
  cwnd time‑series plots, the predicted cwnd closely follows the ground‑truth
  cwnd on the test horizon (similar scale and dynamics, no divergence).
- Feature importances show that:
  - `cwnd_prev`, `loss_rate`, and current `snd_cwnd` dominate the decision,
  - RTT and goodput provide secondary refinement.

These observations are consistent with standard congestion‑control intuition:

- The sender primarily reacts to its current cwnd and recent loss signal.
- RTT and goodput help distinguish between truly good conditions and cases
  where high cwnd causes queueing and increased RTT.
- The learned behavior provides a reasonable basis for deriving a
  hand‑written cwnd update rule that increases cwnd cautiously under
  low‑loss/low‑RTT conditions and backs off when loss or RTT spikes.

## Q3 – ML Model + Congestion Control

This directory also contains the code and scripts for **Question 3** of the assignment:

- Building a dataset from TCP socket statistics (TCP_INFO) while running iperf3 tests.
- Training a global ML model that predicts the next congestion window update Δcwnd.
- Generating cwnd time–series plots comparing the learned behavior to the real one.

### Additional Files

- **`ml_pipeline.py`**  
  End‑to‑end ML pipeline for Q3. It:
  - Discovers per‑destination trace CSVs (e.g., `speedtest.foo.net_5201.csv`).
  - Builds a dataset \(X(t)\) with:
    - `goodput_Mbps`, `rtt_ms`, `snd_cwnd`, `loss_rate`,
    - `rttvar_ms`, `pacing_rate_bps`, `bytes_acked`, `bytes_sent`,
    - and one‑step lags: `goodput_prev`, `rtt_prev`, `cwnd_prev`, `loss_prev`.
  - Defines the label \(y(t) = Δ\text{snd\_cwnd}(t)\).
  - Trains a **GradientBoostingRegressor** on \(y\) with MSE loss.
  - Uses the assignment’s objective  
    \[
    η(t-1) = \text{goodput}(t) - α·\text{RTT}(t) - β·\text{loss}(t)
    \]
    as a **model‑selection metric** (chooses the hyperparameters with the best correlation between predicted Δcwnd and η).
  - Rolls out predicted cwnd on the test horizon and generates cwnd time‑series plots:
    - `q3_outputs/q3_cwnd_trace_0.pdf` … `q3_cwnd_trace_4.pdf`.

## Running Q3 Experiments with Docker

Because macOS does not expose `socket.TCP_INFO`, the experiments are run in a
Linux Docker container (Ubuntu 24.04) as required by the assignment.

### 1. Build the Docker image

From the **CS536 repo root** (one level above `hw2`):

cd ~/Downloads/CS536   # adjust to your repo location
docker build -t cs536-hw2 -f hw2/Dockerfile .
