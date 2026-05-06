# plot_results.py
# Local results  (results_np*.json)      and ring results (results_ring_np*.json)
# are combined on every plot for direct comparison:
#   Local runs       → solid lines
#   Ring topology    → dashed lines  (same color per algorithm)
#
# 

import json
import os
import sys
import glob
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.lines as mlines


ALGO_STYLES = {
    "ring":               {"color": "tab:blue",   "marker": "o"},
    "recursive_doubling": {"color": "tab:orange", "marker": "s"},
    "swing":              {"color": "tab:green",  "marker": "^"},
    "binary_tree":        {"color": "tab:red",    "marker": "D"},
    "binomial_tree":      {"color": "tab:purple", "marker": "v"},
}



def styleKwargs(algoName, isRing):
    """Return plot() kwargs for one curve. isRing controls solid vs dashed."""
    s = ALGO_STYLES.get(algoName, {"color": "gray", "marker": "x"})
    return {
        "color":      s["color"],
        "marker":     s["marker"],
        "linestyle":  "--" if isRing else "-",
        "linewidth":  2,
        "markersize": 7,
    }


# Build a custom legend with one entry per algorithm (color + marker)
def buildLegend(ax, algosPresent, hasLocal, hasRing):
    algo_handles = []
    for name in sorted(algosPresent):
        s = ALGO_STYLES.get(name, {"color": "gray", "marker": "x"})
        algo_handles.append(mlines.Line2D(
            [], [], color=s["color"], marker=s["marker"],
            linestyle="-", linewidth=2, markersize=7,
            label=ALGO_LABELS.get(name, name)
        ))
    type_handles = []
    if hasLocal:
        type_handles.append(mlines.Line2D(
            [], [], color="black", linestyle="-", linewidth=2, label="Local run"))
    if hasRing:
        type_handles.append(mlines.Line2D(
            [], [], color="black", linestyle="--", linewidth=2, label="Ring topology"))
    blank = mlines.Line2D([], [], alpha=0, label="")
    all_h = algo_handles + [blank] + type_handles
    ax.legend(all_h, [h.get_label() for h in all_h], fontsize=10, loc="upper left")

ALGO_LABELS = {
    "ring":               "Ring",
    "recursive_doubling": "Recursive Doubling",
    "swing":              "Swing",
    "binary_tree":        "Binary Tree",
    "binomial_tree":      "Binomial Tree",
}

# Canonical x-axis ticks for the message-size plots (1 KB → 128 MB)
MSG_SIZE_TICKS = [
    1024,            # 1 KB
    4096,            # 4 KB
    16384,           # 16 KB
    65536,           # 64 KB
    262144,          # 256 KB
    1048576,         # 1 MB
    4194304,         # 4 MB
    16777216,        # 16 MB
    67108864,        # 64 MB
    134217728,       # 128 MB
]
MSG_SIZE_MIN = MSG_SIZE_TICKS[0]   # 1 KB
MSG_SIZE_MAX = MSG_SIZE_TICKS[-1]  # 128 MB


# Make it human-readable
def sizeLabel(n):
    if n >= 1024 * 1024:
        v = n // (1024 * 1024)
        return f"{v} MB"
    if n >= 1024:
        v = n // 1024
        return f"{v} KB"
    return f"{n} B"



# Helper functions to load results files, pick message sizes, and build legends.
def loadResults(resultsDir):
    files = sorted(glob.glob(os.path.join(resultsDir, "results_*.json")))
    localBest = {}   # gp_size -> data dict
    ringBest  = {}

    for path in files:
        with open(path) as fp:
            data = json.load(fp)
        fname = os.path.basename(path)
        data["_file"] = fname
        gs = data["gp_size"]
        bucket = ringBest if "ring" in fname else localBest
        if gs not in bucket or fname > bucket[gs]["_file"]:
            bucket[gs] = data

    localData = sorted(localBest.values(), key=lambda d: d["gp_size"])
    ringData  = sorted(ringBest.values(),  key=lambda d: d["gp_size"])

    if localData:
        print(f"  Local : gp_sizes={[d['gp_size'] for d in localData]}")
    if ringData:
        print(f"  Ring  : gp_sizes={[d['gp_size'] for d in ringData]}")
    return localData, ringData


def _pickFixedMsgSize(allData, collective):
    """
    Choose the message size for the fixed-msg-size vs-ranks plot.
    allData is a flat list that may mix local and ring entries.
    Prefer 1 MB; fall back to the size present in the most datasets
    (largest wins on tie).
    """
    preferred = 1048576  # 1 MB
    sizeCount: Counter = Counter()
    for d in allData:
        if collective not in d:
            continue
        for timings in d[collective].values():
            for k in timings:
                sizeCount[int(k)] += 1
    if not sizeCount:
        return preferred
    if preferred in sizeCount:
        return preferred
    maxCount = max(sizeCount.values())
    candidates = [s for s, c in sizeCount.items() if c == maxCount]
    return max(candidates)



# Plotting functions for the two types of plots: time vs message size, and time vs number of ranks.
def plotVSMessageSize(localData, ringData, collective, outputDir):
    localCands = [d for d in localData if collective in d]
    ringCands  = [d for d in ringData  if collective in d]
    if not localCands and not ringCands:
        print(f"  [skip] no data for '{collective}'")
        return

    # x = message size (log2 axis with canonical ticks)
    # y = completion time (ms, log axis)
    fig, ax = plt.subplots(figsize=(10, 6))
    hasLines     = False
    algosPresent = set()
    allPresentSizes = set()

    # Plot all (local and ring) on the same axes for direct comparison.

    for cands, isRing in [(localCands, False), (ringCands, True)]:
        if not cands:
            continue
        gpSize = max(d["gp_size"] for d in cands)
        data   = next(d for d in cands if d["gp_size"] == gpSize)
        algos  = data[collective]
        tag    = f"ring, {gpSize} ranks" if isRing else f"local, {gpSize} ranks"

        for algoName in sorted(algos):
            timings = algos[algoName]
            sizes = sorted(
                s for s in (int(k) for k in timings)
                if MSG_SIZE_MIN <= s <= MSG_SIZE_MAX
            )
            if not sizes:
                continue
            timesMs = [timings[str(s)] * 1000 for s in sizes]
            ax.plot(sizes, timesMs,
                    label=f"{ALGO_LABELS.get(algoName, algoName)} ({tag})",
                    **styleKwargs(algoName, isRing))
            algosPresent.add(algoName)
            allPresentSizes.update(sizes)
            hasLines = True

    if not hasLines:
        print(f"  [skip] {collective} vs msg size: no data in 1 KB – 128 MB range")
        plt.close()
        return

    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlim(MSG_SIZE_MIN / 1.5, MSG_SIZE_MAX * 1.5)

    tickSizes = sorted(allPresentSizes & set(MSG_SIZE_TICKS))
    if tickSizes:
        ax.set_xticks(tickSizes)
        ax.set_xticklabels([sizeLabel(s) for s in tickSizes], rotation=40, ha="right")

    ax.yaxis.set_major_formatter(ticker.FuncFormatter(
        lambda v, _: f"{v:.3g}" if v < 1 else f"{v:.4g}"
    ))

    collective_title = "AllGather" if collective == "allgather" else "Broadcast"
    ax.set_xlabel("Message Size", fontsize=13)
    ax.set_ylabel("Completion Time (ms)", fontsize=13)
    ax.set_title(f"{collective_title}: Completion Time vs Message Size", fontsize=14)
    ax.grid(True, which="both", alpha=0.3)
    buildLegend(ax, algosPresent,
                hasLocal=bool(localCands), hasRing=bool(ringCands))

    plt.tight_layout()
    outpath = os.path.join(outputDir, f"{collective}_vs_msgsize.png")
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"  Saved: {outpath}")



def plotVSNumRanks(localData, ringData, collective, outputDir, fixedMsgSize=None):
    """
    x = number of ranks  (LINEAR axis with explicit integer ticks)
    y = completion time (ms)

    All rank counts from both local and ring datasets appear on the same axes.
    Local runs → solid lines;  ring topology → dashed lines.
    Same color per algorithm in both groups.

    LINEAR x-axis (not log2): rank=5, rank=128, or any odd/arbitrary value is
    placed and labelled correctly — log2 would mis-place non-power-of-2 ticks.
    """
    allDatasets = localData + ringData
    if not any(collective in d for d in allDatasets):
        print(f"  [skip] no data for '{collective}'")
        return

    if fixedMsgSize is None:
        fixedMsgSize = _pickFixedMsgSize(allDatasets, collective)

    # algo -> {"local": {gp_size: ms}, "ring": {gp_size: ms}}
    algoData: dict = {}
    for d in localData:
        if collective not in d:
            continue
        gs = d["gp_size"]
        for algoName, timings in d[collective].items():
            if str(fixedMsgSize) not in timings:
                continue
            algoData.setdefault(algoName, {"local": {}, "ring": {}})
            algoData[algoName]["local"][gs] = timings[str(fixedMsgSize)] * 1000

    for d in ringData:
        if collective not in d:
            continue
        gs = d["gp_size"]
        for algoName, timings in d[collective].items():
            if str(fixedMsgSize) not in timings:
                continue
            algoData.setdefault(algoName, {"local": {}, "ring": {}})
            algoData[algoName]["ring"][gs] = timings[str(fixedMsgSize)] * 1000

    if not algoData:
        print(f"  [skip] {collective} vs ranks: {sizeLabel(fixedMsgSize)} not in any dataset")
        return
    
    fig, ax = plt.subplots(figsize=(10, 6))
    algosPresent = set()
    hasLocal = hasRing = False

    for algoName in sorted(algoData):
        for bucket, isRing in [("local", False), ("ring", True)]:
            pts = algoData[algoName][bucket]
            if not pts:
                continue
            gpSizes = sorted(pts)
            times   = [pts[gs] for gs in gpSizes]
            ax.plot(gpSizes, times, **styleKwargs(algoName, isRing))
            algosPresent.add(algoName)
            if isRing:
                hasRing = True
            else:
                hasLocal = True

    if not algosPresent:
        plt.close()
        return

    # LINEAR x-axis: explicit integer tick at every rank count in the data.
    # Handles any value (2, 4, 5, 8, 128, …) without distortion.
    allGpSizes = sorted({
        gs
        for buckets in algoData.values()
        for pts in buckets.values()
        for gs in pts
    })
    ax.set_xticks(allGpSizes)
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: str(int(v))))
    span = max(allGpSizes) - min(allGpSizes)
    pad  = max(span * 0.05, 0.5)
    ax.set_xlim(min(allGpSizes) - pad, max(allGpSizes) + pad)

    ax.yaxis.set_major_formatter(ticker.FuncFormatter(
        lambda v, _: f"{v:.3g}" if v < 1 else f"{v:.4g}"
    ))

    collective_title = "AllGather" if collective == "allgather" else "Broadcast"
    ax.set_xlabel("Number of Ranks", fontsize=13)
    ax.set_ylabel("Completion Time (ms)", fontsize=13)
    ax.set_title(
        f"{collective_title}: Completion Time vs Number of Ranks\n"
        f"(fixed message size = {sizeLabel(fixedMsgSize)})",
        fontsize=14,
    )
    ax.grid(True, alpha=0.3)
    buildLegend(ax, algosPresent, hasLocal=hasLocal, hasRing=hasRing)

    plt.tight_layout()
    outpath = os.path.join(outputDir, f"{collective}_vs_ranks.png")
    plt.savefig(outpath, dpi=150)
    plt.close()
    print(f"  Saved: {outpath}")


def main():
    resultsDir = sys.argv[1] if len(sys.argv) > 1 else "/app/results"
    outputDir  = sys.argv[2] if len(sys.argv) > 2 else "/app/plots"
    os.makedirs(outputDir, exist_ok=True)

    print(f"Loading results from: {resultsDir}")
    localData, ringData = loadResults(resultsDir)
    if not localData and not ringData:
        print(f"No result files found in {resultsDir}")
        sys.exit(1)
    print()

    print("Generating time vs message-size plots...")
    plotVSMessageSize(localData, ringData, "allgather", outputDir)
    plotVSMessageSize(localData, ringData, "broadcast",  outputDir)
    print()

    print("Generating time vs ranks plots...")
    plotVSNumRanks(localData, ringData, "allgather", outputDir)
    plotVSNumRanks(localData, ringData, "broadcast",  outputDir)

    print(f"\nAll plots saved to: {outputDir}/")


if __name__ == "__main__":
    main()
