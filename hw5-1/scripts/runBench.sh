#!/usr/bin/env bash
#
# runBench.sh: Run AllGather and Broadcast benchmarks inside Docker container.
#
# Usage:
#   ./scripts/runBench.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults
RANKS_LIST="${RANKS:-2 4 8}"
MODE="${MODE:-all}"
MAX_MSG="${MAX_MSG:-16777216}"

# Build message sizes up to MAX_MSG
ALL_SIZES=(1024 4096 16384 65536 262144 1048576 4194304 16777216 67108864)
FILTERED=""
for s in "${ALL_SIZES[@]}"; do
    if [ "$s" -le "$MAX_MSG" ]; then
        if [ -n "$FILTERED" ]; then FILTERED="${FILTERED},${s}"; else FILTERED="${s}"; fi
    fi
done
MSG_SIZES="${MSG_SIZES:-$FILTERED}"
IMAGE_NAME="hw5-collectives"
CONTAINER_NAME="hw5-bench"

echo "============================================"
echo "  HW5 Collective Communication Benchmarks"
echo "============================================"
echo "Ranks:         ${RANKS_LIST}"
echo "Mode:          ${MODE}"
echo "Message sizes: ${MSG_SIZES}"
echo ""

# Build Docker image
echo ">>> Building Docker image '${IMAGE_NAME}'..."
docker build -t "${IMAGE_NAME}" "${PROJECT_DIR}" 2>&1 | tail -5
echo ""

# Create output directories on host
RESULTS_DIR="${PROJECT_DIR}/results"
PLOTS_DIR="${PROJECT_DIR}/plots"
mkdir -p "${RESULTS_DIR}" "${PLOTS_DIR}"

# Run benchmarks for each world size
for NPROCS in ${RANKS_LIST}; do
    echo ">>> Running with ${NPROCS} ranks..."
    OUTPUT_FILE="/app/results/results_np${NPROCS}.json"

    docker run --rm \
        --name "${CONTAINER_NAME}" \
        -v "${RESULTS_DIR}:/app/results" \
        -v "${PLOTS_DIR}:/app/plots" \
        -e MESSAGE_SIZES="${MSG_SIZES}" \
        "${IMAGE_NAME}" \
        torchrun \
            --nproc_per_node="${NPROCS}" \
            --master_addr="127.0.0.1" \
            --master_port="25565" \
            /app/src/benchmark_worker.py "${MODE}" "${OUTPUT_FILE}"

    echo ">>> Done with ${NPROCS} ranks."
    echo ""
done

# Generate plots
echo ">>> Generating plots..."
docker run --rm \
    -v "${RESULTS_DIR}:/app/results" \
    -v "${PLOTS_DIR}:/app/plots" \
    "${IMAGE_NAME}" \
    python3 /app/src/plot_results.py /app/results /app/plots

echo ""
echo "============================================"
echo "  All done!"
echo "  Results: ${RESULTS_DIR}/"
echo "  Plots:   ${PLOTS_DIR}/"
echo "============================================"
