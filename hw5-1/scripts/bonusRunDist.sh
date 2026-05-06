#!/usr/bin/env bash
#
# bonusRunDist.sh: Run benchmarks across physical machines in the ring topology.
#
# This script should be run from Machine 0 (the master).
# It SSHs into each other machine to launch a worker inside Docker, then runs
# the master locally. Using Docker guarantees that all
# dependencies (torch, etc.) are available on every machine.
#
# Prerequisites:
#   - Docker installed on every machine (setup.sh handles this)
#   - Ring topology configured (bonusSetupRing.sh)
#   - Passwordless SSH configured (bonusSetupSsh.sh)
#   - The hw5 project cloned/copied to every machine
#
# Environment variables:
#   MSG_SIZES - comma-separated message sizes
#   APP_DIR   - path to project on each machine
#

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <TOTAL_MACHINES> [MODE]"
    echo "Example: $0 5 all"
    exit 1
fi

TOTAL=$1
MODE="${2:-all}"
SUBNET="10.0.0"
MASTER_IP="${SUBNET}.1"
MASTER_PORT=25565
IMAGE_NAME="hw5-collectives"

# Build usernames array (hw5-0, hw5-1, ...)
USERNAMES=()
for idx in $(seq 0 $((TOTAL - 1))); do
    USERNAMES+=("hw5-${idx}")
done

# SSH options to avoid prompts
# -o StrictHostKeyChecking=no: Don't check host keys
# -o UserKnownHostsFile=/dev/null: Don't use user known hosts file
# -o LogLevel=ERROR: Don't show SSH logs
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

# project directory from script location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_DIR="${APP_DIR:-$DEFAULT_APP_DIR}"

MSG_SIZES="${MSG_SIZES:-1024,4096,16384,65536,262144,1048576,4194304}"

echo "============================================"
echo "  Distributed Benchmark (Ring Topology)"
echo "  Machines:  ${TOTAL}"
echo "  Master:    ${USERNAMES[0]}@${MASTER_IP}"
echo "  Mode:      ${MODE}"
echo "  Interface: auto-detect from IP"
echo "  App dir:   ${APP_DIR}"
echo "  Docker:    ${IMAGE_NAME}"
echo "============================================"

# Create results, plots, and log directories
mkdir -p "${APP_DIR}/results" "${APP_DIR}/plots" "${APP_DIR}/tcpdump"
LOG_DIR=$(mktemp -d "${APP_DIR}/results/.worker_logs_XXXX")
TCPDUMP_PCAP="${APP_DIR}/tcpdump/ring_np${TOTAL}_$(date +%Y%m%d_%H%M%S).pcap"
TCPDUMP_LOG="${APP_DIR}/tcpdump/ring_np${TOTAL}_$(date +%Y%m%d_%H%M%S).log"
echo "  Worker logs: ${LOG_DIR}"
echo "  Tcpdump:     ${TCPDUMP_PCAP}"
echo ""

# ---------------------------------------------------------------
# Step 1: Verify Docker image exists on master and all workers
# The image must be pre-built by setup.sh (before ring removes internet)
# ---------------------------------------------------------------
echo ">>> Checking Docker image '${IMAGE_NAME}' on all machines..."

# Check master
if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    echo "  ERROR: Docker image '${IMAGE_NAME}' not found on master."
    echo "  Run 'sudo ./scripts/setup.sh' first (while you still have internet)."
    rm -rf "${LOG_DIR}"
    exit 1
fi
echo "  Master: OK"

# Check workers
for i in $(seq 1 $((TOTAL - 1))); do
    WORKER_IP="${SUBNET}.$((i + 1))"
    WORKER_USER="${USERNAMES[$i]}"
    REMOTE_APP_DIR="${APP_DIR/${USERNAMES[0]}/${WORKER_USER}}"

    printf "  Machine%d (%s@%s): " "$i" "$WORKER_USER" "$WORKER_IP"

    # Check SSH connectivity
    if ! ssh ${SSH_OPTS} -o ConnectTimeout=5 "${WORKER_USER}@${WORKER_IP}" "echo OK" 2>/dev/null | grep -q "OK"; then
        echo "FAIL - SSH connection failed"
        rm -rf "${LOG_DIR}"
        exit 1
    fi

    # Check Docker image exists on worker
    if ! sshpass -p 'root2214' ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" "docker image inspect ${IMAGE_NAME}" >/dev/null 2>&1; then
        echo "FAIL - Docker image '${IMAGE_NAME}' not found"
        echo "  Run 'sudo ./scripts/setup.sh' on Machine${i} first (while it still has internet)."
        rm -rf "${LOG_DIR}"
        exit 1
    fi

    echo "OK"
done
echo ""


# ---------------------------------------------------------------
# Step 3: Start tcpdump on master to verify ring routing
# Captures all traffic on the ring interface so we can confirm
# packets travel through the expected hops.
# ---------------------------------------------------------------
MASTER_IFACE=$(ip -o addr show | grep "${MASTER_IP}/" | awk '{print $2}')
if [ -z "${MASTER_IFACE}" ]; then
    echo "ERROR: could not detect interface with IP ${MASTER_IP} on master"
    rm -rf "${LOG_DIR}"
    exit 1
fi

echo ">>> Starting tcpdump on master (interface ${MASTER_IFACE})..."
sudo tcpdump -i "${MASTER_IFACE}" -w "${TCPDUMP_PCAP}" -U \
    'tcp or icmp' >/dev/null 2>&1 &
TCPDUMP_PID=$!
echo "    tcpdump PID=${TCPDUMP_PID}  pcap=${TCPDUMP_PCAP}"
echo ""

# ---------------------------------------------------------------
# Step 4: Launch workers on remote machines (rank 1..N-1)
# Each worker runs inside a Docker container with --network host
# so it shares the host's network stack
# ---------------------------------------------------------------
WORKER_PIDS=()

for i in $(seq 1 $((TOTAL - 1))); do
    WORKER_IP="${SUBNET}.$((i + 1))"
    WORKER_USER="${USERNAMES[$i]}"
    REMOTE_APP_DIR="${APP_DIR/${USERNAMES[0]}/${WORKER_USER}}"
    WORKER_LOG="${LOG_DIR}/worker_rank${i}.log"

    echo ">>> Launching rank ${i} on ${WORKER_USER}@${WORKER_IP} (Docker)..."

    # Detect the interface name on the remote worker
    WORKER_IFACE=$(ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" \
        "ip -o addr show | grep '${WORKER_IP}/' | awk '{print \$2}'" 2>/dev/null)

    if [ -z "${WORKER_IFACE}" ]; then
        echo "  ERROR: could not detect interface with IP ${WORKER_IP} on ${WORKER_USER}"
        rm -rf "${LOG_DIR}"
        exit 1
    fi
    echo "    Interface: ${WORKER_IFACE}"

    # Run the worker inside Docker with --network host
    # --network host: share host network (so Gloo can bind to 10.0.0.x)
    # --rm: auto-remove container when done
    # -v results: mount results dir so output is saved on host
    ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" \
        "docker run --rm \
            --network host \
            --hostname ${WORKER_USER} \
            -v ${REMOTE_APP_DIR}/results:/app/results \
            -e MASTER_ADDR=${MASTER_IP} \
            -e MASTER_PORT=${MASTER_PORT} \
            -e RANK=${i} \
            -e WORLD_SIZE=${TOTAL} \
            -e MESSAGE_SIZES=${MSG_SIZES} \
            -e GLOO_SOCKET_IFNAME=${WORKER_IFACE} \
            ${IMAGE_NAME} \
            python3 /app/src/benchmark_worker.py ${MODE}" \
        >"${WORKER_LOG}" 2>&1 &

    WORKER_PIDS+=($!)
    echo "    PID=$! log=${WORKER_LOG}"
done

# Small delay to let workers start connecting
echo ""
echo ">>> Waiting 5s for workers to initialize..."
sleep 5

# Start tailing worker logs in background so we can see their output
TAIL_PIDS=()
for i in $(seq 1 $((TOTAL - 1))); do
    WORKER_LOG="${LOG_DIR}/worker_rank${i}.log"
    tail -f "${WORKER_LOG}" 2>/dev/null | sed "s/^/  [rank ${i}] /" &
    TAIL_PIDS+=($!)
done

# ---------------------------------------------------------------
# Step 5: Launch master (rank 0)
# ---------------------------------------------------------------
echo ">>> Launching rank 0 (master) on interface ${MASTER_IFACE} (Docker)..."

docker run --rm \
    --network host \
    --hostname "${USERNAMES[0]}" \
    -v "${APP_DIR}/results:/app/results" \
    -v "${APP_DIR}/plots:/app/plots" \
    -e MASTER_ADDR="${MASTER_IP}" \
    -e MASTER_PORT="${MASTER_PORT}" \
    -e RANK=0 \
    -e WORLD_SIZE="${TOTAL}" \
    -e MESSAGE_SIZES="${MSG_SIZES}" \
    -e GLOO_SOCKET_IFNAME="${MASTER_IFACE}" \
    "${IMAGE_NAME}" \
    python3 /app/src/benchmark_worker.py "${MODE}" "/app/results/results_ring_np${TOTAL}.json"

MASTER_EXIT=$?

# ---------------------------------------------------------------
# Step 6: Stop tcpdump and produce readable log
# ---------------------------------------------------------------
echo ""
echo ">>> Stopping tcpdump (PID=${TCPDUMP_PID})..."
sudo kill "${TCPDUMP_PID}" 2>/dev/null || true
wait "${TCPDUMP_PID}" 2>/dev/null || true

if [ -f "${TCPDUMP_PCAP}" ]; then
    echo ">>> Converting pcap to readable log..."
    sudo tcpdump -nn -r "${TCPDUMP_PCAP}" > "${TCPDUMP_LOG}" 2>/dev/null
    PACKET_COUNT=$(wc -l < "${TCPDUMP_LOG}")
    echo "    Captured ${PACKET_COUNT} packets"
    echo "    pcap: ${TCPDUMP_PCAP}"
    echo "    log:  ${TCPDUMP_LOG}"

    # Show a summary of src->dst pairs to verify ring routing
    echo ""
    echo "    --- Traffic summary (src -> dst) ---"
    # This was using ai, to help me extract it correctly.
    awk '{for(i=1;i<=NF;i++){if($i==">"){print $(i-1), "->", $(i+1)}}}' "${TCPDUMP_LOG}" \
        | sed 's/\.[0-9]*://g; s/://g' | sort | uniq -c | sort -rn | head -20 \
        | sed 's/^/    /'
    echo "    ---"
else
    echo "  WARNING: pcap file not found, tcpdump may have failed."
fi

# ---------------------------------------------------------------
# Step 7: Wait for all workers and check for failures
# ---------------------------------------------------------------
echo ""
echo ">>> Waiting for workers to finish..."
ALL_OK=true
for i in "${!WORKER_PIDS[@]}"; do
    RANK_IDX=$((i + 1))
    if wait "${WORKER_PIDS[$i]}" 2>/dev/null; then
        echo "  Rank ${RANK_IDX}: exited OK"
    else
        EXIT_CODE=$?
        echo "  Rank ${RANK_IDX}: FAILED (exit code ${EXIT_CODE})"
        echo "  --- Last 20 lines of log ---"
        tail -20 "${LOG_DIR}/worker_rank${RANK_IDX}.log" 2>/dev/null | sed 's/^/    /'
        echo "  ---"
        ALL_OK=false
    fi
done

# Kill background processes
for pid in "${TAIL_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
done

if [ "$ALL_OK" = false ] || [ "$MASTER_EXIT" -ne 0 ]; then
    echo ""
    echo "ERROR: Some ranks failed. Check logs in ${LOG_DIR}/"
    echo "Worker logs:"
    for f in "${LOG_DIR}"/*.log; do
        echo "  $f"
    done
    exit 1
fi

# ---------------------------------------------------------------
# Step 8: Generate plots
# ---------------------------------------------------------------
echo ""
echo ">>> Generating plots..."
docker run --rm \
    -v "${APP_DIR}/results:/app/results" \
    -v "${APP_DIR}/plots:/app/plots" \
    "${IMAGE_NAME}" \
    python3 /app/src/plot_results.py /app/results /app/plots

echo ""
echo "============================================"
echo "  Distributed benchmark complete!"
echo "  Results: ${APP_DIR}/results/"
echo "  Plots:   ${APP_DIR}/plots/"
echo "============================================"
