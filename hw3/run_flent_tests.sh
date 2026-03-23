#!/bin/bash
set -e

# Configuration
HOST="advent.cs.purdue.edu"
DURATION=10
PLOTS_BASE="/home/hw3/plots"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Flent TCP Congestion Control Test${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Clean previous results
echo -e "${YELLOW}[*] Cleaning previous test results...${NC}"
rm -rf "${PLOTS_BASE}/reno" "${PLOTS_BASE}/expo" "${PLOTS_BASE}/bbr" "${PLOTS_BASE}/cubic"
echo -e "${GREEN}    ✓ Cleaned${NC}"
echo ""

# Function to run test for a specific congestion control
run_test() {
    local cong=$1
    local plot_dir="${PLOTS_BASE}/${cong}/8tcp"
    
    echo -e "${GREEN}[*] Testing ${cong} (tcp_8up)...${NC}"
    
    # Create plot directory
    mkdir -p "$plot_dir"
    cd "$plot_dir"
    
    # Set congestion control
    echo -e "${YELLOW}    Setting congestion control to ${cong}${NC}"
    sudo sysctl -w net.ipv4.tcp_congestion_control=$cong >/dev/null
    
    # Run flent test
    echo -e "${YELLOW}    Running tcp_8up test (${DURATION}s)...${NC}"
    flent tcp_8up -H $HOST -l $DURATION \
	--test-parameter controlport=4444 \
        --socket-stats \
        -t "${cong^^} - 8 Stream Stress Test" \
        -o "${cong}_full_load.flent.gz"
    
    echo -e "${GREEN}    ✓ Test complete${NC}"
    echo ""
}

# Function to run single TCP stream test
run_test_single() {
    local cong=$1
    local plot_dir="${PLOTS_BASE}/${cong}/1tcp"
    
    echo -e "${GREEN}[*] Testing ${cong} (tcp_1up - single stream)...${NC}"
    
    # Create plot directory
    mkdir -p "$plot_dir"
    cd "$plot_dir"
    
    # Set congestion control
    echo -e "${YELLOW}    Setting congestion control to ${cong}${NC}"
    sudo sysctl -w net.ipv4.tcp_congestion_control=$cong >/dev/null
    
    # Run single stream flent test
    echo -e "${YELLOW}    Running tcp_1up test (${DURATION}s)...${NC}"
    flent tcp_upload -H $HOST -l $DURATION \
	--test-parameter controlport=4444 \
        --socket-stats \
        -t "${cong^^} - Single Stream Test" \
        -o "${cong}_single.flent.gz"
    
    echo -e "${GREEN}    ✓ Test complete${NC}"
    echo ""
}

# Function to generate plots for 8-stream test
generate_plots() {
    local cong=$1
    local plot_dir="${PLOTS_BASE}/${cong}/8tcp"
    
    echo -e "${GREEN}[*] Generating 8tcp plots for ${cong}...${NC}"
    cd "$plot_dir"
    
    # Throughput plot
    echo -e "${YELLOW}    → throughput.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_8up-*.flent.gz \
        -p upload \
        --figure-width 14 --figure-height 8 \
        --legend-placement "right" \
        -o throughput.png 2>/dev/null
    
    # CWND plot
    echo -e "${YELLOW}    → cwnd.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_8up-*.flent.gz \
        -p tcp_cwnd \
        --figure-width 14 --figure-height 8 \
        --legend-placement "right" \
        -o cwnd.png 2>/dev/null
    
    # RTT plot
    echo -e "${YELLOW}    → rtt.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_8up-*.flent.gz \
        -p tcp_rtt \
        --figure-width 14 --figure-height 8 \
        --legend-placement "right" \
        -o rtt.png 2>/dev/null
    
    # Combined diagnosis plot
    echo -e "${YELLOW}    → diagnosis.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_8up-*.flent.gz \
        -p upload_with_ping_and_tcp_rtt \
        --figure-width 18 --figure-height 10 \
        --legend-placement "upper right" \
        -o diagnosis.png 2>/dev/null
    
    echo -e "${GREEN}    ✓ 8tcp plots generated in ${plot_dir}/${NC}"
    echo ""
}

# Function to generate plots for single stream test
generate_plots_single() {
    local cong=$1
    local plot_dir="${PLOTS_BASE}/${cong}/1tcp"
    
    echo -e "${GREEN}[*] Generating 1tcp plots for ${cong}...${NC}"
    cd "$plot_dir"
    
    # Throughput plot 
    echo -e "${YELLOW}    → throughput.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_upload-*.flent.gz \
        -p totals \
        --figure-width 14 --figure-height 8 \
        --legend-placement "right" \
        -o throughput.png 2>/dev/null
    
    # CWND plot
    echo -e "${YELLOW}    → cwnd.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_upload-*.flent.gz \
        -p tcp_cwnd \
        --figure-width 14 --figure-height 8 \
        --legend-placement "right" \
        -o cwnd.png 2>/dev/null
    
    # RTT plot
    echo -e "${YELLOW}    → rtt.png${NC}"
    MPLBACKEND=Agg flent -i ./tcp_upload-*.flent.gz \
        -p tcp_rtt \
        --figure-width 14 --figure-height 8 \
        --legend-placement "right" \
        -o rtt.png 2>/dev/null
    
    echo -e "${GREEN}    ✓ 1tcp plots generated in ${plot_dir}/${NC}"
    echo ""
}

# Main execution
echo -e "${BLUE}Step 1: Running Tests${NC}"
echo "-----------------------------------"

# Test Reno
run_test "reno"
run_test_single "reno"

# Test BBr
run_test "bbr"
run_test_single "bbr"

# Test Cubic
run_test "cubic"
run_test_single "cubic"

# Test Expo
run_test "expo"
run_test_single "expo"

echo -e "${BLUE}Step 2: Generating Plots${NC}"
echo "-----------------------------------"

# Generate plots for Reno
generate_plots "reno"
generate_plots_single "reno"

# Generate plots for BBr
generate_plots "bbr"
generate_plots_single "bbr"

# Generate plots for Cubic
generate_plots "cubic"
generate_plots_single "cubic"

# Generate plots for Expo
generate_plots "expo"
generate_plots_single "expo"

echo -e "${BLUE}Step 3: Generating Comparison CSVs${NC}"
echo "-----------------------------------"
python3 /home/hw3/generate_comparison.py

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  All tests complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Results:"
echo "  Reno 8tcp: ${PLOTS_BASE}/reno/8tcp/"
echo "  Reno 1tcp: ${PLOTS_BASE}/reno/1tcp/"
echo "  BBR  8tcp: ${PLOTS_BASE}/bbr/8tcp/"
echo "  BBR  1tcp: ${PLOTS_BASE}/bbr/1tcp/"
echo "  Cubic 8tcp: ${PLOTS_BASE}/cubic/8tcp/"
echo "  Cubic 1tcp: ${PLOTS_BASE}/cubic/1tcp/"
echo "  Expo 8tcp: ${PLOTS_BASE}/expo/8tcp/"
echo "  Expo 1tcp: ${PLOTS_BASE}/expo/1tcp/"
echo ""
echo "Comparison CSVs:"
echo "  ${PLOTS_BASE}/single_stream_comparison.csv"
echo "  ${PLOTS_BASE}/multi_stream_comparison.csv"
echo "  ${PLOTS_BASE}/multi_stream_per_flow.csv"
echo ""
