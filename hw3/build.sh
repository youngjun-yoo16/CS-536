#!/bin/bash
set -e

LOCAL_DIR=/home/hw3/tcp_expo
KERNEL_SRC="/usr/src/linux-source-5.15.0"
KERNEL_MOD_DIR="$KERNEL_SRC/net/ipv4/tcp_expo"
MOD_NAME="tcp_expo"

echo "[*] Syncing source into kernel tree"
sudo mkdir -p "$KERNEL_MOD_DIR"
sudo rsync -av --delete \
  --exclude='*.o' \
  --exclude='*.ko' \
  --exclude='modules.order' \
  --exclude='Module.symvers' \
  "$LOCAL_DIR/" "$KERNEL_MOD_DIR/"

echo "[*] Cleaning module build"
make -C "$KERNEL_SRC" M=net/ipv4/tcp_expo clean

echo "[*] Building module"
make -C "$KERNEL_SRC" -j$(nproc) M=net/ipv4/tcp_expo modules

echo "[*] Switching TCP away from expo (if active)"
sudo sysctl -w net.ipv4.tcp_congestion_control=reno >/dev/null || true

echo "[*] Removing old module (if loaded)"
sudo modprobe -r "$MOD_NAME" 2>/dev/null || true

# this will kill your network connection if you have any active TCP connections, so you have to reconnect
sudo ss -K dst 0.0.0.0/0
sudo rmmod tcp_expo
