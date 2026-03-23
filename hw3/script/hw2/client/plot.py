#!/usr/bin/env python3
"""
Q1/Q2 Plotting Script

Reads per-destination trace CSVs produced by main.py / control.py and
generates PDF plots required by Q1(c) and Q2(b) of the assignment.

Q1 outputs (all destinations together):
  q1_throughput_timeseries.pdf  – goodput time series for every destination
  q1_summary_table.pdf          – min / median / avg / p95 goodput table

Q2 outputs (single representative destination):
  q2_cwnd_timeseries.pdf        – snd_cwnd over time
  q2_rtt_timeseries.pdf         – RTT over time
  q2_loss_timeseries.pdf        – loss proxy over time
  q2_throughput_timeseries.pdf  – goodput over time
  q2_cwnd_vs_goodput.pdf        – scatter: snd_cwnd vs goodput
  q2_rtt_vs_goodput.pdf         – scatter: RTT vs goodput
  q2_loss_vs_goodput.pdf        – scatter: loss signal vs goodput

Usage:
    python3 plot.py [--traces-dir DIR] [--output-dir DIR] [--representative HOST]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.ticker import AutoMinorLocator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def discover_trace_files(traces_dir: Path) -> List[Path]:
    """Return all per-destination CSVs, excluding the server list."""
    paths = sorted(traces_dir.glob("*.csv"))
    traces = [
        p for p in paths
        if p.name != "listed_iperf3_servers.csv" and "_" in p.name
    ]
    if not traces:
        print(
            f"[ERROR] No trace CSVs found in '{traces_dir}'. "
            "Run main.py first to generate trace logs.",
            file=sys.stderr,
        )
        sys.exit(1)
    return traces


def load_trace(path: Path) -> pd.DataFrame:
    """Load and sanitise a single trace CSV.

    The first sample is dropped because control.py initialises last_bytes_acked=0
    before the send loop, so the very first goodput measurement covers all bytes
    acked during connection setup and produces an artificially large spike.
    """
    df = pd.read_csv(path)
    numeric_cols = set(df.columns) - {"trace_id", "split"}
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("timestamp").reset_index(drop=True)
    if len(df) > 1:
        df = df.iloc[1:].reset_index(drop=True)
    return df


def label_from_path(path: Path) -> str:
    """Turn 'speedtest.wobcom.de_5201.csv' → 'speedtest.wobcom.de'."""
    stem = path.stem  # e.g. "speedtest.wobcom.de_5201"
    # Strip trailing _PORT
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0]
    return stem


def loss_column(df: pd.DataFrame) -> Tuple[str, pd.Series]:
    """Return (column_name, Series) for the best available loss proxy."""
    for col in ("retrans", "lost", "retransmits"):
        if col in df.columns:
            s = df[col].diff().clip(lower=0)
            return col, s
    # Fallback: zeros
    return "loss", pd.Series(np.zeros(len(df)), index=df.index)


def clean_goodput_mbps(df: pd.DataFrame) -> pd.Series:
    """
    Return goodput in Mbps with outlier spikes replaced by NaN.

    control.py computes goodput as delta(bytes_acked)/interval. The bytes_acked
    counter from TCP_INFO can jump suddenly (e.g. after connection stalls, or in
    the first sample where the baseline is 0), producing unrealistically large
    values. We use the IQR fence (Q3 + 3*IQR) to cap outliers so that the bulk
    of the trace is not compressed against the x-axis.
    """
    s = df["goodput_bps"] / 1e6
    q1 = s.quantile(0.25)
    q3 = s.quantile(0.75)
    iqr = q3 - q1
    upper = q3 + 3 * iqr
    # Never clip below a sensible minimum so we don't destroy very low-throughput traces.
    upper = max(upper, q3 * 2, 1.0)
    return s.where(s <= upper, other=np.nan).interpolate(method="linear")


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[INFO] Saved {path}")


# ---------------------------------------------------------------------------
# Q1 plots
# ---------------------------------------------------------------------------

def plot_q1_throughput_timeseries(
    traces: Dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """
    Q1(c): Goodput time series for all destinations on one plot.
    Each destination is a separate line; y-axis is Mbps.
    """
    fig, ax = plt.subplots(figsize=(12, 6))

    cmap = plt.colormaps["tab20"].resampled(max(len(traces), 1))
    for i, (label, df) in enumerate(traces.items()):
        goodput_mbps = clean_goodput_mbps(df)
        ax.plot(
            df["timestamp"],
            goodput_mbps,
            label=label,
            color=cmap(i),
            linewidth=1.2,
            alpha=0.85,
        )

    ax.set_xlabel("Elapsed time (s)")
    ax.set_ylabel("Goodput (Mbps)")
    ax.set_title("Q1 – Goodput time series across all destinations")
    ax.legend(fontsize=7, loc="upper right", ncol=2)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.xaxis.set_minor_locator(AutoMinorLocator())

    _save(fig, output_dir / "q1_throughput_timeseries.pdf")


def plot_q1_summary_table(
    traces: Dict[str, pd.DataFrame],
    output_dir: Path,
) -> None:
    """
    Q1(c): Summary table – min / median / avg / p95 goodput per destination.
    Rendered as a matplotlib table and saved as a PDF.
    """
    rows = []
    for label, df in traces.items():
        mbps = clean_goodput_mbps(df).dropna()
        rows.append(
            {
                "Destination": label,
                "Min (Mbps)": f"{mbps.min():.2f}",
                "Median (Mbps)": f"{mbps.median():.2f}",
                "Avg (Mbps)": f"{mbps.mean():.2f}",
                "p95 (Mbps)": f"{np.percentile(mbps, 95):.2f}",
            }
        )

    if not rows:
        return

    table_df = pd.DataFrame(rows)
    col_labels = list(table_df.columns)
    cell_text = table_df.values.tolist()

    # Choose a figure height that scales with the number of rows.
    n_rows = len(rows)
    fig_h = max(2.0, 0.45 * (n_rows + 2))
    fig, ax = plt.subplots(figsize=(11, fig_h))
    ax.axis("off")

    tbl = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        cellLoc="center",
        loc="center",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.auto_set_column_width(range(len(col_labels)))

    # Style header row.
    for j in range(len(col_labels)):
        tbl[0, j].set_facecolor("#2c5f8a")
        tbl[0, j].set_text_props(color="white", fontweight="bold")

    # Alternate row shading.
    for i in range(1, n_rows + 1):
        bg = "#eaf1f8" if i % 2 == 0 else "white"
        for j in range(len(col_labels)):
            tbl[i, j].set_facecolor(bg)

    ax.set_title(
        "Q1 – Per-destination goodput summary",
        pad=12,
        fontsize=11,
        fontweight="bold",
    )
    _save(fig, output_dir / "q1_summary_table.pdf")


# ---------------------------------------------------------------------------
# Q2 – time series plots
# ---------------------------------------------------------------------------

def _timeseries_fig(
    x: pd.Series,
    y: pd.Series,
    xlabel: str,
    ylabel: str,
    title: str,
    color: str,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(x, y, color=color, linewidth=1.3)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    return fig


def plot_q2_timeseries(
    df: pd.DataFrame,
    label: str,
    output_dir: Path,
) -> None:
    """Q2(b)(i): Four separate time-series PDFs for one representative destination."""
    t = df["timestamp"]

    # 1. snd_cwnd
    fig = _timeseries_fig(
        t, df["snd_cwnd"],
        "Elapsed time (s)", "snd_cwnd (segments)",
        f"Q2 – snd_cwnd over time  [{label}]",
        "tab:blue",
    )
    _save(fig, output_dir / "q2_cwnd_timeseries.pdf")

    # 2. RTT
    fig = _timeseries_fig(
        t, df["rtt_ms"],
        "Elapsed time (s)", "RTT (ms)",
        f"Q2 – RTT over time  [{label}]",
        "tab:orange",
    )
    _save(fig, output_dir / "q2_rtt_timeseries.pdf")

    # 3. Loss proxy
    loss_col, loss_series = loss_column(df)
    fig = _timeseries_fig(
        t, loss_series,
        "Elapsed time (s)", f"Loss proxy (Δ{loss_col})",
        f"Q2 – Loss proxy over time  [{label}]",
        "tab:red",
    )
    fig.axes[0].set_ylim(bottom=0)
    _save(fig, output_dir / "q2_loss_timeseries.pdf")

    # 4. Throughput / goodput
    fig = _timeseries_fig(
        t, clean_goodput_mbps(df),
        "Elapsed time (s)", "Goodput (Mbps)",
        f"Q2 – Goodput over time  [{label}]",
        "tab:green",
    )
    _save(fig, output_dir / "q2_throughput_timeseries.pdf")


# ---------------------------------------------------------------------------
# Q2 – scatter plots
# ---------------------------------------------------------------------------

def _scatter_fig(
    x: pd.Series,
    y: pd.Series,
    xlabel: str,
    ylabel: str,
    title: str,
    color: str,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(x, y, alpha=0.4, s=14, color=color, edgecolors="none")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, alpha=0.3, linestyle="--")
    fig.tight_layout()
    return fig


def plot_q2_scatters(
    df: pd.DataFrame,
    label: str,
    output_dir: Path,
) -> None:
    """Q2(b)(ii): Three scatter-plot PDFs for one representative destination."""
    goodput = clean_goodput_mbps(df)
    loss_col_name, loss_series = loss_column(df)

    # 1. snd_cwnd vs goodput
    fig = _scatter_fig(
        df["snd_cwnd"], goodput,
        "snd_cwnd (segments)", "Goodput (Mbps)",
        f"Q2 – snd_cwnd vs Goodput  [{label}]",
        "tab:blue",
    )
    _save(fig, output_dir / "q2_cwnd_vs_goodput.pdf")

    # 2. RTT vs goodput
    fig = _scatter_fig(
        df["rtt_ms"], goodput,
        "RTT (ms)", "Goodput (Mbps)",
        f"Q2 – RTT vs Goodput  [{label}]",
        "tab:orange",
    )
    _save(fig, output_dir / "q2_rtt_vs_goodput.pdf")

    # 3. Loss signal vs goodput
    fig = _scatter_fig(
        loss_series, goodput,
        f"Loss signal (Δ{loss_col_name})", "Goodput (Mbps)",
        f"Q2 – Loss signal vs Goodput  [{label}]",
        "tab:red",
    )
    fig.axes[0].set_xlim(left=0)
    _save(fig, output_dir / "q2_loss_vs_goodput.pdf")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Q1/Q2 PDF plots from iperf trace CSVs."
    )
    parser.add_argument(
        "--traces-dir",
        default=".",
        help="Directory containing per-destination trace CSVs (default: .).",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory to write PDF plots (default: .).",
    )
    parser.add_argument(
        "--representative",
        default=None,
        metavar="HOST",
        help=(
            "Hostname (or CSV filename stem) of the representative destination "
            "to use for Q2 plots. If omitted, the first trace is used."
        ),
    )
    args = parser.parse_args()

    traces_dir = Path(args.traces_dir)
    base_dir = Path(args.output_dir)

    q1_dir = base_dir / "q1_outputs"
    q2_dir = base_dir / "q2_outputs"
    q1_dir.mkdir(parents=True, exist_ok=True)
    q2_dir.mkdir(parents=True, exist_ok=True)

    trace_files = discover_trace_files(traces_dir)
    print(f"[INFO] Found {len(trace_files)} trace file(s).")

    # Load all traces keyed by their human-readable label.
    traces: Dict[str, pd.DataFrame] = {}
    for path in trace_files:
        lbl = label_from_path(path)
        try:
            traces[lbl] = load_trace(path)
        except Exception as exc:
            print(f"[WARN] Could not load {path.name}: {exc}", file=sys.stderr)

    if not traces:
        print("[ERROR] All traces failed to load; aborting.", file=sys.stderr)
        sys.exit(1)

    # --- Q1 ----------------------------------------------------------------
    print("\n[Q1] Generating throughput time series and summary table …")
    plot_q1_throughput_timeseries(traces, q1_dir)
    plot_q1_summary_table(traces, q1_dir)

    # --- Q2 ----------------------------------------------------------------
    # Pick the representative destination.
    rep_label: Optional[str] = None
    if args.representative:
        # Allow matching by hostname or full stem.
        for lbl in traces:
            if args.representative in lbl:
                rep_label = lbl
                break
        if rep_label is None:
            print(
                f"[WARN] --representative '{args.representative}' not found; "
                "falling back to first trace.",
                file=sys.stderr,
            )

    if rep_label is None:
        # Pick the trace with the most samples — avoids short/dropped traces.
        rep_label = max(traces, key=lambda lbl: len(traces[lbl]))

    print(f"\n[Q2] Using '{rep_label}' as representative destination.")
    rep_df = traces[rep_label]
    plot_q2_timeseries(rep_df, rep_label, q2_dir)
    plot_q2_scatters(rep_df, rep_label, q2_dir)

    print(f"\n[Done] Q1 plots → {q1_dir.resolve()}")
    print(f"[Done] Q2 plots → {q2_dir.resolve()}")


if __name__ == "__main__":
    main()
