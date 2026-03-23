## CS536 – Homework 2 Report  


This report describes my implementation and experimental results for all three
parts of Assignment 2: iPerf throughput measurements, TCP statistics tracing,
and a learned congestion avoidance algorithm.

---

## 1. iPerf Throughput Application

### 1(a) Socket program and iPerf3 compatibility

I implemented a Python client that speaks the iperf3 control and data
protocols directly, without using the `iperf3` binary.

- **Files:**  
  - `hw2/client/control.py` – core iperf3 implementation  
  - `hw2/client/main.py` – multi‑server driver script

#### Protocol behavior

For each destination server:

1. **Control connection** – `ControlConnection.connect()` opens a TCP socket to
   the iperf3 control port (typically 5201), disables Nagle (`TCP_NODELAY`),
   and sends the iperf3 cookie.
2. **JSON parameter exchange** – `ControlConnection.negotiate()`:
   - Waits for the `PARAM_EXCHANGE` byte from the server.
   - Sends a JSON object with fields such as `time` (duration),
     `len` (block size), and `parallel`.
   - Waits for the `CREATE_STREAMS` byte before opening the data connection.
3. **Data connection** – `ControlConnection.open_data_connection()` opens a
   second TCP socket (same host, port 5201), sends the cookie on the data
   channel, and waits for the server to send `TEST_START` and `TEST_RUNNING`.
4. **Data transfer** – `ControlConnection.send_data()`:
   - Sends random bytes continuously for the configured duration
     (e.g., 10–60 seconds).
   - Every 200 ms, samples the Linux `TCP_INFO` struct via
     `getsockopt(TCP_INFO)` and records RTT, cwnd, retransmissions, bytes
     acked, bytes sent, etc.
5. **Termination** – after the duration:
   - Stops sending, sends the `TEST_END` byte on the control connection.
   - Receives the server’s results JSON, sends back client utilization
     statistics, and finally sends the `IPERF_DONE` byte.

The client successfully completes tests against multiple public servers listed
on [iperf3serverlist.net](https://iperf3serverlist.net), including servers
operated by Leaseweb and WOBcom. Misbehaving servers (wrong greeting byte,
connection refused, etc.) are detected and skipped with automatic replacement.

#### Robustness

The client explicitly handles:

- Connection timeouts and resets.
- Servers that send an unexpected control byte (e.g., 255 instead of
  `PARAM_EXCHANGE`).
- Non‑responsive or overloaded servers by retrying once, then selecting a
  replacement server from the list.

### 1(b) Destination selection and goodput measurement

From `listed_iperf3_servers.csv` (exported from iperf3serverlist.net) the
script:

- Loads 193 candidate servers.
- Randomly selects **n** servers (default 10; I used 5 in the example run) via
  `-n, --num-servers`.
- For each server:
  - Runs an iperf3 test for **d** seconds (`-d, --duration`, default 10).
  - If a server fails twice in a row, it is replaced by a new random server.

At each 200 ms interval during the transfer, I compute the **goodput**:

\[
\text{goodput}(t)
  = \frac{\text{bytes\_acked}(t) - \text{bytes\_acked}(t-1)}{\Delta t} \cdot 8
\quad [\text{bits/s}]
\]

and record it together with the TCP_INFO fields in a per‑destination CSV file
named `<host>_<port>.csv`.

### 1(c) Throughput time series and summary table

For each destination, the logged goodput samples form a time series over the
experiment duration. In the report I include plots (generated from these CSVs)
that show:

- **Throughput vs time** for each server.
- A **summary table** with per‑destination:
  - Min, median, average, and 95th‑percentile goodput.

Example numbers from a representative run with 5 destinations:

- Average throughput across servers: **239.37 Mbps**  
- Min across servers: **144.79 Mbps**  
- Max across servers: **344.72 Mbps**



---

## 2. TCP Stats Tracing During Transfer

### 2(a) TCP_INFO logging

While the client is sending, every 200 ms `ControlConnection.send_data()` calls
`getsockopt(TCP_INFO)` and decodes the struct into the following fields:

- **Required:**
  - `timestamp` – time since start of the transfer.
  - `snd_cwnd` – congestion window (segments).
  - `rtt_ms` – smoothed RTT, converted from microseconds.
  - **Loss proxy** – derived from:
    - `retransmits`, `lost`, and `total_retrans` counters.
- **Additional / recommended:**
  - `rttvar_ms` – RTT variance.
  - `pacing_rate_bps` – pacing rate.
  - `bytes_acked` – cumulative bytes acknowledged.
  - `bytes_sent` – cumulative bytes sent.
  - `delivered` – total packets delivered (for delivery‑rate style metrics).

These statistics are stored alongside the interval goodput in CSV files, one
per destination.

### 2(b) Visualizations

For a **representative destination**, I generated PDF plots that show:

1. **Time series plots:**
   - cwnd (`snd_cwnd`) vs time.
   - RTT vs time.
   - Loss proxy (e.g., incremental retransmissions) vs time.
   - Throughput vs time.

2. **Scatter plots:**
   - cwnd vs goodput.
   - RTT vs goodput.
   - Loss signal vs goodput.

These are automatically generated from the trace CSVs and saved as PDFs. The
plots illustrate the expected relationships:

- cwnd and goodput are positively correlated up to the point where increased
  cwnd no longer yields higher goodput due to congestion.
- Higher RTT and higher loss both tend to correspond to lower goodput,
  especially when cwnd has already grown large.

### 2(c) Observations

From the plots:

- **cwnd vs goodput:** increasing cwnd initially increases goodput almost
  linearly; once cwnd exceeds the path’s bandwidth‑delay product (BDP), the
  curve flattens and additional cwnd mostly increases queueing delay.
- **RTT vs goodput:** when RTT is low, goodput is high and stable. As RTT
  increases (queue buildup), goodput may plateau or even drop slightly because
  of bufferbloat and retransmissions.
- **Loss vs goodput:** bursts of retransmissions/loss correlate with temporary
  drops in goodput and multiplicative decreases in cwnd. These events mark the
  points where the sender has clearly overshot the capacity of the path.

Overall, the traces exhibit the familiar congestion‑avoidance sawtooth:
gradual cwnd increase while RTT remains stable, followed by a spike in loss
and RTT, then a sharp cwnd reduction.

---

## 3. ML Model + Hand‑Written Congestion Avoidance Algorithm

### 3(a) Dataset and preprocessing

I built the ML dataset directly from the TCP_INFO traces and goodput
measurements output by the client.

#### Features \(X(t)\)

At each sampling time \(t\) (every ~200 ms) I construct:

\[
X(t) =
[\text{goodput}(t),
 \text{RTT}(t),
 \text{loss\_rate}(t),
 \text{snd\_cwnd}(t),
 \text{rttvar}(t),
 \text{pacing\_rate}(t),
 \text{bytes\_acked}(t),
 \text{bytes\_sent}(t),
 \text{goodput}(t-1),
 \text{RTT}(t-1),
 \text{loss\_rate}(t-1),
 \text{snd\_cwnd}(t-1)]
\]

More concretely:

- **Base features:**
  - `goodput_Mbps(t)` – interval goodput in Mbps.
  - `rtt_ms(t)` – RTT estimate.
  - `snd_cwnd(t)` – current congestion window (segments).
  - `loss_rate(t)` – loss proxy computed as:
    \[
      \text{loss\_rate}(t) =
      \frac{\Delta \text{retrans}(t)}{\Delta t}
    \]
    where \(\Delta \text{retrans}(t)\) is the change in retransmission counter.
  - `rttvar_ms(t)` – RTT variation.
  - `pacing_rate_bps(t)` – pacing rate.
  - `bytes_acked(t)`, `bytes_sent(t)` – cumulative counters.
- **Lag features (one‑step history):**
  - `goodput_prev = goodput_Mbps(t-1)`.
  - `rtt_prev = rtt_ms(t-1)`.
  - `cwnd_prev = snd_cwnd(t-1)`.
  - `loss_prev = loss_rate(t-1)`.

#### Label \(y(t)\)

The learning target is the **congestion window decision**, expressed as the
change in cwnd between successive samples:

\[
y(t) = Δ\text{snd\_cwnd}(t) =
       \text{snd\_cwnd}(t) - \text{snd\_cwnd}(t-1)
\]

This matches the assignment’s definition of predicting the next congestion
window update.

#### Preprocessing

- **Scaling:**  
  - Goodput is converted to Mbps (`goodput_bps / 1e6`) to keep values on a
    human‑scale range.
  - Loss rate is computed per second via the retransmission counter delta
    divided by the interval length.
- **Cleaning:**  
  - The first row (where `.diff()` produces NaNs) is dropped.
  - Any rows where a lag feature is NaN are also dropped.
- **Global dataset:**  
  - For each destination trace, I build a per‑trace dataset and tag it with a
    `trace_id`.
  - All traces are concatenated into a single global dataset, with a
    `trace_id` column used for per‑trace splitting.

### 3(b) Model, η objective, and plots

#### Train/test splitting

For each `trace_id`:

1. Sort samples by timestamp.
2. Use the first 70% of samples as **train** and the remaining 30% as **test**
   (no shuffling, to respect time order).

All train segments are combined into a global training set; all test segments
form the global test set.

#### Model choice

I use **GradientBoostingRegressor** from scikit‑learn:

- Handles non‑linear relationships between cwnd, RTT, loss, and goodput.
- Works well with mixed‑scale features without heavy normalization.
- Trains quickly on a CPU for the moderate dataset size I have.

#### η‑based objective

The assignment defines:

\[
η(t-1) = \text{goodput}(t) - α \cdot \text{RTT}(t) - β \cdot \text{loss}(t)
\]

For training, I use an **η‑weighted MSE loss** on \(y(t) = Δ\text{cwnd}(t)\):

1. For every sample I compute \(η(t-1)\) from the observed
   `goodput_Mbps(t)`, `rtt_ms(t)`, and `loss_rate(t)` using \(α = 0.01\) and
   \(β = 1.0\).
2. I map these η values to **strictly positive sample weights**
   \(w(t) = f(η(t-1))\) by normalizing η, applying a linear mapping around 1,
   and clipping to a range \([w_{\min}, w_{\max}]\) (e.g., [0.2, 3.0]). Samples
   with higher η (high goodput, low RTT/loss) receive larger weights.
3. The Gradient Boosting model is then trained to minimize the weighted loss
   \(\sum_t w(t)\,(Δ\text{cwnd}_\text{pred}(t) - Δ\text{cwnd}(t))^2\), so the
   effective training objective directly depends on η.

For **hyperparameter selection**, I still measure how well the predicted
updates align with η:

1. For each candidate configuration (number of trees, depth, learning rate),
   I fit the model on a time‑ordered training subset using the η‑derived
   weights.
2. On a validation subset, I compute the correlation between the predicted
   Δcwnd and the corresponding η(t−1) values.
3. I select the configuration with the **strongest positive correlation**
   between predicted Δcwnd and η.

The best model in one representative run used:

- `n_estimators = 150`, `max_depth = 3`, `learning_rate = 0.05`
with a test MSE of about **1.04** on Δcwnd.

#### Cwnd time‑series plots

For each of 5 destinations, I generate a cwnd time‑series plot:

1. Plot the **ground‑truth snd_cwnd** over the entire trace (train + test).
2. Starting at the test split, roll out the **predicted cwnd**:
   - Initialize `cwnd_pred` at the true cwnd at the start of the test horizon.
   - For each time step \(k\) in the test region:
     - Build the feature vector using observed stats at time \(k\), but set
       `cwnd_prev` to the **previous predicted** cwnd.
     - Predict `Δcwnd_pred(k)` from the model and update:
       \[
       \text{cwnd\_pred}(k) =
         \max(1, \text{cwnd\_pred}(k-1) + Δ\text{cwnd\_pred}(k))
       \]
3. Overlay `cwnd_pred` on the same plot, but only over the test region.

These plots are written to:

- `hw2/client/q3_outputs/q3_cwnd_trace_0.pdf` … `q3_cwnd_trace_4.pdf`.

Visually, the predicted cwnd curves follow the ground‑truth cwnd reasonably
well in magnitude and trend, without diverging or exploding.

### 3(c) Hand‑written congestion window update algorithm

#### Insights from the learned model

Feature importances from the trained model (typical ordering):

1. `cwnd_prev` – previous cwnd value.
2. `loss_rate` – recent loss signal.
3. `snd_cwnd` – current cwnd.
4. `rtt_ms` – current RTT.
5. `goodput_prev`, `goodput_Mbps`.
6. Remaining features: pacing rate, rttvar, bytes_acked/sent, lagged loss/RTT.

This matches intuition: the controller primarily pays attention to cwnd
history and loss, with RTT and goodput providing secondary refinement.

#### Proposed cwnd update rule

Based on these observations and standard congestion‑control principles, I
propose the following **offline, hand‑written** congestion window update rule:

Let:

- \(g(t)\) – interval goodput (Mbps).
- \(r(t)\) – RTT (ms).
- \(ℓ(t)\) – loss_rate (e.g., retransmissions/sec).
- \(c(t)\) – cwnd in segments at time \(t\).

Define an η‑like score:

\[
η(t) = g(t) - α \cdot r(t) - β \cdot ℓ(t)
\]

with, for example, \(α = 0.01\) and \(β = 1.0\).

Then update cwnd every sampling interval as:

```text
if ℓ(t) > L_high or r(t) > R_high:
    # clear sign of congestion: back off aggressively
    c(t+1) = max(1, ceil(c(t) / 2))
elif η(t) > η_high:
    # path is under‑utilized: additive increase
    c(t+1) = c(t) + A
elif η(t) < η_low:
    # poor objective but no hard congestion signal:
    # small decrease to shed queueing load
    c(t+1) = max(1, c(t) - D)
else:
    # near operating point: keep cwnd steady
    c(t+1) = c(t)
```

Typical parameter choices:

- \(L_{\text{high}}\): small but non‑zero loss rate (e.g., a few
  retransmissions per interval).
- \(R_{\text{high}}\): RTT significantly above the baseline (queueing delay).
- \(η_{\text{high}}\): high goodput with low RTT and loss.
- \(η_{\text{low}}\): low goodput and/or high RTT/loss.
- \(A\): small additive increment (e.g., 1–2 segments per interval).
- \(D\): small decrement (e.g., 1 segment).

#### Justification

- When **loss or RTT spikes** (`ℓ(t) > L_high` or `r(t) > R_high`), the rule
  halves cwnd, following the classic AIMD multiplicative decrease. This reacts
  quickly when the path is clearly over‑loaded.
- When **η is high**, goodput is high and RTT/loss are low, suggesting that
  the path is under‑utilized; the rule increases cwnd additively, probing for
  more bandwidth.
- When **η is low but without sharp loss/RTT signals**, the rule gently
  reduces cwnd to relieve queueing, moving cwnd back toward the BDP.
- When η is in the middle and there is no congestion signal, cwnd is held
  steady, which stabilizes the connection around a good operating point.

This rule is rooted in the **observed behavior** of the learned model
(importance of `cwnd_prev`, `loss_rate`, `snd_cwnd`, and RTT) while remaining
simple, deterministic, and implementable without invoking the model at
runtime. It respects:

- The **bandwidth‑delay product**: cwnd tends to settle near the amount of
  data that fits in flight at high throughput and moderate RTT.
- **Queueing**: excessive cwnd produces higher RTT and loss, triggering
  multiplicative decrease.
- The relationship between **cwnd and goodput**: increases in cwnd are only
  recommended when they actually improve η, not blindly.

