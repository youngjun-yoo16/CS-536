#!/usr/bin/env python3
"""
HW2 end-to-end driver.

Runs the full Assignment 2 pipeline (Q1, Q2, Q3) in one shot:

1. Throughput tests against iperf3 servers using client/main.py.
2. Q1/Q2 plotting using client/plot.py.
3. Q3 ML training and cwnd rollout plots using client/ml_pipeline.py.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


def _run_step(cmd: List[str], cwd: Path, description: str) -> None:
    print(f"\n[STEP] {description}")
    print(f"[CMD]  {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise SystemExit(
            f"[ERROR] Step failed ({description}) with exit code {result.returncode}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run the full HW2 pipeline: iperf tests (Q1), TCP stats plots (Q2), "
            "and ML congestion control (Q3)."
        )
    )
    parser.add_argument(
        "--server-list",
        type=str,
        default="hw2/client/listed_iperf3_servers.csv",
        help=(
            "CSV file containing candidate iperf3 servers "
            "(default: hw2/client/listed_iperf3_servers.csv)."
        ),
    )
    parser.add_argument(
        "-n",
        "--num-servers",
        type=int,
        default=5,
        help="Number of servers to test (default: 5).",
    )
    parser.add_argument(
        "-d",
        "--duration",
        type=int,
        default=10,
        help="Test duration per server in seconds (default: 10).",
    )
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=30,
        help="Socket timeout in seconds for iperf tests (default: 30).",
    )
    parser.add_argument(
        "--traces-dir",
        type=str,
        default="hw2/client",
        help="Directory where per-destination CSV traces are written (default: hw2/client).",
    )
    parser.add_argument(
        "--plots-dir",
        type=str,
        default="hw2/client",
        help="Base directory to write Q1/Q2 plots (default: hw2/client).",
    )
    parser.add_argument(
        "--q3-output-dir",
        type=str,
        default="hw2/client/q3_outputs",
        help="Directory to write Q3 cwnd plots (default: hw2/client/q3_outputs).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.01,
        help="Alpha parameter in η(t-1) = goodput - α*RTT - β*loss (default: 0.01).",
    )
    parser.add_argument(
        "--beta",
        type=float,
        default=1.0,
        help="Beta parameter in η(t-1) = goodput - α*RTT - β*loss (default: 1.0).",
    )

    args = parser.parse_args()

    # Resolve paths relative to the repository root (one level above hw2/).
    hw2_dir = Path(__file__).resolve().parent
    repo_root = hw2_dir.parent

    client_dir = hw2_dir / "client"
    client_main = client_dir / "main.py"
    plot_script = client_dir / "plot.py"
    ml_script = client_dir / "ml_pipeline.py"

    server_list = (repo_root / args.server_list).resolve()
    traces_dir = (repo_root / args.traces_dir).resolve()
    plots_dir = (repo_root / args.plots_dir).resolve()
    q3_output_dir = (repo_root / args.q3_output_dir).resolve()

    if not server_list.exists():
        raise SystemExit(f"[ERROR] Server list not found at {server_list}")

    print("[INFO] Repository root:", repo_root)
    print("[INFO] Using server list:", server_list)
    print("[INFO] Traces directory:", traces_dir)
    print("[INFO] Q1/Q2 plots base directory:", plots_dir)
    print("[INFO] Q3 output directory:", q3_output_dir)

    # 1) Run throughput client to generate per-destination CSV traces.
    client_cmd = [
        sys.executable,
        str(client_main),
        "-n",
        str(args.num_servers),
        "-d",
        str(args.duration),
        "-t",
        str(args.timeout),
    ]
    # The client currently reads its server list from a fixed path; ensure the
    # caller has placed the desired CSV at that location. The --server-list
    # argument here mainly documents the expected input file.
    _run_step(client_cmd, cwd=repo_root, description="Run iperf throughput client (Q1 data collection)")

    # 2) Generate Q1/Q2 plots from the CSV traces.
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_cmd = [
        sys.executable,
        str(plot_script),
        "--traces-dir",
        str(traces_dir),
        "--output-dir",
        str(plots_dir),
    ]
    _run_step(plot_cmd, cwd=repo_root, description="Generate Q1/Q2 plots")

    # 3) Run the ML pipeline for Q3.
    q3_output_dir.mkdir(parents=True, exist_ok=True)
    ml_cmd = [
        sys.executable,
        str(ml_script),
        "--traces-dir",
        str(traces_dir),
        "--output-dir",
        str(q3_output_dir),
        "--min-traces",
        "5",
        "--alpha",
        str(args.alpha),
        "--beta",
        str(args.beta),
    ]
    _run_step(ml_cmd, cwd=repo_root, description="Train ML model and generate Q3 cwnd plots")

    print("\n[DONE] Full HW2 pipeline completed successfully.")
    print("       - Traces (CSV):", traces_dir)
    print("       - Q1/Q2 plots: ", plots_dir)
    print("       - Q3 plots:    ", q3_output_dir)


if __name__ == "__main__":
    main()

