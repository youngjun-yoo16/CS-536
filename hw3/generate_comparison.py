#!/usr/bin/env python3
"""
Generate CSV comparison tables from flent test results.
Parses the summary text files and produces:
  - single_stream_comparison.csv  (1tcp results)
  - multi_stream_comparison.csv   (8tcp results, aggregate)
  - multi_stream_per_flow.csv     (8tcp results, per-flow fairness)
  - fairness_index.csv            (Jain's fairness index per algorithm)
"""

import os
import re
import csv
import sys
import math

PLOTS_BASE = "/home/hw3/plots"
ALGOS = ["reno", "bbr", "cubic", "expo"]


def parse_summary(filepath):
    """Parse a flent summary text file into a dict of metric -> (avg, median, p99)."""
    metrics = {}
    if not os.path.exists(filepath):
        return metrics

    with open(filepath, "r") as f:
        text = f.read()

    # Join continuation lines (some lines wrap due to "Mbits/s" split)
    text = text.replace("Mbits\n/s", "Mbits/s")
    text = text.replace("Mbi\nts/s", "Mbits/s")

    for line in text.split("\n"):
        # Match lines like:  "  TCP upload   :   237.42   240.90   283.67 Mbits/s"
        #                or: "  Ping (ms) ICMP   :   12.88   11.50   24.28 ms"
        m = re.search(
            r"([\w\s\(\):]+?)\s*:\s+([\d.]+|N/A)\s+([\d.]+|N/A)\s+([\d.]+|N/A)",
            line,
        )
        if m:
            name = m.group(1).strip()
            avg = m.group(2)
            median = m.group(3)
            p99 = m.group(4)

            def to_float(v):
                return float(v) if v != "N/A" else None

            metrics[name] = {
                "avg": to_float(avg),
                "median": to_float(median),
                "p99": to_float(p99),
            }

    return metrics


def jains_fairness(throughputs):
    """Compute Jain's fairness index for a list of throughput values."""
    n = len(throughputs)
    if n == 0:
        return None
    s = sum(throughputs)
    sq = sum(x * x for x in throughputs)
    if sq == 0:
        return None
    return (s * s) / (n * sq)


def generate_single_stream_csv():
    """Generate comparison CSV for single stream (1tcp) tests."""
    output = os.path.join(PLOTS_BASE, "single_stream_comparison.csv")
    rows = []

    for algo in ALGOS:
        filepath = os.path.join(PLOTS_BASE, algo, "1tcp", f"{algo}_single.flent.gz")
        metrics = parse_summary(filepath)
        if not metrics:
            continue

        # Extract key metrics
        ping = metrics.get("Ping (ms) ICMP", {})
        upload = metrics.get("TCP upload", {})
        cwnd = metrics.get("TCP upload::tcp_cwnd", {})
        delivery = metrics.get("TCP upload::tcp_delivery_rate", {})
        pacing = metrics.get("TCP upload::tcp_pacing_rate", {})
        rtt = metrics.get("TCP upload::tcp_rtt", {})
        rtt_var = metrics.get("TCP upload::tcp_rtt_var", {})

        rows.append({
            "Algorithm": algo.upper(),
            "Throughput_avg (Mbps)": upload.get("avg"),
            "Throughput_median (Mbps)": upload.get("median"),
            "Throughput_p99 (Mbps)": upload.get("p99"),
            "Ping_avg (ms)": ping.get("avg"),
            "Ping_median (ms)": ping.get("median"),
            "Ping_p99 (ms)": ping.get("p99"),
            "CWND_avg": cwnd.get("avg"),
            "CWND_median": cwnd.get("median"),
            "RTT_avg (ms)": rtt.get("avg"),
            "RTT_median (ms)": rtt.get("median"),
            "RTT_p99 (ms)": rtt.get("p99"),
            "RTT_var_avg (ms)": rtt_var.get("avg"),
            "Delivery_rate_avg (Mbps)": delivery.get("avg"),
            "Pacing_rate_avg (Mbps)": pacing.get("avg"),
        })

    if rows:
        with open(output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Created: {output}")
    return rows


def generate_multi_stream_csv():
    """Generate comparison CSV for 8-stream (8tcp) tests — aggregate view."""
    output = os.path.join(PLOTS_BASE, "multi_stream_comparison.csv")
    rows = []

    for algo in ALGOS:
        filepath = os.path.join(PLOTS_BASE, algo, "8tcp", f"{algo}_full_load.flent.gz")
        metrics = parse_summary(filepath)
        if not metrics:
            continue

        ping = metrics.get("Ping (ms) ICMP", {})
        upload_avg = metrics.get("TCP upload avg", {})
        upload_sum = metrics.get("TCP upload sum", {})

        # Collect per-flow throughputs and RTTs for fairness calculation
        flow_throughputs = []
        flow_rtts = []
        flow_cwnds = []
        for i in range(1, 9):
            flow = metrics.get(f"TCP upload::{i}", {})
            flow_rtt = metrics.get(f"TCP upload::{i}::tcp_rtt", {})
            flow_cwnd = metrics.get(f"TCP upload::{i}::tcp_cwnd", {})
            if flow.get("avg") is not None:
                flow_throughputs.append(flow["avg"])
            if flow_rtt.get("avg") is not None:
                flow_rtts.append(flow_rtt["avg"])
            if flow_cwnd.get("avg") is not None:
                flow_cwnds.append(flow_cwnd["avg"])

        fairness = jains_fairness(flow_throughputs)
        avg_rtt = sum(flow_rtts) / len(flow_rtts) if flow_rtts else None
        avg_cwnd = sum(flow_cwnds) / len(flow_cwnds) if flow_cwnds else None
        min_tput = min(flow_throughputs) if flow_throughputs else None
        max_tput = max(flow_throughputs) if flow_throughputs else None

        rows.append({
            "Algorithm": algo.upper(),
            "Total_throughput (Mbps)": upload_sum.get("avg"),
            "Per_flow_avg (Mbps)": upload_avg.get("avg"),
            "Per_flow_min (Mbps)": min_tput,
            "Per_flow_max (Mbps)": max_tput,
            "Jains_fairness": round(fairness, 4) if fairness else None,
            "Ping_avg (ms)": ping.get("avg"),
            "Ping_median (ms)": ping.get("median"),
            "Ping_p99 (ms)": ping.get("p99"),
            "Avg_flow_RTT (ms)": round(avg_rtt, 2) if avg_rtt else None,
            "Avg_flow_CWND": round(avg_cwnd, 2) if avg_cwnd else None,
        })

    if rows:
        with open(output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Created: {output}")
    return rows


def generate_per_flow_csv():
    """Generate per-flow breakdown CSV for 8-stream tests."""
    output = os.path.join(PLOTS_BASE, "multi_stream_per_flow.csv")
    rows = []

    for algo in ALGOS:
        filepath = os.path.join(PLOTS_BASE, algo, "8tcp", f"{algo}_full_load.flent.gz")
        metrics = parse_summary(filepath)
        if not metrics:
            continue

        for i in range(1, 9):
            flow = metrics.get(f"TCP upload::{i}", {})
            flow_cwnd = metrics.get(f"TCP upload::{i}::tcp_cwnd", {})
            flow_rtt = metrics.get(f"TCP upload::{i}::tcp_rtt", {})
            flow_rtt_var = metrics.get(f"TCP upload::{i}::tcp_rtt_var", {})
            flow_delivery = metrics.get(f"TCP upload::{i}::tcp_delivery_rate", {})

            rows.append({
                "Algorithm": algo.upper(),
                "Flow": i,
                "Throughput_avg (Mbps)": flow.get("avg"),
                "Throughput_median (Mbps)": flow.get("median"),
                "Throughput_p99 (Mbps)": flow.get("p99"),
                "CWND_avg": flow_cwnd.get("avg"),
                "CWND_median": flow_cwnd.get("median"),
                "RTT_avg (ms)": flow_rtt.get("avg"),
                "RTT_median (ms)": flow_rtt.get("median"),
                "RTT_var_avg (ms)": flow_rtt_var.get("avg"),
                "Delivery_rate_avg (Mbps)": flow_delivery.get("avg"),
            })

    if rows:
        with open(output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Created: {output}")
    return rows


def print_summary_table(single_rows, multi_rows):
    """Print a human-readable comparison to stdout."""
    print("\n" + "=" * 80)
    print("  SINGLE STREAM COMPARISON (1 TCP)")
    print("=" * 80)
    if single_rows:
        header = f"{'Algorithm':<10} {'Throughput':>12} {'RTT avg':>10} {'RTT p99':>10} {'Ping avg':>10} {'CWND avg':>10}"
        print(header)
        print("-" * len(header))
        for r in sorted(single_rows, key=lambda x: x.get("Throughput_avg (Mbps)") or 0, reverse=True):
            print(f"{r['Algorithm']:<10} {r.get('Throughput_avg (Mbps)', 'N/A'):>10.2f}  {r.get('RTT_avg (ms)', 'N/A'):>10.2f} {r.get('RTT_p99 (ms)', 'N/A'):>10.2f} {r.get('Ping_avg (ms)', 'N/A'):>10.2f} {r.get('CWND_avg', 'N/A'):>10.2f}")

    print("\n" + "=" * 80)
    print("  8-STREAM COMPARISON (8 TCP)")
    print("=" * 80)
    if multi_rows:
        header = f"{'Algorithm':<10} {'Total Tput':>12} {'Fairness':>10} {'Ping avg':>10} {'Ping p99':>10} {'Avg RTT':>10}"
        print(header)
        print("-" * len(header))
        for r in sorted(multi_rows, key=lambda x: x.get("Total_throughput (Mbps)") or 0, reverse=True):
            fairness = r.get("Jains_fairness")
            fairness_str = f"{fairness:.4f}" if fairness else "N/A"
            print(f"{r['Algorithm']:<10} {r.get('Total_throughput (Mbps)', 'N/A'):>10.2f}  {fairness_str:>10} {r.get('Ping_avg (ms)', 'N/A'):>10.2f} {r.get('Ping_p99 (ms)', 'N/A'):>10.2f} {r.get('Avg_flow_RTT (ms)', 'N/A'):>10.2f}")
    print()


if __name__ == "__main__":
    print("\nGenerating comparison CSVs...")
    single = generate_single_stream_csv()
    multi = generate_multi_stream_csv()
    generate_per_flow_csv()
    print_summary_table(single, multi)
