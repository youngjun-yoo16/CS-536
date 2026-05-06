#!/usr/bin/env bash
#
# runQuick.sh: Quick smoke test: 2 ranks, small messages, verify correctness.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

IMAGE_NAME="hw5-collectives"

echo ">>> Building Docker image..."
docker build -t "${IMAGE_NAME}" "${PROJECT_DIR}" 2>&1 | tail -3

echo ""
echo ">>> Running quick test (2 ranks, small messages)..."
docker run --rm \
    -e MESSAGE_SIZES="1024,4096,16384" \
    "${IMAGE_NAME}" \
    torchrun \
        --nproc_per_node=2 \
        --master_addr="127.0.0.1" \
        --master_port="25565" \
        /app/src/benchmark_worker.py all

echo ""
echo ">>> Quick test passed!"
