# Plan for Question 3 – ML Congestion Control

This document describes the end‑to‑end plan for implementing Q3 using the existing hw2 client traces.

---

## 0. Overall Approach

- Use the existing per‑destination CSV logs written by `ControlConnection.send_data()` as the raw data source.
- Build a **single global supervised regression model** that predicts the **next congestion window update**:
  \[
  y(t) = \Delta \text{snd\_cwnd}(t) = \text{snd\_cwnd}(t) - \text{snd\_cwnd}(t-1)
  \]
- Features \(X(t)\) will be derived from TCP_INFO and goodput at time \(t-1\), possibly including a small amount of history (one lag).
- Use **scikit‑learn** for the ML pieces:
  - `pandas`, `numpy` for data handling
  - `sklearn.GradientBoostingRegressor` (or similar tree model) as the main model
  - `sklearn.model_selection` for train/test split and validation
- Use **matplotlib** for all Q3 plots.

**Justification:**

- Tree‑based models handle non‑linearities and mixed‑scale features well, train quickly on modest datasets, and don’t require GPU or long tuning cycles.
- We keep the pipeline simple, debuggable, and easy to explain in the report.

---

## 1. Data Preparation

### 1.1. Collecting Raw Traces

**Assumption:** The iperf client has already been run against multiple servers, producing logs like:

- `client/<host>_<port>.csv`

Each row already includes:

- `timestamp`
- `interval_s`
- `goodput_bps`
- `snd_cwnd`
- `rtt_ms`
- loss/retransmission fields (`lost`, `retrans`, `retransmits`, `delivered`, etc.)
- other TCP fields (`rttvar_ms`, `pacing_rate_bps`, `bytes_acked`, `bytes_sent`, …)

If needed, re‑run the client script to gather at least:

- **5 traces** for the destinations that must be shown in the final Q3 plots.
- Optionally more traces (e.g., 10–20) to give the global model more variety.

### 1.2. Loading Individual Logs

For each destination log file:

1. Load into a `pandas.DataFrame`.
2. Sort by `timestamp` (just to be safe).
3. Compute one‑step differences:

   - `delta_cwnd = snd_cwnd.diff()`  
   - `delta_retrans = retrans.diff()` or `lost.diff()`  
   - `delta_delivered = delivered.diff()`  
   - `delta_bytes_acked = bytes_acked.diff()`

4. Drop the first row (where diffs are NaN).

We will treat each row \(t\) as the outcome of the cwnd decision at \(t-1\).

---

## 2. Feature and Label Definition

### 2.1. Label \(y(t)\)

For each interval \(t\):

- **Label:**  
  \[
  y(t) = \Delta \text{snd\_cwnd}(t) = \text{snd\_cwnd}(t) - \text{snd\_cwnd}(t-1)
  \]

Implementation-wise:

- `y = delta_cwnd` at time index \(t\).

**Justification:**  
The question explicitly defines the learning target as the **congestion window decision**, expressed as the change in cwnd.

### 2.2. Base Features \(X(t)\)

For each interval \(t\) we use **values observed at \(t\)** (which correspond to the effect of the previous cwnd decision). To keep the model interpretable and close to the handout, we use:

- `goodput_bps(t)` – instantaneous goodput
- `rtt_ms(t)` – RTT estimate
- `snd_cwnd(t)` – current cwnd
- `loss_rate(t)` – derived from retrans/lost
  - e.g., `delta_retrans(t) / interval_s(t)` or `delta_lost(t) / interval_s(t)`
- `rttvar_ms(t)` – RTT variability
- `pacing_rate_bps(t)` – pacing rate
- `bytes_acked(t)` – cumulative acked bytes (for scale)
- Optionally `bytes_sent(t)` if useful

These are all already present or derivable from the logged TCP_INFO struct.

**Justification:**

- Matches the handout’s variables: goodput, RTT, loss, cwnd.
- Adds a few extra TCP_INFO statistics (rttvar, pacing rate) that can help but are still easy to explain.

### 2.3. Lag Features (Short History)

To let the model react to short‑term trends without becoming overly complex, we add **one‑step lag features**:

- `goodput_prev = goodput_bps.shift(1)`
- `rtt_prev = rtt_ms.shift(1)`
- `cwnd_prev = snd_cwnd.shift(1)`
- `loss_prev = loss_rate.shift(1)`

After shifting, drop rows with NaNs.

**Justification:**

- A single lag gives the model a sense of “direction” (e.g., RTT rising or falling, loss just started appearing) without requiring RNNs or attention models.
- Easy to justify in the report as a basic form of memory.

### 2.4. Normalization / Scaling

- For **tree-based models**, strict normalization is not required, but we will:
  - Convert `goodput_bps` to `goodput_Mbps = goodput_bps / 1e6` for readability.
  - Optionally log‑transform very skewed quantities (e.g., pacing_rate) if needed.

**Justification:**

- Keeps all features within understandable ranges (e.g., RTT in ms, goodput in Mbps), which helps when plotting and reasoning about feature importances.

---

## 3. Dataset Assembly and Splitting

### 3.1. Combine Multiple Destinations

1. For each destination log:
   - Engineer features and label as above.
   - Add a `trace_id` or `dest` column to indicate which server this row came from.

2. Concatenate all per‑destination data into a single big DataFrame.

This forms our **global dataset** for the model.

### 3.2. Train/Test Split

To respect temporal structure and keep Q3 plots simple:

- For each destination:
  - Use the first **X%** of time as **train**, remaining as **test** (e.g., 70/30 split along `timestamp`).
- Concatenate all train segments across destinations into a global **train set**.
- Concatenate all test segments into a global **test set**.

This also automatically gives us:

- For 5 chosen destinations, a natural **train horizon** and **test horizon** for the cwnd timeseries plot.

**Justification:**

- Avoids “future leakage” by not shuffling time.
- Still uses a single global model, as requested.

---

## 4. Objective Function \(η\) and Model Training

### 4.1. Computing \(η(t-1)\)

From each row \(t\) we compute:

\[
η(t-1) = \text{goodput}(t) - α \cdot \text{RTT}(t) - β \cdot \text{loss}(t)
\]

We will use:

- `goodput(t)` in **Mbps**
- `RTT(t)` in **ms**
- `loss(t)` as the **loss rate per second** (e.g., `delta_retrans / interval_s`)

**Choice of α, β:**

- Start with simple, scale‑reasonable values, e.g.:
  - \(α = 0.01\) (penalizes RTT too high but keeps units comparable with Mbps)
  - \(β = 1.0\) (each unit of loss rate strongly penalizes the objective)
- Optionally adjust α, β so that the three components of η have similar numeric ranges on a sample of the data.

**Justification:**

- Keeps η in a readable range and clearly encodes the idea “we want high goodput, low RTT, low loss”.

### 4.2. Training Loss and How η Enters

We will:

1. Train a **regression model** to predict \(y(t) = \Delta \text{snd\_cwnd}(t)\) using standard squared error (MSE) on the train set.
2. Use **η** as the **model selection objective**:
   - For each candidate model / hyperparameter set, roll out predictions on a validation set (subset of the train time‑horizon).
   - Compute the **average η** achieved by the resulting cwnd trajectory.
   - Choose hyperparameters that **maximize mean η**.

This way:

- The **supervised target** matches the handout (predict Δcwnd),
- The **performance objective** we actually optimize over hyperparameters is exactly the η defined in the assignment.

**Justification:**

- Directly optimizing η as a loss would be tricky because η depends on outcomes after the cwnd update; using it as the **model selection criterion** is a clean, defensible compromise that still “trains the model using η” in the sense of the handout.

### 4.3. Model Choice

Use a **Gradient Boosting Regressor** (or Random Forest as a baseline):

- `sklearn.ensemble.GradientBoostingRegressor`
- Small number of trees (e.g., 50–200), shallow depth (e.g., max_depth 3–4).

**Justification:**

- Captures non‑linear relationships between cwnd, RTT, loss, and goodput.
- Trains quickly on CPU, suitable for running multiple times within a day.
- Easy to inspect feature importances for the discussion in part (c).

---

## 5. Rolling Out Predictions and Plotting

The assignment requires:

> Plot the snd cwnd timeseries … including both train and test time horizons. Separately, now starting at the test split and for each time interval, take a prediction from your model and plot the new snd cwnd obtained from predictions.

### 5.1. For Each of 5 Destinations

For 5 chosen traces:

1. **Ground truth cwnd plot**
   - Plot `snd_cwnd` vs `timestamp` for the entire run.
   - Mark the train/test split with a vertical line.

2. **Predicted cwnd path on test horizon**
   - Initialize `cwnd_pred` at the cwnd value at the **start of test**.
   - For each test interval k:
     - Build features using:
       - Observed TCP stats at step k (goodput, RTT, loss, etc.)
       - For the lag features, use the **predicted** cwnd from the previous step rather than the true cwnd (so the model’s decisions feed into future decisions).
     - Get \(\Delta \widehat{\text{cwnd}}\) from the model.
     - Update:
       \[
       \text{cwnd\_pred}(k) = \text{cwnd\_pred}(k-1) + \Delta \widehat{\text{cwnd}}(k)
       \]
   - Plot `cwnd_pred` on the **same figure** as ground truth, but only over the test horizon.

3. Save each destination’s figure as a separate PDF.

**Justification:**

- Exactly matches the handout’s description of starting predictions “at the test split” and plotting the evolution in the same timeseries figure.

---

## 6. Extracting a Hand‑Written Congestion Update Rule (Q3c)

After training and plotting:

1. **Inspect feature importances** from the Gradient Boosting model to see which signals matter most (e.g., goodput, RTT, loss, rttvar).
2. For a few example traces, look at:
   - When RTT rises and loss increases, how does the model adjust cwnd?
   - When goodput increases without much RTT or loss, how does cwnd change?
3. From these patterns, derive a **verbal and pseudo‑code rule**, e.g.:

   - If RTT and loss are low and goodput is increasing → gently increase cwnd.
   - If loss spikes or RTT inflates sharply → decrease cwnd proportionally.
   - Maintain cwnd roughly constant when goodput is stable and RTT/loss are flat.

4. Translate that into a simple algorithm (e.g., AIMD‑like update) using:
   - A few thresholds on `rtt_ms` and `loss_rate`
   - A small additive increase rule and multiplicative decrease rule justified by observed η and feature importances.

**Justification:**

- Grounds the extracted algorithm in:
  - Observed cwnd trajectories,
  - The learned model behavior,
  - And standard principles: queueing, bandwidth‑delay product, and classic TCP congestion control.

---

## 7. Integration into One‑Shot Script

To align with the “one‑shot” requirement in the handout:

1. Add a **separate ML driver script**, e.g. `ml_pipeline.py`, that:
   - Discovers all per‑destination logs in a given directory.
   - Builds the dataset as above.
   - Trains the model and saves it (e.g., with `joblib`).
   - Generates:
     - cwnd timeseries plots (ground truth + predictions) for 5 destinations.
     - Optional summary statistics (η, error metrics).
2. Later, the **top‑level script** (or Docker entrypoint) will:
   - Run the iperf client (Q1+Q2),
   - Then invoke `ml_pipeline.py` for Q3,
   - Then exit with all plots and logs generated.

---

## 8. Deliverables Checklist for Q3

- [ ] Code to load and clean per‑destination CSVs into a single dataset.
- [ ] Feature engineering: base + lag features, label \(Δ\text{cwnd}\), loss proxy, η computation.
- [ ] Train/test split by time per destination, assembled into global train/test sets.
- [ ] Gradient Boosting regression model (or similar) trained on train set.
- [ ] Model selection based on η computed on validation data.
- [ ] For 5 destinations:
  - [ ] Plot of ground‑truth `snd_cwnd` (train+test) vs time.
  - [ ] Overlaid predicted `snd_cwnd` on test horizon.
- [ ] Text/section in report describing:
  - [ ] Feature set and preprocessing.
  - [ ] Model choice and how η was used.
  - [ ] Qualitative behavior of the learned cwnd controller.
  - [ ] The hand‑written congestion control rule derived from the learned behavior.