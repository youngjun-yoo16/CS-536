#!/usr/bin/env bash
#
# bonusSetupRing.sh: Configure ring topology on machines connected via a 5-port switch.
#
# Ring topology (5 machines):
#   Machine0 -> Machine1 -> Machine2 -> Machine3 -> Machine4 -> Machine0
#

set -euo pipefail

if [ "$#" -lt 3 ]; then
    echo "Usage: sudo $0 <MY_INDEX> <TOTAL_MACHINES> <INTERFACE>"
    echo "Example: sudo $0 0 5 enp0s1"
    exit 1
fi

MY_INDEX=$1
TOTAL=$2
IFACE=$3
SUBNET="10.0.0"

MY_IP="${SUBNET}.$((MY_INDEX + 1))"
RIGHT_INDEX=$(( (MY_INDEX + 1) % TOTAL ))
RIGHT_IP="${SUBNET}.$((RIGHT_INDEX + 1))"

echo "============================================"
echo "  Ring Topology Setup"
echo "  Machine index: ${MY_INDEX} / ${TOTAL}"
echo "  Interface:     ${IFACE}"
echo "============================================"
echo "My IP:          ${MY_IP}"
echo "Right neighbor: Machine${RIGHT_INDEX} at ${RIGHT_IP}"
echo ""

# ---------------------------------------------------------------
# Step 0: Disconnect external interfaces and prevent NM interference
#
# We bring down every interface that is NOT the ring interface and
# NOT loopback.  This isolates the machines from any external network
# so that all traffic is forced through the ring.
# ---------------------------------------------------------------
echo ">>> Step 0: Disconnecting external interfaces and preventing NM interference..."

# Bring down any non-loopback, non-ring interface
for iface_path in /sys/class/net/*/; do
    other=$(basename "${iface_path}")
    if [ "${other}" = "lo" ] || [ "${other}" = "${IFACE}" ]; then
        continue
    fi
    # Skip virtual/docker interfaces (docker0, veth*, br-*)
    if echo "${other}" | grep -qE '^(docker|veth|br-|virbr)'; then
        continue
    fi
    echo "    Bringing down external interface: ${other}"
    ip link set "${other}" down 2>/dev/null || true
done

if command -v nmcli &>/dev/null; then
    nmcli device set "${IFACE}" managed no 2>/dev/null || true
    echo "    NetworkManager: set ${IFACE} to unmanaged"
fi

# Avoid using netplan
if [ -d /run/systemd/network ]; then
    for f in /run/systemd/network/*; do
        if [ -f "$f" ] && grep -q "${IFACE}" "$f" 2>/dev/null; then
            echo "    Removing rendered config: $f"
            rm -f "$f"
        fi
    done
fi

# ---------------------------------------------------------------
# Step 1: Verify interface exists
# ---------------------------------------------------------------
echo ""
echo ">>> Step 1: Checking interface..."

if ! ip link show "${IFACE}" &>/dev/null; then
    echo "ERROR: Interface ${IFACE} does not exist!"
    echo "Available interfaces:"
    ip -br link show
    exit 1
fi

ip link set "${IFACE}" up
sleep 1

# Show current state
MY_MAC=$(ip link show "${IFACE}" | awk '/link\/ether/{print $2}')
LINK=$(cat "/sys/class/net/${IFACE}/carrier" 2>/dev/null || echo "0")
STATE=$(cat "/sys/class/net/${IFACE}/operstate" 2>/dev/null || echo "unknown")

echo "    MAC address:  ${MY_MAC}"
echo "    Carrier:      ${LINK} (1=cable connected)"
echo "    Oper state:   ${STATE}"

if [ "${LINK}" != "1" ]; then
    echo ""
    echo "WARNING: No link detected on ${IFACE}!"
    echo "Make sure the ethernet cable is plugged in."
fi

# ---------------------------------------------------------------
# Step 2: Configure IP address
# ---------------------------------------------------------------
echo ""
echo ">>> Step 2: Configuring IP address..."

# Remove any existing IP
ip addr flush dev "${IFACE}" 2>/dev/null || true
sleep 0.5

# Add our IP with /24
ip addr add "${MY_IP}/24" dev "${IFACE}"
ip link set "${IFACE}" up

echo "    Assigned: ${MY_IP}/24 on ${IFACE}"

# Verify it stuck
CURRENT_IP=$(ip -4 addr show dev "${IFACE}" | grep -oP '(?<=inet\s)\S+' | head -1)
echo "    Verified: ${CURRENT_IP}"

# ---------------------------------------------------------------
# Step 3: Enable IP forwarding
# ---------------------------------------------------------------
echo ""
echo ">>> Step 3: Enabling IP forwarding..."
sysctl -w net.ipv4.ip_forward=1 > /dev/null
echo "    ip_forward = 1"
# This allows us to make the machine forward packets to other machines

# ---------------------------------------------------------------
# Step 4: Disable reverse path filtering BEFORE setting routes
# We had to add this because otherwise the kernel would drop packets
# sent to the wrong interface
# ---------------------------------------------------------------
echo ""
echo ">>> Step 4: Disabling reverse path filtering and hardening ring..."
sysctl -w "net.ipv4.conf.${IFACE}.rp_filter=0" > /dev/null
sysctl -w net.ipv4.conf.all.rp_filter=0 > /dev/null
sysctl -w net.ipv4.conf.default.rp_filter=0 > /dev/null
echo "    rp_filter = 0 (all, default, ${IFACE})"

# Disable ICMP redirects — prevents a router along the path from
# telling senders to use a shorter route, which would break the ring.
sysctl -w "net.ipv4.conf.${IFACE}.send_redirects=0" > /dev/null
sysctl -w net.ipv4.conf.all.send_redirects=0 > /dev/null
sysctl -w "net.ipv4.conf.${IFACE}.accept_redirects=0" > /dev/null
sysctl -w net.ipv4.conf.all.accept_redirects=0 > /dev/null
echo "    send_redirects = 0 / accept_redirects = 0"

# Disable proxy ARP: we do NOT want any machine to answer ARP requests
# on behalf of another machine (that would allow direct MAC delivery,
# bypassing the ring routing).
sysctl -w "net.ipv4.conf.${IFACE}.proxy_arp=0" > /dev/null
sysctl -w net.ipv4.conf.all.proxy_arp=0 > /dev/null
echo "    proxy_arp = 0"

# ---------------------------------------------------------------
# Step 5: Configure routes for ring topology
# ---------------------------------------------------------------
echo ""
echo ">>> Step 5: Configuring ring routes..."

# Remove default route
ip route del default 2>/dev/null || true

# Flush all routes on this interface
ip route flush dev "${IFACE}" 2>/dev/null || true
sleep 0.5

# Keep the /24 subnet route so that ARP works for ALL machines on the segment.
ip route add "${SUBNET}.0/24" dev "${IFACE}" proto static
echo "    Added: ${SUBNET}.0/24 dev ${IFACE} (for ARP resolution)"

# Now add /32 routes for ring
# - Right neighbor: direct via interface
# - Everyone else: via right neighbor 
for i in $(seq 0 $((TOTAL - 1))); do
    if [ "$i" -eq "$MY_INDEX" ]; then
        continue  # skip this machine
    fi
 
    TARGET_IP="${SUBNET}.$((i + 1))"
    # 
    if [ "$i" -eq "$RIGHT_INDEX" ]; then
        # Right neighbor: direct via interface
        # For my classmates:
        # dev IFACE means the packet goes directly to the neighbor
        # proto static means the route is added manually
        ip route add "${TARGET_IP}/32" dev "${IFACE}" proto static
        echo "    Added: ${TARGET_IP}/32 dev ${IFACE} (right neighbor, direct)"
    else
        # Everyone else
        ip route add "${TARGET_IP}/32" via "${RIGHT_IP}" dev "${IFACE}" proto static
        echo "    Added: ${TARGET_IP}/32 via ${RIGHT_IP} (ring route)"
    fi
done

# ---------------------------------------------------------------
# Step 6: Wait for right neighbor and learn MAC via ARP
# ---------------------------------------------------------------
echo ""
echo ">>> Step 6: Discovering right neighbor (${RIGHT_IP})..."
echo "    Make sure Machine${RIGHT_INDEX} is running this script too!"
echo ""

RETRIES=30
RIGHT_MAC=""
for attempt in $(seq 1 $RETRIES); do
    # Send ARP request + ping
    # For my classmates:
    # arping -c 1 -w 1 -I "${IFACE}" "${RIGHT_IP}" > /dev/null 2>&1 || true
    # sends an ARP request to the right neighbor
    # ping -c 1 -W 1 "${RIGHT_IP}" > /dev/null 2>&1 || true
    # sends a ping to the right neighbor

    arping -c 1 -w 1 -I "${IFACE}" "${RIGHT_IP}" > /dev/null 2>&1 || true
    ping -c 1 -W 1 "${RIGHT_IP}" > /dev/null 2>&1 || true

    # Check ARP table
    # For my classmates:
    # ip neigh show "${RIGHT_IP}" dev "${IFACE}" 2>/dev/null \
    # shows the ARP entry for the right neighbor
    # grep -oP '([0-9a-f]{2}:){5}[0-9a-f]{2}' | head -1 \
    # extracts the MAC address
    RIGHT_MAC=$(ip neigh show "${RIGHT_IP}" dev "${IFACE}" 2>/dev/null \
        | grep -oP '([0-9a-f]{2}:){5}[0-9a-f]{2}' | head -1) 


    # If the MAC address is found, break the loop
    if [ -n "${RIGHT_MAC}" ]; then
        echo "    OK! Found neighbor! MAC: ${RIGHT_MAC} (attempt ${attempt})"
        break
    fi

    printf "    Attempt %2d/%d: waiting for Machine%d...\r" "$attempt" "$RETRIES" "$RIGHT_INDEX"
    sleep 2
done
echo ""

if [ -z "${RIGHT_MAC}" ]; then
    echo ""
    echo "WARNING: Could not discover right neighbor (${RIGHT_IP})."
    echo "Check that the interfece is correct and the other devices are correct"
fi

# ---------------------------------------------------------------
# Step 7: Set permanent ARP entry for right neighbor
# ---------------------------------------------------------------
echo ""
echo ">>> Step 7: Setting static ARP entries..."

if [ -z "${RIGHT_MAC}" ]; then
    # For my classmates:
    # If we couldn't discover the right neighbor, we can't set a static ARP entry.
    echo "    WARNING: RIGHT_MAC is empty"
else
    # Right neighbor: permanent ARP entry 
    ip neigh replace "${RIGHT_IP}" lladdr "${RIGHT_MAC}" nud permanent dev "${IFACE}"
    echo "    ${RIGHT_IP} -> ${RIGHT_MAC} (permanent, right neighbor)"

    # All other machines: point to RIGHT_MAC
    for i in $(seq 0 $((TOTAL - 1))); do
        if [ "$i" -eq "$MY_INDEX" ] || [ "$i" -eq "$RIGHT_INDEX" ]; then
            continue  # skip self and right neighbor
        fi
        TARGET_IP="${SUBNET}.$((i + 1))"
        ip neigh replace "${TARGET_IP}" lladdr "${RIGHT_MAC}" nud permanent dev "${IFACE}"
        echo "    ${TARGET_IP} -> ${RIGHT_MAC} (permanent, via right neighbor — ring enforcement)"
    done
fi

# ---------------------------------------------------------------
# Step 8: Disable firewall if running
# ---------------------------------------------------------------
echo ""
echo ">>> Step 8: Checking firewall..."

if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "active"; then
    echo "    UFW is active — disabling for ring to work"
    ufw disable 2>/dev/null || true
fi

# Flush iptables just in case
iptables -F 2>/dev/null || true
iptables -P FORWARD ACCEPT 2>/dev/null || true
echo "    iptables: flushed rules, FORWARD policy = ACCEPT"

# ---------------------------------------------------------------
# Done!
# ---------------------------------------------------------------
echo ""
echo "============================================"
echo " Ring setup complete for Machine${MY_INDEX}"
echo "============================================"
echo "  IP:        ${MY_IP}"
echo "  MAC:       ${MY_MAC}"
echo "  Next hop:  ${RIGHT_IP} (MAC: ${RIGHT_MAC:-unknown})"
echo ""
echo "Current routing table:"
ip route | sed 's/^/  /'
echo ""
echo "ARP table:"
ip neigh show dev "${IFACE}" | sed 's/^/  /'
echo ""

