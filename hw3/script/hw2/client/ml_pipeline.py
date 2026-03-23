#!/usr/bin/env python3
"""
Q3 ML pipeline for TCP congestion control.

This script builds a dataset from the per-destination CSV logs produced by
`ControlConnection.send_data` in `control.py`, trains a global model to
predict the next congestion window update Δsnd_cwnd, and generates cwnd
time-series plots comparing ground truth and model rollouts for several
destinations.

The implementation follows the plan in `implementation.md` and the
`HW2-Q3-ML-Pipeline` plan file.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from sklearn.ensemble import GradientBoostingRegressor


# ---------------------------
# Data loading and utilities
# ---------------------------


REQUIRED_COLUMNS = {
    "timestamp",
    "interval_s",
    "goodput_bps",
    "snd_cwnd",
    "rtt_ms",
    "bytes_acked",
    "bytes_sent",
}


def discover_trace_files(traces_dir: Path, min_traces: int = 5) -> List[Path]:
    """
    Find per-destination trace CSVs in the given directory.

    The client names logs as `<host>_<port>.csv`. We filter out the server list
    and any obvious non-trace CSV files.
    """
    csv_paths = sorted(traces_dir.glob("*.csv"))
    traces: List[Path] = []
    for path in csv_paths:
        name = path.name
        if name == "listed_iperf3_servers.csv":
            continue
        # Heuristic: treat files with an underscore before the extension as
        # client logs (e.g., "speedtest.example.com_5201.csv").
        if "_" not in name:
            continue
        traces.append(path)

    if not traces:
        print(
            f"[WARN] No per-destination trace CSVs found in {traces_dir}. "
            "Run the client to generate logs before executing the ML pipeline."
        )
    elif len(traces) < min_traces:
        print(
            f"[WARN] Only found {len(traces)} trace file(s) in {traces_dir}, "
            f"fewer than requested minimum of {min_traces}."
        )

    print(f"[INFO] Discovered {len(traces)} trace file(s).")
    for t in traces:
        print(f"  - {t.name}")
    return traces


def _ensure_numeric(df: pd.DataFrame, cols: Iterable[str]) -> None:
    """Convert the given columns to numeric dtype in-place (coercing errors)."""
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")


def load_trace(path: Path) -> pd.DataFrame:
    """
    Load a single per-destination trace CSV into a DataFrame.

    The function:
    - reads the CSV,
    - sorts by timestamp,
    - coerces obvious numeric columns to numeric dtype.
    """
    df = pd.read_csv(path)
    if "timestamp" not in df.columns:
        raise ValueError(f"Trace {path} is missing required column 'timestamp'")

    df = df.sort_values("timestamp").reset_index(drop=True)

    numeric_candidates = set(df.columns) - {"trace_id", "split"}
    _ensure_numeric(df, numeric_candidates)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        print(
            f"[WARN] Trace {path.name} is missing columns: "
            f"{', '.join(sorted(missing))}. The pipeline may still work "
            "if those features are not used."
        )

    return df


# ---------------------------
# Per-trace feature engineering
# ---------------------------


@dataclass
class TraceDataset:
    df: pd.DataFrame
    trace_id: str


def build_trace_dataset(path: Path, trace_id: str) -> TraceDataset:
    """
    Build a per-trace dataset with engineered features and label.

    Features include:
    - goodput_Mbps
    - rtt_ms
    - snd_cwnd
    - loss_rate (derived from retransmissions)
    - rttvar_ms
    - pacing_rate_bps
    - bytes_acked
    - bytes_sent
    - one-step lags of goodput, rtt, cwnd, and loss_rate

    Label:
    - y = delta_cwnd = snd_cwnd(t) - snd_cwnd(t-1)
    """
    df = load_trace(path)

    # Compute base deltas.
    df["delta_cwnd"] = df["snd_cwnd"].diff()

    if "retrans" in df.columns:
        df["delta_retrans"] = df["retrans"].diff()
    elif "lost" in df.columns:
        df["delta_retrans"] = df["lost"].diff()
    else:
        df["delta_retrans"] = 0.0

    if "bytes_acked" in df.columns:
        df["delta_bytes_acked"] = df["bytes_acked"].diff()

    # Drop first row with NaNs from diff.
    df = df.iloc[1:].copy()

    # Base features.
    df["goodput_Mbps"] = df["goodput_bps"] / 1e6
    # Avoid division by zero for interval length.
    interval = df["interval_s"].replace(0, np.nan)
    df["loss_rate"] = (df["delta_retrans"].clip(lower=0) / interval).fillna(0.0)

    # Label.
    df["y"] = df["delta_cwnd"]

    # One-step lag features.
    df["goodput_prev"] = df["goodput_Mbps"].shift(1)
    df["rtt_prev"] = df["rtt_ms"].shift(1)
    df["cwnd_prev"] = df["snd_cwnd"].shift(1)
    df["loss_prev"] = df["loss_rate"].shift(1)

    # Drop rows with NaNs introduced by lagging.
    df = df.dropna().reset_index(drop=True)

    df["trace_id"] = trace_id

    return TraceDataset(df=df, trace_id=trace_id)


# ---------------------------
# Global dataset & splitting
# ---------------------------


def build_global_dataset(paths: Sequence[Path]) -> pd.DataFrame:
    """Build a global dataset across all traces."""
    trace_datasets: List[pd.DataFrame] = []
    for idx, path in enumerate(paths):
        trace_id = f"trace_{idx}"
        td = build_trace_dataset(path, trace_id)
        trace_datasets.append(td.df)

    if not trace_datasets:
        raise RuntimeError("No trace datasets could be built; aborting.")

    all_df = pd.concat(trace_datasets, ignore_index=True)
    return all_df


def add_time_based_split(df: pd.DataFrame, train_fraction: float = 0.7) -> pd.DataFrame:
    """
    Add a `split` column with values 'train' or 'test' per trace_id
    using a temporal split on timestamp.
    """
    if "trace_id" not in df.columns:
        raise ValueError("Global dataset is missing 'trace_id' column")

    df = df.sort_values(["trace_id", "timestamp"]).reset_index(drop=True)
    splits = []

    for trace_id, group in df.groupby("trace_id", sort=False):
        n = len(group)
        if n < 2:
            # Not enough samples to split; put everything in train.
            idx_split = n
        else:
            idx_split = max(1, int(n * train_fraction))

        mask = np.array(["train"] * n, dtype=object)
        if idx_split < n:
            mask[idx_split:] = "test"
        splits.extend(mask.tolist())

    df = df.copy()
    df["split"] = splits
    return df


def get_feature_and_label_matrices(
    df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series, List[str]]:
    """
    Create X_train, y_train, X_test, y_test matrices and return the list
    of feature column names used.
    """
    # Explicit feature list for clarity and reproducibility.
    candidate_features = [
        "goodput_Mbps",
        "rtt_ms",
        "snd_cwnd",
        "loss_rate",
        "rttvar_ms",
        "pacing_rate_bps",
        "bytes_acked",
        "bytes_sent",
        "goodput_prev",
        "rtt_prev",
        "cwnd_prev",
        "loss_prev",
    ]

    feature_cols = [c for c in candidate_features if c in df.columns]
    if not feature_cols:
        raise RuntimeError("No usable feature columns found in dataset.")

    # Drop rows with missing labels or features.
    work_df = df.dropna(subset=feature_cols + ["y"]).copy()

    train_df = work_df[work_df["split"] == "train"]
    test_df = work_df[work_df["split"] == "test"]

    if train_df.empty or test_df.empty:
        raise RuntimeError("Train/test split produced empty train or test set.")

    X_train = train_df[feature_cols]
    y_train = train_df["y"]
    X_test = test_df[feature_cols]
    y_test = test_df["y"]

    return X_train, y_train, X_test, y_test, feature_cols


# ---------------------------
# η computation and modeling
# ---------------------------


def compute_eta(df: pd.DataFrame, alpha: float, beta: float) -> pd.Series:
    """
    Compute η(t-1) = goodput(t) - α * RTT(t) - β * loss(t) for each row.
    """
    if "goodput_Mbps" not in df.columns or "rtt_ms" not in df.columns or "loss_rate" not in df.columns:
        raise ValueError("Dataset missing columns required to compute η.")

    eta = df["goodput_Mbps"] - alpha * df["rtt_ms"] - beta * df["loss_rate"]
    return eta


@dataclass
class TrainedModel:
    model: GradientBoostingRegressor
    feature_cols: List[str]
    alpha: float
    beta: float


def train_model_with_eta_selection(
    df: pd.DataFrame,
    alpha: float = 0.01,
    beta: float = 1.0,
) -> TrainedModel:
    """
    Train a GradientBoostingRegressor on Δsnd_cwnd and select hyperparameters
    using an η-based objective on a validation subset.

    We keep training loss as MSE on y, but for model selection we compute
    a simple score that encourages alignment between the predicted update
    Δcwnd and η:

        score = corr(y_pred, η)

    Higher correlation means that positive updates are associated with higher
    η and negative updates with lower η.
    """
    X_train, y_train, X_test, y_test, feature_cols = get_feature_and_label_matrices(df)

    # Create a time-ordered view of the training data for internal val split.
    train_df = df[df["split"] == "train"].dropna(subset=feature_cols + ["y"]).copy()
    train_df = train_df.sort_values("timestamp")
    n_train = len(train_df)
    val_start = int(n_train * 0.8)
    inner_train_df = train_df.iloc[:val_start]
    val_df = train_df.iloc[val_start:]

    if val_df.empty:
        # Fallback: use full train as inner train and test as validation.
        inner_train_df = train_df
        val_df = df[df["split"] == "test"].dropna(subset=feature_cols + ["y"]).copy()

    eta_val = compute_eta(val_df, alpha=alpha, beta=beta)

    param_grid = [
        {"n_estimators": 50, "max_depth": 2, "learning_rate": 0.1},
        {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.1},
        {"n_estimators": 150, "max_depth": 3, "learning_rate": 0.05},
    ]

    best_score = -np.inf
    best_params = None
    best_model = None

    for params in param_grid:
        gb = GradientBoostingRegressor(
            n_estimators=params["n_estimators"],
            max_depth=params["max_depth"],
            learning_rate=params["learning_rate"],
            random_state=42,
        )

        gb.fit(inner_train_df[feature_cols], inner_train_df["y"])

        # Evaluate on validation subset using η-based score.
        y_pred_val = gb.predict(val_df[feature_cols])

        # Correlation between predicted updates and η.
        if eta_val.std() == 0 or np.std(y_pred_val) == 0:
            score = -np.inf
        else:
            score = float(np.corrcoef(y_pred_val, eta_val)[0, 1])

        print(
            f"[INFO] Params {params} -> corr(y_pred, η) on val = "
            f"{score:.4f}"
        )

        if score > best_score:
            best_score = score
            best_params = params
            best_model = gb

    if best_model is None or best_params is None:
        raise RuntimeError("Hyperparameter search failed to produce a valid model.")

    print(f"[INFO] Selected params {best_params} with validation score {best_score:.4f}")

    # Refit on the full training set with best params.
    final_model = GradientBoostingRegressor(
        n_estimators=best_params["n_estimators"],
        max_depth=best_params["max_depth"],
        learning_rate=best_params["learning_rate"],
        random_state=42,
    )
    final_model.fit(X_train, y_train)

    # Basic sanity check on held-out test set.
    y_pred_test = final_model.predict(X_test)
    mse = np.mean((y_pred_test - y_test) ** 2)
    print(f"[INFO] Test MSE on Δcwnd: {mse:.4f}")

    return TrainedModel(
        model=final_model,
        feature_cols=feature_cols,
        alpha=alpha,
        beta=beta,
    )


# ---------------------------
# Rollout and plotting
# ---------------------------


def rollout_cwnd_for_trace(
    df_trace: pd.DataFrame,
    trained: TrainedModel,
) -> pd.DataFrame:
    """
    Roll out predicted cwnd for the test portion of a single trace.

    The function assumes df_trace contains both train and test rows and that
    a `split` column already exists. Only the test horizon is rolled out.
    """
    feature_cols = trained.feature_cols
    model = trained.model

    trace_df = df_trace.sort_values("timestamp").reset_index(drop=True)
    test_mask = trace_df["split"] == "test"
    if not test_mask.any():
        raise ValueError("Trace has no test rows for rollout.")

    # Index of first test row.
    first_test_idx = np.where(test_mask.values)[0][0]

    cwnd_pred = []
    timestamps = []
    cwnd_true = []

    # Initialize predicted cwnd with the true cwnd at the first test step.
    prev_cwnd = float(trace_df.loc[first_test_idx, "snd_cwnd"])

    for idx in range(first_test_idx, len(trace_df)):
        row = trace_df.loc[idx]

        x = row[feature_cols].copy()
        if "cwnd_prev" in feature_cols:
            x["cwnd_prev"] = prev_cwnd

        y_pred = float(model.predict(x.to_frame().T)[0])

        prev_cwnd = max(1.0, prev_cwnd + y_pred)

        cwnd_pred.append(prev_cwnd)
        timestamps.append(row["timestamp"])
        cwnd_true.append(row["snd_cwnd"])

    return pd.DataFrame(
        {
            "timestamp": np.array(timestamps),
            "cwnd_true": np.array(cwnd_true),
            "cwnd_pred": np.array(cwnd_pred),
        }
    )


def plot_cwnd_timeseries(
    rollout_df: pd.DataFrame,
    full_trace_df: pd.DataFrame,
    output_path: Path,
    title: str,
) -> None:
    """Plot ground-truth and predicted cwnd over time and save as PDF."""
    fig, ax = plt.subplots(figsize=(10, 5))

    # Full ground truth.
    ax.plot(
        full_trace_df["timestamp"],
        full_trace_df["snd_cwnd"],
        label="Ground truth cwnd",
        color="tab:blue",
        linewidth=1.5,
    )

    # Predicted on test horizon.
    ax.plot(
        rollout_df["timestamp"],
        rollout_df["cwnd_pred"],
        label="Predicted cwnd (test)",
        color="tab:orange",
        linewidth=1.5,
    )

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("snd_cwnd (segments)")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3, linestyle="--")

    fig.tight_layout()
    fig.savefig(output_path, dpi=300)
    plt.close(fig)
    print(f"[INFO] Saved cwnd timeseries plot to {output_path}")


# ---------------------------
# Model interpretation helpers
# ---------------------------


def print_feature_importances(trained: TrainedModel) -> None:
    """Print feature importances for the trained model."""
    model = trained.model
    if not hasattr(model, "feature_importances_"):
        print("[WARN] Model does not expose feature_importances_.")
        return

    importances = model.feature_importances_
    pairs = sorted(
        zip(trained.feature_cols, importances),
        key=lambda x: x[1],
        reverse=True,
    )
    print("[INFO] Feature importances (descending):")
    for name, val in pairs:
        print(f"  {name:20s} {val:.4f}")


# ---------------------------
# Entry point
# ---------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "HW2 Q3 ML pipeline: build dataset from iperf traces, "
            "train Δcwnd model, and plot cwnd rollouts."
        )
    )
    parser.add_argument(
        "--traces-dir",
        type=str,
        default=".",
        help="Directory containing per-destination trace CSVs (default: current directory).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".",
        help="Directory to store plots and any additional outputs.",
    )
    parser.add_argument(
        "--min-traces",
        type=int,
        default=5,
        help="Minimum number of traces expected (default: 5).",
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

    traces_dir = Path(args.traces_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trace_files = discover_trace_files(traces_dir, min_traces=args.min_traces)
    if len(trace_files) == 0:
        print("[ERROR] No trace files available; aborting ML pipeline.")
        return

    # Build dataset and split.
    global_df = build_global_dataset(trace_files)
    global_df = add_time_based_split(global_df, train_fraction=0.7)

    # Train model using η-based selection.
    trained = train_model_with_eta_selection(
        global_df, alpha=args.alpha, beta=args.beta
    )
    print_feature_importances(trained)

    # Generate cwnd timeseries plots for up to 5 traces.
    unique_traces = list(global_df["trace_id"].unique())
    plot_traces = unique_traces[:5]
    print(f"[INFO] Generating cwnd timeseries plots for traces: {plot_traces}")

    for trace_id in plot_traces:
        trace_df = global_df[global_df["trace_id"] == trace_id].copy()
        try:
            rollout_df = rollout_cwnd_for_trace(trace_df, trained)
        except ValueError as exc:
            print(f"[WARN] Skipping {trace_id}: {exc}")
            continue
        plot_path = output_dir / f"q3_cwnd_{trace_id}.pdf"
        title = f"Trace {trace_id} – snd_cwnd ground truth vs prediction"
        plot_cwnd_timeseries(rollout_df, trace_df, plot_path, title)


if __name__ == "__main__":
    main()

