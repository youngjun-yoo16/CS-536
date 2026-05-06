#!/usr/bin/env bash
#
# setup.sh: Install everything needed to run the project.
#
# For Docker benchmarks: installs Docker
# For bonus (VM ring): installs Python, PyTorch, SSH, networking tools
#

set -euo pipefail

echo "============================================"
echo "  HW5 Setup"
echo "============================================"
echo ""

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME="${ID}"
else
    echo "Could not detect OS. Exiting."
    exit 1
fi

echo "Detected OS: ${OS_NAME}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo ./scripts/setup.sh"
    exit 1
fi

# ──────────────────────────────────────────────
# 1. System packages
# ──────────────────────────────────────────────
echo ">>> Installing system packages..."
apt-get update
apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    net-tools \
    iproute2 \
    iputils-ping \
    traceroute \
    tcpdump \
    openssh-server \
    openssh-client \
    curl \
    ca-certificates \
    gnupg

# ──────────────────────────────────────────────
# 2. Docker
# ──────────────────────────────────────────────
if command -v docker &> /dev/null; then
    echo ""
    echo ">>> Docker already installed: $(docker --version)"
else
    echo ""
    echo ">>> Installing Docker..."

    # Add Docker GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/${OS_NAME}/gpg" \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    # Add Docker repo
    ARCH=$(dpkg --print-architecture)
    echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/${OS_NAME} ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin

    # Start Docker
    systemctl enable --now docker

    echo ">>> Docker installed: $(docker --version)"
fi

# ──────────────────────────────────────────────
# 3. Python packages (PyTorch, matplotlib, numpy)
# ──────────────────────────────────────────────
echo ""
echo ">>> Installing Python packages..."
pip3 install --break-system-packages --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu 2>/dev/null || \
pip3 install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu

pip3 install --break-system-packages --no-cache-dir matplotlib numpy 2>/dev/null || \
pip3 install --no-cache-dir matplotlib numpy

# ──────────────────────────────────────────────
# 4. SSH
# ──────────────────────────────────────────────
echo ""
echo ">>> Enabling SSH server..."
systemctl enable --now ssh 2>/dev/null || systemctl enable --now sshd 2>/dev/null || true

# ──────────────────────────────────────────────
# 5. Make all scripts executable
# ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
chmod +x "${SCRIPT_DIR}"/*.sh

# ──────────────────────────────────────────────
# 6. Add user to docker group
# ──────────────────────────────────────────────
sudo usermod -aG docker $USER
newgrp docker

# ──────────────────────────────────────────────
# 6. Install sshpass
# ──────────────────────────────────────────────
if ! command -v sshpass &>/dev/null; then
    echo ">>> Installing sshpass..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq sshpass
    else
        echo "ERROR: sshpass not found."
        exit 1
    fi
fi  


# ──────────────────────────────────────────────
# 7. Pre-build Docker image
# ──────────────────────────────────────────────
echo ""
echo ">>> Building Docker image 'hw5-collectives'..."
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if docker build -t hw5-collectives "${PROJECT_DIR}" 2>&1 | tail -5; then
    echo "    Docker image 'hw5-collectives' built successfully."
else
    echo "    WARNING: Docker image build failed. You can retry later with:"
    echo "    docker build -t hw5-collectives ${PROJECT_DIR}"
fi

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
