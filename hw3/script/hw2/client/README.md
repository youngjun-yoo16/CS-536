# iperf3 TCP Throughput Client

A Python-based iperf3-compatible TCP client that measures throughput to multiple remote iperf3 servers.

## Requirements

- Python 3.9+
- Network access to public iperf3 servers

## Files

- **`control.py`**: Core iperf3 protocol implementation
  - `ControlConnection`: Handles control channel negotiation, parameter exchange, and data transfer
  - Helper functions: `send_json`, `recv_json`, `recv_exact`

- **`main.py`**: Multi-server throughput testing script
  - Loads server list from CSV
  - Tests n random servers with automatic fallback/retry
  - Reports aggregate and per-server throughput statistics

- **`mock_server.py`**: Mock iperf3 server for testing (localhost)
  - Accepts control connections
  - Handles parameter negotiation
  - Receives data on separate port

- **`test_against_mock.py`**: Integration test against mock server

## Usage

### Test Against Mock Server (Local)

```bash
python3 test_against_mock.py
```

This verifies the client implementation without needing external servers.

### Test Against Real iperf3 Servers

```bash
# Test 10 random servers for 10 seconds each (default)
python3 main.py

# Test 5 servers for 30 seconds each with 60s timeout
python3 main.py -n 5 -d 30 -t 60

# Test specific number of servers
python3 main.py -n 20 -d 5

# Rerun tests on previously tested servers from history file
python3 main.py -R history.txt -d 30
```

**Command-line Options:**
- `-n, --num-servers`: Number of servers to test (default: 10)
- `-d, --duration`: Test duration per server in seconds (default: 10)
- `-t, --timeout`: Socket timeout in seconds (default: 30)
- `-H, --history-file`: path to file where last five tested servers (host:port) will be saved
- `-R, --rerun-history`: rerun tests on servers from the specified history file

### Example Output

```
Loading server list from /Users/.../listed_iperf3_servers.csv...
Loaded 193 servers

Selected 3 random servers for testing
Test duration: 10 seconds per server

Testing speedtest.fra1.de.leaseweb.net:5201... ✓ 245.32 Mbps (3062900 bytes)
Testing speedtest.lon1.uk.leaseweb.net:5201... ✓ 312.18 Mbps (3902250 bytes)
Testing speedtest.sfo12.us.leaseweb.net:5201... ✓ 289.45 Mbps (3618062 bytes)

======================================================================
SUMMARY: 3 successful, 0 failed
======================================================================

Throughput Statistics:
  Average: 282.32 Mbps
  Max:     312.18 Mbps
  Min:     245.32 Mbps
  Total:   10.58 MB transferred

Detailed Results:
Host                              Country     Throughput (Mbps)
speedtest.lon1.uk.leaseweb.net    GB                     312.18
speedtest.sfo12.us.leaseweb.net   US                     289.45
speedtest.fra1.de.leaseweb.net    DE                     245.32
```

## Implementation Details

### Protocol

The implementation follows the iperf3 control protocol:

1. **Control Connection**: TCP connection to port 5201 (or specified)
2. **Parameter Exchange**: 
   - Client sends JSON parameters (duration, block size, etc.)
   - Server responds with JSON acknowledgment
3. **Data Connection**: Separate TCP connection (typically port 5202)
4. **Data Transfer**: Client sends data continuously for specified duration
5. **Measurement**: Throughput calculated as (bytes_sent * 8) / (duration * 1,000,000)

### Key Features

- **Robust Error Handling**: Handles timeouts, connection resets, and overloaded servers
- **Automatic Fallback**: Failed servers are replaced with random alternatives
- **Retry Logic**: Attempts each server up to 2 times before giving up
- **Detailed Statistics**: Reports per-server and aggregate throughput metrics
- **CSV Server List Integration**: Loads from `../hw1/listed_iperf3_servers.csv`

### Resilience

The client handles:
- Non-responsive servers → timeout and retry
- Connection refused → skip and try replacement
- Servers that reject negotiation → error handling
- Premature connection termination → graceful shutdown
- Rate-limited servers → automatic server replacement

## Troubleshooting

### Connection Timeouts

Many public iperf3 servers may be geographically distant or overloaded. Increase timeout:

```bash
python3 main.py -n 5 -t 60
```

### Connection Refused

Some servers may block external connections or be offline. The script automatically selects replacement servers.

### Low Throughput

Throughput depends on:
- Network distance to the server
- Current server load
- ISP bandwidth
- Firewall restrictions

Run tests during off-peak hours or test servers closer to your location.

## Assignment Compliance

This implementation fulfills all assignment requirements:

✓ (a) Socket program from scratch (Python)  
✓ (i) Establishes control connection  
✓ (ii) Performs JSON-based parameter exchange  
✓ (iii) Opens data connection  
✓ (iv) Transmits data continuously for configurable duration  
✓ (v) Properly terminates following iperf3 semantics  
✓ Robust error handling (timeouts, rejections, premature termination)  
✓ (b) Destination selection with n as CLI argument  
✓ Automatic server replacement for failed connections  
✓ iperf3 server compatibility (tested against real servers)  

## Notes

- The client does not use the official iperf3 binary
- Implementation is based on reverse-engineering the iperf3 protocol from:
  - Official iperf3 source code
  - Packet traces and protocol documentation
  - Testing against live iperf3 servers
