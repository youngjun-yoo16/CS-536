#!/usr/bin/env python3
"""
Script to find round-trip times to intermediate hops using traceroute.
Picks 5 random IP addresses and traces the path to each destination.
"""

import subprocess
import re
import random
import csv
import sys
import platform
import statistics
from typing import List, Dict, Tuple, Optional
from extract_addrs import load_servers_dataframe, extract_addrs_list


def run_ping(ip: str, count: int = 3) -> Optional[Dict[str, float]]:
    """
    Run ping command to measure RTT to destination.
    
    Args:
        ip: Destination IP address
        count: Number of ping packets to send
    
    Returns:
        Dictionary with min_rtt, max_rtt, avg_rtt or None if ping fails
    """
    
    try:
        cmd = ['ping', '-c', str(count), ip]
        
        print(f"Pinging {ip} to get final hop RTT...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            print(f"Warning: Ping to {ip} failed")
            return None
        
        # Parse ping output to extract RTT values
        rtts = []

        # Unix ping format: "time=XX.XX ms"
        rtt_matches = re.findall(r'time=([\d\.]+)\s*ms', result.stdout, re.IGNORECASE)
        rtts = [float(r) for r in rtt_matches]
        
        if rtts:
            return {
                'min_rtt': min(rtts),
                'max_rtt': max(rtts),
                'avg_rtt': sum(rtts) / len(rtts)
            }
        else:
            print(f"Warning: Could not parse ping RTT values for {ip}")
            return None
    
    except subprocess.TimeoutExpired:
        print(f"Warning: Ping to {ip} timed out")
        return None
    except Exception as e:
        print(f"Error pinging {ip}: {e}")
        return None


def run_traceroute(ip: str, max_hops: int = 30, timeout: int = 2) -> str:
    """
    Run traceroute command for the given IP address.
    
    Args:
        ip: Destination IP address
        max_hops: Maximum number of hops to trace
        timeout: Timeout in seconds for each hop
    
    Returns:
        Raw traceroute output as string
    """
    try:
        # Unix/Linux traceroute command
        cmd = ['traceroute', '-m', str(max_hops), '-w', str(timeout), ip]
        
        print(f"Running traceroute to {ip}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # Overall timeout of 2 minutes
        )
        return result.stdout
    
    except subprocess.TimeoutExpired:
        print(f"Warning: Traceroute to {ip} timed out")
        return ""
    except FileNotFoundError:
        print(f"Error: Traceroute command not found. Make sure it's installed.")
        return ""
    except Exception as e:
        print(f"Error running traceroute to {ip}: {e}")
        return ""


def parse_traceroute(output: str, destination_ip: str) -> List[Dict[str, any]]:
    """
    Parse Unix/Linux traceroute output.
    
    Unix traceroute format:
    1  192.168.1.1 (192.168.1.1)  0.5 ms  0.3 ms  0.2 ms
    2  * * *
    3  10.0.0.1 (10.0.0.1)  10.1 ms  10.2 ms  10.3 ms
    
    Args:
        output: Raw traceroute output
        destination_ip: Destination IP being traced
    
    Returns:
        List of hop dictionaries with hop_number, hop_ip, and rtt values
    """
    hops = []
    lines = output.split('\n')
    
    # Pattern to match traceroute lines
    hop_pattern = re.compile(
        r'^\s*(\d+)\s+' +  # Hop number
        r'(?:([^\s\(]+)\s+)?' +  # Optional hostname
        r'(?:\(([^\)]+)\))?' +  # IP in parentheses
        r'(.+)$'  # Rest of line with RTTs
    )
    
    # Pattern for * * * lines
    timeout_pattern = re.compile(r'^\s*(\d+)\s+\*\s+\*\s+\*')
    
    for line in lines:
        # Check for timeout lines first (* * * hops)
        timeout_match = timeout_pattern.match(line)
        if timeout_match:
            hop_num = int(timeout_match.group(1))
            # Add non-responsive hop with 0ms RTT (will be filtered later)
            hops.append({
                'destination_ip': destination_ip,
                'hop_number': hop_num,
                'hop_ip': None,  # No IP for non-responsive hop
                'min_rtt': 0.0,
                'max_rtt': 0.0,
                'avg_rtt': 0.0,
                'is_responsive': False
            })
            continue
        
        match = hop_pattern.match(line)
        if match:
            hop_num = int(match.group(1))
            hostname = match.group(2)
            ip_addr = match.group(3)
            rtt_part = match.group(4)
            
            # If line has only asterisks, skip it (already handled above)
            if '*' in line and not ip_addr:
                continue
            
            # Extract RTT values
            rtt_matches = re.findall(r'([\d\.]+)\s*ms', rtt_part)
            
            if rtt_matches and ip_addr:
                rtts = [float(r) for r in rtt_matches]
                avg_rtt = sum(rtts) / len(rtts)
                min_rtt = min(rtts)
                max_rtt = max(rtts)
                
                hops.append({
                    'destination_ip': destination_ip,
                    'hop_number': hop_num,
                    'hop_ip': ip_addr,
                    'min_rtt': min_rtt,
                    'max_rtt': max_rtt,
                    'avg_rtt': avg_rtt,
                    'is_responsive': True
                })
    
    return hops

def select_random_ips(num_ips: int = 5) -> List[str]:
    """
    Select random IP addresses from the iperf3 server list.
    
    Args:
        num_ips: Number of random IPs to select
    
    Returns:
        List of IP addresses
    """
    print("Loading iperf3 server list...")
    df = load_servers_dataframe()
    addrs = extract_addrs_list(df)
    
    # Filter to get only valid IPs (not hostnames)
    # Simple check: contains dots and starts with a digit
    ip_pattern = re.compile(r'^\d+\.\d+\.\d+\.\d+$')
    valid_ips = [addr for addr in addrs if ip_pattern.match(addr)]
    
    print(f"Found {len(valid_ips)} valid IP addresses")
    
    # Select random IPs
    num_to_select = min(num_ips, len(valid_ips))
    selected = random.sample(valid_ips, num_to_select)
    
    print(f"Selected {num_to_select} random IPs: {selected}")
    return selected


def write_results_to_csv(hops: List[Dict[str, any]], output_file: str = 'p1/traceroute_results.csv'):
    """
    Write traceroute results to CSV file.
    Filters out non-responsive hops before writing.
    
    Args:
        hops: List of hop dictionaries
        output_file: Output CSV filename
    """
    if not hops:
        print("No hops to write to CSV")
        return
    
    # Filter out non-responsive hops (those with is_responsive=False)
    responsive_hops = [h for h in hops if h.get('is_responsive', True)]
    
    if not responsive_hops:
        print("No responsive hops to write to CSV")
        return
    
    # Define CSV columns (exclude is_responsive field)
    fieldnames = ['destination_ip', 'hop_number', 'hop_ip', 'min_rtt', 'max_rtt', 'avg_rtt']
    
    # Remove is_responsive field from dictionaries before writing
    csv_hops = []
    for hop in responsive_hops:
        csv_hop = {k: v for k, v in hop.items() if k in fieldnames}
        csv_hops.append(csv_hop)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_hops)
    
    print(f"\nResults written to {output_file}")
    print(f"Total responsive hops recorded: {len(csv_hops)}")


def main():
    """Main function to run traceroute analysis."""
    print("=" * 70)
    print("Traceroute RTT Analyzer")
    print("=" * 70)
    
    # Select 5 random IPs
    try:
        selected_ips = select_random_ips(num_ips=5)
    except Exception as e:
        print(f"Error selecting IPs: {e}")
        return 1
    
    if not selected_ips:
        print("No valid IPs found")
        return 1
    
    # Run traceroute for each IP and collect results
    all_hops = []
    successful_traces = 0
    
    for i, ip in enumerate(selected_ips, 1):
        print(f"\n[{i}/{len(selected_ips)}] Tracing route to {ip}")
        print("-" * 70)
        
        output = run_traceroute(ip)
    
        if output:
            hops = parse_traceroute(output, ip)
            
            if hops:
                # Filter to only responsive hops for counting
                responsive_hops = [h for h in hops if h.get('is_responsive', True)]
                print(f"Found {len(responsive_hops)} responsive hops (out of {len(hops)} total)")
                
                # Replace final hop RTT with ping RTT
                if responsive_hops:
                    # Get the final responsive hop (which should be the destination)
                    final_hop = None
                    for hop in reversed(hops):
                        if hop.get('is_responsive', True) and hop.get('hop_ip'):
                            final_hop = hop
                            break
                    
                    if final_hop:
                        # Use ping to get RTT for the final hop
                        ping_result = run_ping(ip)
                        if ping_result:
                            print(f"Replacing final hop RTT with ping result")
                            final_hop['min_rtt'] = ping_result['min_rtt']
                            final_hop['max_rtt'] = ping_result['max_rtt']
                            final_hop['avg_rtt'] = ping_result['avg_rtt']
                
                all_hops.extend(hops)
                successful_traces += 1
                
                # Print summary for this destination (only responsive hops)
                hop_summary = ', '.join([f"{h['hop_number']}:{h['hop_ip']}" 
                                        for h in responsive_hops[:5] if h.get('hop_ip')])
                if len(responsive_hops) > 5:
                    hop_summary += "..."
                print(f"Responsive hops: {hop_summary}")
            else:
                print(f"Warning: No hops found for {ip}")
        else:
            print(f"Warning: Failed to trace route to {ip}")
    
    # Write results to CSV
    print("\n" + "=" * 70)
    print(f"Traceroute completed for {successful_traces}/{len(selected_ips)} destinations")
    
    if all_hops:
        write_results_to_csv(all_hops, 'traceroute_results.csv')
        
        # Print statistics (only for responsive hops)
        responsive_hops = [h for h in all_hops if h.get('is_responsive', True)]
        if responsive_hops:
            print(f"\nStatistics:")
            print(f"  Total responsive hops: {len(responsive_hops)}")
            print(f"  Average RTT across all responsive hops: {sum(h['avg_rtt'] for h in responsive_hops) / len(responsive_hops):.2f} ms")
            print(f"  RTT range: {min(h['min_rtt'] for h in responsive_hops):.2f} - {max(h['max_rtt'] for h in responsive_hops):.2f} ms")
        else:
            print("No responsive hops found across all destinations")
            return 1
    else:
        print("No hops found across all destinations")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
