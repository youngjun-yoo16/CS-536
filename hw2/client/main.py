#!/usr/bin/env python3
"""
iperf3 TCP Throughput Client
Connects to multiple iperf3 servers and measures throughput.

Usage:
    python3 main.py -n 10 -d 10
    
Arguments:
    -n N: Number of servers to test (default 10)
    -d DURATION: Test duration in seconds per server (default 10)
    -H FILE: record last five successfully tested servers (host:port) in
        FILE.  The file will be overwritten on each run.
    -R FILE: rerun tests on servers listed in FILE (previously saved history)
"""

import argparse
import csv
import random
import sys
from pathlib import Path
from typing import Optional
from control import ControlConnection

# Path to server list
SERVER_LIST_PATH = Path(__file__).parent.parent.parent / "hw2" / "client" / "listed_iperf3_servers.csv"


def load_servers(csv_file: Path) -> list[dict]:
    """Load iperf3 server list from CSV."""
    servers = []
    try:
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Extract host and port from CSV
                host = row['IP/HOST'].strip()
                try:
                    # Port range is comma-separated or hyphen-separated
                    port_str = row['PORT'].strip()
                    if '-' in port_str:
                        # Range: pick the first port
                        port = int(port_str.split('-')[0])
                    else:
                        port = int(port_str)
                    
                    servers.append({
                        'host': host,
                        'port': port,
                        'country': row['COUNTRY'],
                        'site': row['SITE'],
                    })
                except (ValueError, KeyError):
                    # Skip rows with invalid port data
                    continue
    except FileNotFoundError:
        print(f"ERROR: Server list not found at {csv_file}", file=sys.stderr)
        sys.exit(1)
    
    return servers


def load_history_servers(history_file: Path) -> list[dict]:
    """Load iperf3 server list from history file (host:port lines)."""
    servers = []
    try:
        with open(history_file, 'r') as f:
            for line in f:
                line = line.strip()
                if ':' in line:
                    host, port_str, country = line.split(':', 2)
                    try:
                        port = int(port_str)
                        servers.append({
                            'host': host,
                            'port': port,
                            'country': country,
                            'site': 'history',
                        })
                    except ValueError:
                        continue
    except FileNotFoundError:
        print(f"ERROR: History file {history_file} not found", file=sys.stderr)
        sys.exit(1)
    
    return servers


def test_server(host: str, port: int, duration: int, timeout: int = 30, retries: int = 2) -> Optional[dict]:
    """
    Test a single server with retry logic. Returns result dict or None if failed.
    """
    
    for attempt in range(retries):
        try:
            print(f"Testing {host}:{port}...", end=" ", flush=True)
            
            ctrl = ControlConnection(host, port=port, timeout=timeout)
            result = ctrl.run_test(duration=duration, log_filename=f"{host}_{port}.csv", log_format="csv")

            return result
            
        except Exception as e:
            print(f"✗ {type(e).__name__}: {e}")
            if attempt < retries - 1:
                print("  Retrying...")
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description="iperf3 TCP Throughput Client"
    )
    parser.add_argument(
        '-n', '--num-servers',
        type=int,
        default=10,
        help='Number of servers to test (default 10)'
    )
    parser.add_argument(
        '-d', '--duration',
        type=int,
        default=10,
        help='Test duration per server in seconds (default 10)'
    )
    parser.add_argument(
        '-t', '--timeout',
        type=int,
        default=30,
        help='Socket timeout in seconds (default 30)'
    )
    parser.add_argument(
        '-H', '--history-file',
        type=Path,
        help='Optional path to a file where the last five tested servers will be recorded (host:port per line)'
    )
    
    parser.add_argument(
        '-R', '--rerun-history',
        type=Path,
        help='Rerun tests on servers from the specified history file'
    )
    
    args = parser.parse_args()
    
    # Load server list
    if args.rerun_history:
        print(f"Loading server list from history file {args.rerun_history}...")
        servers = load_history_servers(args.rerun_history)
    else:
        print(f"Loading server list from {SERVER_LIST_PATH}...")
        servers = load_servers(SERVER_LIST_PATH)
    print(f"Loaded {len(servers)} servers")
    
    if not servers:
        print("ERROR: No servers loaded", file=sys.stderr)
        sys.exit(1)
    
    if args.num_servers > len(servers):
        print(f"WARNING: Requested {args.num_servers} servers but only {len(servers)} available")
        args.num_servers = len(servers)
    
    # Select servers
    if args.rerun_history:
        selected_servers = servers[:args.num_servers]
        print(f"Selected {len(selected_servers)} servers from history for testing")
    else:
        selected_servers = random.sample(servers, args.num_servers)
        print(f"Selected {len(selected_servers)} random servers for testing")
    print(f"Test duration: {args.duration} seconds per server\n")
    
    # Test servers with fallback
    results = []
    tested_count = 0
    failed_count = 0
    
    for server_info in selected_servers:
        result = test_server(
            server_info['host'],
            server_info['port'],
            args.duration,
            timeout=args.timeout,
            retries=2
        )
        
        if result:
            results.append({
                **server_info,
                **result
            })
            tested_count += 1
        else:
            failed_count += 1
            
            # Try to find a replacement server
            print("  Selecting replacement server...", end=" ", flush=True)
            remaining = [s for s in servers if s not in selected_servers]
            if remaining:
                replacement = random.choice(remaining)
                replacement_result = test_server(
                    replacement['host'],
                    replacement['port'],
                    args.duration,
                    timeout=args.timeout,
                    retries=2
                )
                
                if replacement_result:
                    print("replacement successful")
                    results.append({
                        **replacement,
                        **replacement_result
                    })
                    tested_count += 1
                else:
                    print("replacement failed")
            else:
                print("no replacement available")
    
    # Print summary
    print("\n" + "="*70)
    print(f"SUMMARY: {tested_count} successful, {failed_count} failed")
    print("="*70)
    
    if results:
        # If the user asked for a history file record the last servers that were
        # actually tested.  We write host:port lines and keep only the most
        # recent five entries.
        if args.history_file:
            def _update_history(path, entries, max_entries=10):
                # read existing history lines
                existing = []
                try:
                    with open(path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                existing.append(line)
                except FileNotFoundError:
                    pass

                # add new entries, making sure duplicates move to the end
                for e in entries:
                    if e in existing:
                        existing.remove(e)
                    existing.append(e)

                trimmed = existing[-max_entries:]
                with open(path, 'w') as f:
                    for e in trimmed:
                        f.write(e + '\n')

            tested_servers = [f"{r['host']}:{r['port']}:{r['country']}" for r in results]
            _update_history(args.history_file, tested_servers)
            print(f"\nWrote history ({len(tested_servers)} entries) to {args.history_file}")
        
        # Calculate aggregate statistics
        throughputs = [r['throughput_mbps'] for r in results]
        total_bytes = sum(r['bytes_sent'] for r in results)
        avg_throughput = sum(throughputs) / len(throughputs)
        max_throughput = max(throughputs)
        min_throughput = min(throughputs)
        
        print(f"\nThroughput Statistics:")
        print(f"  Average: {avg_throughput:.2f} Mbps")
        print(f"  Max:     {max_throughput:.2f} Mbps")
        print(f"  Min:     {min_throughput:.2f} Mbps")
        print(f"  Total:   {total_bytes / (1024**3):.3f} GB transferred")
        
        print(f"\nDetailed Results:")
        print(f"{'Host':<35} {'Country':<10} {'Throughput (Mbps)':<20}")
        print("-" * 65)
        for r in sorted(results, key=lambda x: x['throughput_mbps'], reverse=True):
            print(f"{r['host']:<35} {r['country']:<10} {r['throughput_mbps']:>18.2f}")
    else:
        print("No successful tests. Check server connectivity and timeout settings.")
        sys.exit(1)


if __name__ == '__main__':
    main()
