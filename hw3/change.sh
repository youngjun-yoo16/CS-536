#!/bin/bash
set -e

LOCAL_DIR=/home/hw3/tcp_expo
KERNEL_SRC="/usr/src/linux-source-5.15.0"
KERNEL_MOD_DIR="$KERNEL_SRC/net/ipv4/tcp_expo"
MOD_NAME="tcp_expo"

if lsmod | grep -q "^$MOD_NAME"; then
    echo "[*] Module already loaded — skipping reload"
else
    echo "[*] Loading module"
    sudo insmod "$KERNEL_MOD_DIR/$MOD_NAME.ko"
fi

echo "[*] Switching TCP congestion control to expo"
sudo sysctl -w net.ipv4.tcp_congestion_control=expo

echo "[✓] tcp_expo rebuilt, reloaded, and active"
sudo sysctl net.ipv4.tcp_congestion_control