#!/usr/bin/env bash
#
# bonusRunDist.sh: Run benchmarks across physical machines in the ring topology.
#
# This script should be run from Machine 0 (the master).
# It SSHs into each other machine to launch a worker inside Docker, then runs
# the master locally. 
#
#
# Environment variables:
#   MSG_SIZES   - comma separated message sizes
#   RANKS_LIST  - space-separated process sizes to test
#   APP_DIR     - path to project on each machine
#   MODE        - all / allgather / broadcast  (default: all)
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

MSG_SIZES="${MSG_SIZES:-1024,4096,16384,65536,262144,1048576,4194304,16777216}"

# RANKS_LIST: all powers of 2 that fit (so recursive_doubling and
# swing can run), plus TOTAL itself, it will just show ring though.
if [ -z "${RANKS_LIST:-}" ]; then
    RANKS_LIST=""
    p=2
    while [ "$p" -le "$TOTAL" ]; do
        RANKS_LIST="${RANKS_LIST} ${p}"
        p=$((p * 2))
    done
    # Add TOTAL if not included 
    if ! echo "${RANKS_LIST}" | grep -qw "${TOTAL}"; then
        RANKS_LIST="${RANKS_LIST} ${TOTAL}"
    fi
    RANKS_LIST="${RANKS_LIST# }"  
fi

echo "============================================"
echo "  Benchmark"
echo "  Total machines: ${TOTAL}"
echo "  Processes:    ${RANKS_LIST}"
echo "  Master:         ${USERNAMES[0]}@${MASTER_IP}"
echo "  Mode:           ${MODE}"
echo "  App dir:        ${APP_DIR}"
echo "  Docker:         ${IMAGE_NAME}"
echo "============================================"

mkdir -p "${APP_DIR}/results" "${APP_DIR}/plots" "${APP_DIR}/tcpdump"

# ---------------------------------------------------------------
# Step 1: Verify Docker image exists on master and all workers
# The image must be pre-built by setup.sh (before ring removes internet)
# ---------------------------------------------------------------
echo ""
echo ">>> Checking Docker image '${IMAGE_NAME}' on all machines..."

if ! docker image inspect "${IMAGE_NAME}" >/dev/null 2>&1; then
    echo "  ERROR: Docker image '${IMAGE_NAME}' not found on master."
    echo "  Run 'sudo ./scripts/setup.sh' first (while you still have internet)."
    exit 1
fi
echo "  Master: OK"

for i in $(seq 1 $((TOTAL - 1))); do
    WORKER_IP="${SUBNET}.$((i + 1))"
    WORKER_USER="${USERNAMES[$i]}"

    printf "  Machine%d (%s@%s): " "$i" "$WORKER_USER" "$WORKER_IP"

    if ! ssh ${SSH_OPTS} -o ConnectTimeout=5 "${WORKER_USER}@${WORKER_IP}" "echo OK" 2>/dev/null | grep -q "OK"; then
        echo "FAIL - SSH connection failed"
        exit 1
    fi

    if ! ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" "docker image inspect ${IMAGE_NAME}" >/dev/null 2>&1; then
        echo "FAIL - Docker image '${IMAGE_NAME}' not found"
        echo "  Run 'sudo ./scripts/setup.sh' on Machine${i} first (while it still has internet)."
        exit 1
    fi

    echo "OK"
done
echo ""

# ---------------------------------------------------------------
# Step 2: Detect master ring interface (used for every world-size run)
# ---------------------------------------------------------------
MASTER_IFACE=$(ip -o addr show | grep "${MASTER_IP}/" | awk '{print $2}')
if [ -z "${MASTER_IFACE}" ]; then
    echo "ERROR: could not detect interface with IP ${MASTER_IP} on master."
    echo "Make sure bonusSetupRing.sh has been run on this machine."
    exit 1
fi
echo "Master ring interface: ${MASTER_IFACE}"
echo ""

echo ">>> Killing any leftover ${IMAGE_NAME} containers from previous runs..."
docker ps -q --filter ancestor="${IMAGE_NAME}" | xargs -r docker kill 2>/dev/null || true
for i in $(seq 1 $((TOTAL - 1))); do
    WORKER_IP="${SUBNET}.$((i + 1))"
    WORKER_USER="${USERNAMES[$i]}"
    ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" \
        "docker ps -q --filter ancestor='${IMAGE_NAME}' | xargs -r docker kill 2>/dev/null; true" 2>/dev/null || true
done
echo ""

# ---------------------------------------------------------------
# Step 3: Go through each group of processes, launch workers via SSH, run master locally
# For each process size we run the full benchmark suite (all algorithms)
# ---------------------------------------------------------------
for PROCESS_SIZE in ${RANKS_LIST}; do
    if [ "${PROCESS_SIZE}" -gt "${TOTAL}" ]; then
        echo "WARNING: Skipping process size ${PROCESS_SIZE} (only ${TOTAL} machines available)"
        continue
    fi

    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    LOG_DIR=$(mktemp -d "${APP_DIR}/results/.worker_logs_np${PROCESS_SIZE}_XXXX")
    TCPDUMP_PCAP="${APP_DIR}/tcpdump/ring_np${PROCESS_SIZE}_${TIMESTAMP}.pcap"
    TCPDUMP_LOG="${APP_DIR}/tcpdump/ring_np${PROCESS_SIZE}_${TIMESTAMP}.log"

    echo "============================================"
    echo "  Running process size = ${PROCESS_SIZE}"
    echo "  Worker logs: ${LOG_DIR}"
    echo "  Tcpdump:     ${TCPDUMP_PCAP}"
    echo "============================================"

    # ---- Start tcpdump on master to capture ring traffic ----
    echo ">>> Starting tcpdump on master (${MASTER_IFACE})..."
    sudo tcpdump -i "${MASTER_IFACE}" -w "${TCPDUMP_PCAP}" -U \
        'tcp or icmp' >/dev/null 2>&1 &
    TCPDUMP_PID=$!
    echo "    tcpdump PID=${TCPDUMP_PID}  pcap=${TCPDUMP_PCAP}"
    echo ""

    # ---- Launch workers (rank 1 .. WORLD_SIZE-1) via SSH ----
    # Each worker runs in Docker with --network host so it shares the
    # host's ring IP (10.0.0.x) and the routing/ARP we configured.
    WORKER_PIDS=()

    for i in $(seq 1 $((PROCESS_SIZE - 1))); do
        WORKER_IP="${SUBNET}.$((i + 1))"
        WORKER_USER="${USERNAMES[$i]}"
        REMOTE_APP_DIR="${APP_DIR/${USERNAMES[0]}/${WORKER_USER}}"
        WORKER_LOG="${LOG_DIR}/worker_rank${i}.log"

        echo ">>> Launching rank ${i} on ${WORKER_USER}@${WORKER_IP} (Docker)..."

        # Detect ring interface on the remote worker by its ring IP
        WORKER_IFACE=$(ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" \
            "ip -o addr show | grep '${WORKER_IP}/' | awk '{print \$2}'" 2>/dev/null)

        if [ -z "${WORKER_IFACE}" ]; then
            echo "  ERROR: could not detect interface with IP ${WORKER_IP} on ${WORKER_USER}"
            echo "  Make sure bonusSetupRing.sh has been run on Machine${i}."
            sudo pkill -SIGINT -f "tcpdump.*${TCPDUMP_PCAP}" 2>/dev/null || true
            rm -rf "${LOG_DIR}"
            exit 1
        fi
        echo "    Ring interface: ${WORKER_IFACE}"

        # --network host  → container shares host ring IP; Gloo binds to 10.0.0.x
        # GLOO_SOCKET_IFNAME → tells Gloo which interface to use
        ssh ${SSH_OPTS} "${WORKER_USER}@${WORKER_IP}" \
            "docker run --rm \
                --network host \
                --hostname ${WORKER_USER} \
                -v ${REMOTE_APP_DIR}/results:/app/results \
                -e MASTER_ADDR=${MASTER_IP} \
                -e MASTER_PORT=${MASTER_PORT} \
                -e RANK=${i} \
                -e WORLD_SIZE=${PROCESS_SIZE} \
                -e MESSAGE_SIZES=${MSG_SIZES} \
                -e GLOO_SOCKET_IFNAME=${WORKER_IFACE} \
                ${IMAGE_NAME} \
                python3 /app/src/benchmark_worker.py ${MODE}" \
            >"${WORKER_LOG}" 2>&1 &

        WORKER_PIDS+=($!)
        echo "    PID=$! log=${WORKER_LOG}"
    done

    echo ""
    echo ">>> Waiting 5s for workers to initialize..."
    sleep 5

    # Tail worker logs so output is visible in the master's terminal
    TAIL_PIDS=()
    for i in $(seq 1 $((PROCESS_SIZE - 1))); do
        WORKER_LOG="${LOG_DIR}/worker_rank${i}.log"
        tail -f "${WORKER_LOG}" 2>/dev/null | sed "s/^/  [rank ${i}] /" &
        TAIL_PIDS+=($!)
    done

    # ---- Launch master (rank 0) ----
    echo ">>> Launching rank 0 (master) on ${MASTER_IFACE} (Docker)..."

    docker run --rm \
        --network host \
        --hostname "${USERNAMES[0]}" \
        -v "${APP_DIR}/results:/app/results" \
        -v "${APP_DIR}/plots:/app/plots" \
        -e MASTER_ADDR="${MASTER_IP}" \
        -e MASTER_PORT="${MASTER_PORT}" \
        -e RANK=0 \
        -e WORLD_SIZE="${PROCESS_SIZE}" \
        -e MESSAGE_SIZES="${MSG_SIZES}" \
        -e GLOO_SOCKET_IFNAME="${MASTER_IFACE}" \
        "${IMAGE_NAME}" \
        python3 /app/src/benchmark_worker.py "${MODE}" "/app/results/results_ring_np${PROCESS_SIZE}.json"

    MASTER_EXIT=$?

    echo ""
    echo ">>> Stopping tcpdump (PID=${TCPDUMP_PID})..."
    sudo pkill -SIGINT -f "tcpdump.*${TCPDUMP_PCAP}" 2>/dev/null || true
    wait "${TCPDUMP_PID}" 2>/dev/null || true
    sleep 1  # let tcpdump flush and finalize the pcap

    if [ -f "${TCPDUMP_PCAP}" ]; then
        echo ">>> Converting pcap to readable log..."
        sudo tcpdump -nn -r "${TCPDUMP_PCAP}" > "${TCPDUMP_LOG}" 2>/dev/null || true
        PACKET_COUNT=$(wc -l < "${TCPDUMP_LOG}")
        echo "    Captured ${PACKET_COUNT} packets"
        echo "    log:  ${TCPDUMP_LOG}"
        echo ""
        echo "    --- Traffic (src -> dst) ---"
        awk '{for(i=1;i<=NF;i++){if($i==">"){print $(i-1), "->", $(i+1)}}}' "${TCPDUMP_LOG}" \
            | sed 's/\.[0-9]*://g; s/://g' | sort | uniq -c | sort -rn | head -20 \
            | sed 's/^/    /' || true
        echo "    ---"
	sudo rm -rf ${TCPDUMP_PCAP}
    else
        echo "  WARNING: pcap file not found, tcpdump may have failed."
    fi

    # ---- Wait for workers and report failures ----
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

    for pid in "${TAIL_PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done

    if [ "$ALL_OK" = false ] || [ "$MASTER_EXIT" -ne 0 ]; then
        echo ""
        echo "ERROR: Some ranks failed for process size ${PROCESS_SIZE}."
        echo "Check logs in ${LOG_DIR}/"
        exit 1
    fi

    echo ""
    echo "  Process size ${PROCESS_SIZE}: DONE"
    echo ""
done

# ---------------------------------------------------------------
# Step 4: Generate comparison plots from all result files
# Plot reads every results_ring_np*.json in the results/ directory.
# ---------------------------------------------------------------
echo ">>> Generating plots..."
docker run --rm \
    -v "${APP_DIR}/results:/app/results" \
    -v "${APP_DIR}/plots:/app/plots" \
    "${IMAGE_NAME}" \
    python3 /app/src/plot_results.py /app/results /app/plots

echo ""
echo "============================================"
echo "  Benchmark complete!"
echo "  Results: ${APP_DIR}/results/"
echo "  Plots:   ${APP_DIR}/plots/"
echo "  Tcpdump: ${APP_DIR}/tcpdump/"
echo "============================================"
