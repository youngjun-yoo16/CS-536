# TCP Expo Congestion Control

TCP Expo is a delay-based congestion control algorithm we built as a kernel module for CS536. Instead of waiting for packet loss to know the network is congested (like Reno and CUBIC do), Expo watches the round-trip time. When RTT starts climbing, it means packets are sitting in router queues — the network is getting full even though nothing has been dropped yet.

The core idea is **momentum**: we track how much RTT has inflated compared to the baseline (the lowest RTT we've seen). If RTT is still close to baseline, we grow the window aggressively. If it's spiking up, we slow down. If it spikes past 75% inflation, we do a small reduction called a **Negative Pulse** (thanks to the professor advice) — dropping the window by about 3% to reduce the queue back down without throwing away throughput.

There are three zones:
- **Clean** (< 30% RTT inflation) — grow fast, the pipe has room
- **Build** (30–75%) — some queuing, grow carefully
- **Expo event** (> 75%) — too much delay, fire a Negative Pulse

This lets Expo fill the pipe without flooding it. In our flent tests it matched or beat CUBIC and Reno on throughput while keeping latency low, and got near-perfect fairness (0.9998 Jain's index) across 8 concurrent streams.

We also wanted to have fun with it and experimented a bit — we start with an initial window of 20 segments instead of the default 10, which gets data moving faster on high-bandwidth links. And in the clean zone we have an acceleration system: the longer the connection goes without hitting congestion, the faster we let the window grow (up to 16x the base rate). 

## Results (60 second tests)

Single stream (1 TCP):

| Algorithm | Throughput (Mbps) | RTT avg (ms) | Ping avg (ms) |
|-----------|-------------------|---------------|----------------|
| CUBIC     | 100.24            | 38.55         | 34.33          |
| RENO      | 97.02             | 37.98         | 33.31          |
| **EXPO**  | **96.41**         | **39.56**     | **35.33**      |
| BBR       | 84.46             | 45.33         | 40.24          |

8 streams (8 TCP):

| Algorithm | Total Throughput (Mbps) | Jain's Fairness | Ping avg (ms) | Avg RTT (ms) |
|-----------|-------------------------|-----------------|----------------|---------------|
| CUBIC     | 114.64                  | 0.9904          | 48.77          | 53.56         |
| **EXPO**  | **112.52**              | **0.9998**      | **53.63**      | **59.69**     |
| RENO      | 97.19                   | 0.9931          | 52.90          | 59.63         |
| BBR       | 89.79                   | 0.9884          | 50.60          | 57.93         |

Expo gets close to CUBIC on throughput but has way better fairness between flows — the per-flow throughput ranged from 13.68 to 14.43 Mbps across all 8 streams, which is basically even.

## Results (20 second tests)

With shorter tests Expo doesn't do as well since the acceleration and rtt_min aging need time to warm up, but it's still competitive.

Single stream (1 TCP):

| Algorithm | Throughput (Mbps) | RTT avg (ms) | Ping avg (ms) |
|-----------|-------------------|---------------|----------------|
| EXPO      | 92.43             | 50.43         | 32.84          |
| BBR       | 92.40             | 48.47         | 33.49          |
| CUBIC     | 91.28             | 40.80         | 27.08          |
| RENO      | 90.25             | 42.53         | 26.83          |

8 streams (8 TCP):

| Algorithm | Total Throughput (Mbps) | Jain's Fairness | Ping avg (ms) | Avg RTT (ms) |
|-----------|-------------------------|-----------------|----------------|---------------|
| RENO      | 98.71                   | 0.9810          | 36.46          | 58.07         |
| CUBIC     | 97.80                   | 0.8498          | 37.76          | 63.19         |
| EXPO      | 83.41                   | 0.9682          | 45.03          | 72.50         |
| BBR       | 77.32                   | 0.9935          | 37.62          | 59.89         |

At 20 seconds Expo drops behind on total throughput in the 8-stream test, but still keeps better fairness than CUBIC (0.97 vs 0.85). The 60-second run is where it really shows its strengths.

Obviously, this was in a small environment with a single bottleneck link and no cross-traffic, but it's a fun proof of concept for how delay-based congestion control can work in the kernel. So we can't say it outperforms the others, sadly.

### For more information
Please refer to the **TCP Expo Report PDF**, which includes more detailed experiments and analysis. You can find it in the repository as **report/TCP Expo Report.pdf**.

---

## KERNEL MODULE SETUP
We used Ubuntu 22.04 for this project. Start from a fresh install on any machine/VM of your choice.

### Prerequisites

```
sudo apt update
sudo apt install -y \
  build-essential libncurses-dev libelf-dev libssl-dev \
  bison flex pkg-config dwarves

sudo apt install -y linux-source-5.15.0
```

Then extract the kernel source:

```
cd /usr/src
sudo tar xf linux-source-5.15.0.tar.bz2
sudo chown -R $USER:$USER linux-source-5.15.0
```

---

### Kernel tree setup (one-time)

These steps wire the module into the kernel build system. Only need to do this once.

1. Edit `net/ipv4/Kconfig` — inside the `if TCP_CONG_ADVANCED` block, add:

```
source "net/ipv4/tcp_expo/Kconfig.fragment"
```

2. Edit `net/ipv4/Makefile` — add:

```
obj-$(CONFIG_TCP_EXPO) += tcp_expo/
```

3. Enable the module in menuconfig:

```
make menuconfig
```

Go to `Networking support → Networking options → TCP: advanced congestion control → TCP Expo congestion control` and select `<M>`.

4. Prepare the kernel build (from kernel source root):

```
make oldconfig
make prepare
make modules_prepare
```

---

### Building and loading

We have two scripts that handle building and loading so you don't have to do it manually.

**`build.sh`** — syncs the source into the kernel tree, compiles the module, and unloads the old version. Heads up: this kills active TCP connections since it has to remove the running module, so you'll need to reconnect SSH after.

Make sure to change LOCAL_DIR to where the tcp_expo source is.

```
./build.sh
```

**`change.sh`** — loads the compiled module and switches the system to use expo. Run this after reconnecting.

```
./change.sh
```

You can verify it's active with:

```
sysctl net.ipv4.tcp_congestion_control
```

---

## How to run our testing suite

We need flent and iperf3 installed. The test server was netserver on control port 4444 provided by the Professor.

```
sudo apt install -y flent iperf3 netperf 
```

(Make sure that flent is on the last version — the one in apt is old and doesn't have some features we use. You can install from pip if needed: `pip3 install --user flent`.)

`run_flent_tests.sh` runs everything automatically: it loops through reno, bbr, cubic, and expo, runs both a single-stream (`tcp_upload`) and 8-stream (`tcp_8up`) test for each, generates throughput/cwnd/rtt plots, and builds comparison CSVs.

```
./run_flent_tests.sh
```

The duration is set at the top of the script (`DURATION=60` for 60 seconds). We found that 60 seconds gives expo enough time to converge — shorter tests (20s) don't let the `rtt_min` aging and `clean_rtts` acceleration ramp up fully.

Each test does:
- Sets the congestion control via `sysctl`
- Runs `flent tcp_upload` (single stream) or `flent tcp_8up` (8 streams) against the test server
- Captures socket stats (`--socket-stats`) for cwnd/rtt data
- Generates `.png` plots for throughput, cwnd, and rtt

After all tests finish, `generate_comparison.py` runs and produces three CSVs in `plots/`:
- `single_stream_comparison.csv` — throughput, rtt, ping, cwnd per algorithm
- `multi_stream_comparison.csv` — total throughput, Jain's fairness index, ping per algorithm  
- `multi_stream_per_flow.csv` — per-flow breakdown for the 8-stream test

You can also regenerate the CSVs anytime without re-running tests:

```
python3 generate_comparison.py
```

#### Output structure:

```
plots/
  single_stream_comparison.csv
  multi_stream_comparison.csv
  multi_stream_per_flow.csv
  reno/
    1tcp/   (throughput.png, cwnd.png, rtt.png)
    8tcp/   (throughput.png, cwnd.png, rtt.png, diagnosis.png)
  bbr/
    1tcp/
    8tcp/
  cubic/
    1tcp/
    8tcp/
  expo/
    1tcp/
    8tcp/
```

