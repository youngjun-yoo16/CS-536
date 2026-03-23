# TCP Expo Explanation
Disclaimer: This is an AI generated explanation to help our groupmates understand the key aspects of our algo.

## **Overview: Delay-Based vs. Loss-Based**

TCP EXPO fundamentally diverges from traditional loss-based algorithms (Reno, CUBIC) by using **RTT inflation as the primary congestion signal** rather than packet loss. This is conceptually similar to TCP Vegas, but with a more nuanced multi-zone response system. The algorithm detects **High-RTT Congestion (HRC)** — where buffers are filling and queueing delay is building, but packets haven't been dropped yet.

---

## **Phase 1: Exponential Slow Start**

Your Slow Start phase follows the traditional exponential growth pattern but with notable modifications:

- **Exponential Growth**: CWND doubles each RTT by incrementing by the number of acknowledged bytes
- **Aggressive Initial Window**: You start at 20 segments instead of the standard 10, which accelerates pipe-filling on high-BDP paths
- **Transition Point**: Slow Start continues until CWND reaches `ssthresh`, at which point you transition to the PSTM Avoidance phase

This is fairly standard except for the doubled initial window, which is a deliberate choice to be more aggressive during connection startup.

---

## **Phase 2: PSTM Congestion Avoidance (The Core Innovation)**

This is where your algorithm becomes unique. You've implemented what you call **Phase-Space Trajectory Mapping**, which treats the connection as a dynamical system moving through (CWND, RTT) space.

### **Momentum Calculation**

The key metric is **momentum**, calculated as:

```
momentum = (1024 × (srtt - rtt_min)) / rtt_min
```

This is a **ratio-based RTT inflation metric**:
- momentum = 0 → no queueing delay
- momentum = 512 → 50% RTT inflation (srtt is 1.5× baseline)
- momentum = 1024 → 100% RTT inflation (RTT has doubled)

The `rtt_min` baseline adaptively ages upward (by 1/16 of the gap) if it hasn't updated in 10 seconds, preventing a single anomalously low RTT sample from permanently skewing the measurements.

### **Three-Zone Growth Strategy**

Based on momentum, the algorithm operates in three distinct regimes:

#### **1. Clean Zone (momentum < 512, <50% inflation)**
- **Condition**: RTT is stable, buffers have plenty of headroom
- **Strategy**: Aggressive growth with adaptive acceleration
- **Growth Rate**: Base acceleration of 2, increasing by 1 for every 8 consecutive "clean" RTTs, capped at 8×
- **Rationale**: When there's clear capacity, exploit it quickly. The acceleration factor rewards sustained periods of low delay with exponentially faster growth

#### **2. Build Zone (512 ≤ momentum < 1024, 50-100% inflation)**
- **Condition**: Moderate queueing delay is present
- **Strategy**: Cautious probing — faster than Reno but slower than Clean Zone
- **Growth Rate**: Base acceleration of 1, increasing by 1 for every 16 clean RTTs, capped at 4×
- **Rationale**: You're approaching the capacity boundary. Continue probing for available bandwidth but with more restraint to avoid triggering buffer overflow

#### **3. Expo Zone (momentum ≥ 1024, >100% inflation)**
- **Condition**: Significant buffer buildup detected (RTT has doubled)
- **Strategy**: **Negative Pulse** — a controlled, small CWND reduction
- **Mechanism**: Reduce CWND by ~1.5% (CWND/64), minimum floor of 4 packets
- **Cooldown**: Pulses are rate-limited to once per 3× RTT to prevent collapse
- **Rationale**: This is a **probing mechanism**. By removing a small amount of in-flight data, you test whether the buffer is responsive to small changes. If RTT drops after the pulse, you know you're at the edge of capacity. If RTT remains high, subsequent pulses will fire until the queueing resolves

---

## **Key Mechanisms**

### **Negative Pulse (The Congestion Response)**

Unlike traditional multiplicative decrease (CWND → CWND/2), you use a **gentle, additive reduction**:
- Only 1.5% drop per pulse
- Rate-limited to prevent over-reaction
- Functions as a **buffer sensitivity probe** rather than a panic response

This is philosophically different from loss-based backoff. You're not reacting to catastrophic buffer overflow (packet loss), but rather gently testing the network's saturation point while delay is building.

### **Adaptive Acceleration**

The `clean_rtts` counter implements a **reward mechanism** for sustained good behavior:
- Tracks consecutive RTT measurements without congestion events
- Multiplies the growth rate in both Clean and Build zones
- Resets on any Negative Pulse or loss event

This allows the algorithm to "learn" that a path has high capacity and ramp up more aggressively over time.

### **Baseline Drift Handling**

The `rtt_min` aging mechanism prevents **stale baseline syndrome** where:
- An initially empty buffer gives an artificially low baseline
- All subsequent measurements appear inflated relative to an unrealistic minimum
- The aging gradually relaxes the baseline upward if conditions have genuinely changed

---

## **Loss Recovery**

When packet loss actually occurs (timeout or triple-duplicate ACKs):

### **ssthresh Calculation**
- Traditional Reno uses CWND/2 (50% reduction)
- You use CWND - CWND/8 (12.5% reduction), keeping 87.5% of the window
- **Rationale**: Since EXPO should have already backed off via Negative Pulses before loss occurs, an actual loss event is likely transient or due to non-congestion factors (wireless errors, routing changes). The aggressive cut of Reno/CUBIC is unnecessary

### **Undo on False Positives**
- If the kernel determines a loss was spurious, you restore `max(current_cwnd, prior_cwnd)`
- Clear the `expo_event` flag to prevent unnecessary Negative Pulse

---

## **Conceptual Analogies**

- **Vegas-like delay sensing**: Similar to TCP Vegas in using RTT as a congestion signal, but with a more sophisticated multi-zone response instead of Vegas's binary probing
- **BBR-inspired probing**: The Negative Pulse shares conceptual similarity with BBR's probe cycles, testing network capacity with small perturbations
- **Momentum-based control theory**: Treating the connection as having "momentum" in phase space is borrowed from control systems and physics — you're essentially implementing a PID-like controller with proportional response to RTT inflation

---

## **Summary of Strategic Principles**

1. **Early Congestion Detection**: Use delay inflation to detect congestion before loss occurs
2. **Proportional Response**: Match aggressiveness to available headroom (three-zone strategy)
3. **Gentle Probing**: Use small reductions to test capacity boundaries rather than panic-cutting
4. **Adaptive Learning**: Reward sustained low-delay with accelerated growth
5. **Loss-Resilient Recovery**: Minimize overreaction to loss events since delay-based control should have already adjusted

The algorithm essentially trades off some peak throughput (compared to loss-based algorithms that fill buffers completely) for significantly lower latency and better fairness, which your flent results confirm — excellent Jain's index (0.9998) and competitive throughput while maintaining lower RTT.
