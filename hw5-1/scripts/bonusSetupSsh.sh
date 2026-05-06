#!/usr/bin/env bash
#
# bonusSetupSsh.sh: Setup passwordless SSH between ring machines.
#
# Run this on each machine after running bonusSetupRing.sh.
# Uses sshpass so we don't have to type anything.
#
# Machines:
#   hw5-0 (master) -> 10.0.0.1
#   hw5-1          -> 10.0.0.2
#   hw5-2          -> 10.0.0.3
#   hw5-3          -> 10.0.0.4
#   hw5-4          -> 10.0.0.5
#
# Password for all: root2214
#

set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <MY_INDEX> <TOTAL_MACHINES>"
    echo "Example: $0 0 5    (run on hw5-0, the master, with 5 machines)"
    echo "         $0 1 3    (run on hw5-1, with 3 machines)"
    exit 1
fi

MY_INDEX=$1
TOTAL=$2
SUBNET="10.0.0"
PASSWORD="root2214"

# Create the usernames
USERNAMES=()
for i in $(seq 0 $((TOTAL - 1))); do
    USERNAMES+=("hw5-${i}")
done

MY_USER="${USERNAMES[$MY_INDEX]}"
MY_IP="${SUBNET}.$((MY_INDEX + 1))"

echo "============================================"
echo "  SSH Setup for Ring Machines"
echo "  Machine${MY_INDEX} (${MY_USER}@${MY_IP})"
echo "============================================"

# ---------------------------------------------------------------
# Step 1: Generate SSH key if it doesn't exist
# ---------------------------------------------------------------
if [ ! -f ~/.ssh/id_rsa ]; then
    echo ">>> Generating SSH key..."
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    ssh-keygen -t rsa -b 2048 -f ~/.ssh/id_rsa -N "" -q
    echo "    Key generated."
else
    echo ">>> SSH key already exists, skipping generation."
fi

# ---------------------------------------------------------------
# Step 2: Copy SSH key to all other machines
# ---------------------------------------------------------------
echo ""
echo ">>> Copying SSH key to all other machines..."

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"

for i in $(seq 0 $((TOTAL - 1))); do
    if [ "$i" -eq "$MY_INDEX" ]; then
        continue
    fi

    TARGET_USER="${USERNAMES[$i]}"
    TARGET_IP="${SUBNET}.$((i + 1))"

    echo "  Copying to Machine${i} (${TARGET_USER}@${TARGET_IP})..."
    sshpass -p "${PASSWORD}" ssh-copy-id ${SSH_OPTS} "${TARGET_USER}@${TARGET_IP}" 2>/dev/null && \
        echo "      Done!!!!1" || \
        echo "      Failed: make sure Machine${i} is reachable and sshd is running"
done

# ---------------------------------------------------------------
# Step 3: Test SSH connections
# ---------------------------------------------------------------
echo ""
echo ">>> Testing passwordless SSH connections..."

ALL_OK=true
for i in $(seq 0 $((TOTAL - 1))); do
    if [ "$i" -eq "$MY_INDEX" ]; then
        continue
    fi

    TARGET_USER="${USERNAMES[$i]}"
    TARGET_IP="${SUBNET}.$((i + 1))"

    if ssh ${SSH_OPTS} -o ConnectTimeout=5 "${TARGET_USER}@${TARGET_IP}" "echo OK" 2>/dev/null | grep -q "OK"; then
        echo "  Machine${i} (${TARGET_USER}@${TARGET_IP}): connected"
    else
        echo "  Machine${i} (${TARGET_USER}@${TARGET_IP}): not connected"
        ALL_OK=false
    fi
done

echo ""
if [ "$ALL_OK" = true ]; then
    echo "============================================"
    echo "  All SSH connections working!"
    echo "============================================"
else
    echo "============================================"
    echo "  Some connections failed."
    echo "============================================"
fi
