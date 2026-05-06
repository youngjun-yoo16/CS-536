#!/usr/bin/env bash
#
# bonusVerifyRing.sh: Verify that ring topology is enforced.
#
# Checks routing table, ARP, IP forwarding, pings all machines,
# and runs traceroute to verify packets go through the ring.
#

set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "Usage: sudo $0 <MY_INDEX> <TOTAL_MACHINES> <INTERFACE>"
    exit 1
fi

MY_INDEX=$1
TOTAL=$2
IFACE=$3
SUBNET="10.0.0"
MY_IP="${SUBNET}.$((MY_INDEX + 1))"

# All output goes to both the terminal and a log file.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/tcpdump"
mkdir -p "${LOG_DIR}"
VERIFY_LOG="${LOG_DIR}/verify_ring_m${MY_INDEX}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "${VERIFY_LOG}") 2>&1
echo "Log file: ${VERIFY_LOG}"

echo "============================================"
echo "  Ring Topology Verification"
echo "  Machine${MY_INDEX} (${MY_IP})"
echo "============================================"

# Check IP forwarding is enabled
# For my classmates:
# sysctl -n net.ipv4.ip_forward checks the value of the ip_forward sysctl parameter
# if it is 1, then IP forwarding is enabled
# if it is 0, then IP forwarding is disabled
echo ""
echo ">>> IP forwarding status:"
FWD=$(sysctl -n net.ipv4.ip_forward)
if [ "$FWD" -eq 1 ]; then
    echo "  net.ipv4.ip_forward = 1 (GOOD :) )"
else
    echo "  net.ipv4.ip_forward = 0 (BAD: ring forwarding won't work! :'( )"
fi

# Check reverse path filtering is off
# This is important because it prevents the kernel from dropping packets
# that are not sent to the interface that the packet was received on
echo ""
echo ">>> Reverse path filtering:"
RPF_ALL=$(sysctl -n net.ipv4.conf.all.rp_filter)
RPF_IFACE=$(sysctl -n "net.ipv4.conf.${IFACE}.rp_filter")
echo "  all.rp_filter = ${RPF_ALL} (should be 0)"
echo "  ${IFACE}.rp_filter = ${RPF_IFACE} (should be 0)"

echo ""
echo ">>> Routing table (${IFACE}):"
ip route show dev "${IFACE}"

echo ""
echo ">>> ARP table (${IFACE}):"
ip neigh show dev "${IFACE}"

# For my classmates:
# - ping -c 1 -W 3 sends 1 ping packet with a timeout of 3 seconds
# - if the ping is successful, it will return 0
# - if the ping fails, it will return a non-zero value
echo ""
echo ">>> Ping test to all machines:"
ALL_OK=true
for i in $(seq 0 $((TOTAL - 1))); do
    if [ "$i" -eq "$MY_INDEX" ]; then
        continue
    fi
    TARGET="${SUBNET}.$((i + 1))"
    if ping -c 1 -W 3 "${TARGET}" > /dev/null 2>&1; then
        echo "  Machine${i} (${TARGET}): OK"
    else
        echo "  Machine${i} (${TARGET}): FAIL"
        ALL_OK=false
    fi
done

echo ""
if [ "$ALL_OK" = true ]; then
    echo "All machines reachable!"
else
    echo "WARNING: Some machines are unreachable."
    echo "Make sure all machines have run bonusSetupRing.sh and are connected to the switch."
fi

echo ""
echo ">>> Traceroute to verify ring path:"
echo "    Machine to the right = 1 hop, two away = 2 hops, and so on."
echo ""
for i in $(seq 0 $((TOTAL - 1))); do
    if [ "$i" -eq "$MY_INDEX" ]; then
        continue
    fi
    TARGET="${SUBNET}.$((i + 1))"
    # calculate expected hops going clockwise
    HOPS=$(( (i - MY_INDEX + TOTAL) % TOTAL ))
    echo "  Path to Machine${i} (${TARGET}) — expected ${HOPS} hop(s):"
    traceroute -n -m 10 "${TARGET}" 2>/dev/null || echo "    (traceroute failed)"
    echo ""
done

echo "DONE"
