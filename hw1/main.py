#!/usr/bin/env python3
"""
Main script to automate all network experiments and plotting.
Runs ping tests, traceroute analysis, and generates all plots in one command.

Usage:
    python main.py                                    # Use default website source
    python main.py --input-file my_servers.csv        # Use custom input file
    python main.py --output-dir ./results             # Custom output directory
    python main.py --skip-ping                        # Skip ping tests
    python main.py --skip-traceroute                  # Skip traceroute tests
    python main.py -v                                 # Verbose output
"""

import argparse
import sys
import os
import time
from pathlib import Path
import pandas as pd
from typing import List, Optional, Dict, Tuple

# Import functions from existing modules
from extract_addrs import load_servers_dataframe, extract_addrs_list
from ping_addr import ping_all_addrs
from find_rtt import select_random_ips, run_traceroute, parse_traceroute, run_ping, write_results_to_csv
from plot_distance_rtt import plot_distance_vs_rtt
from plot_latency_breakdown import plot_latency_breakdown
from plot_hopcount_rtt import plot_hopcount_vs_rtt


class ExperimentRunner:
    """Orchestrates all network experiments and plotting."""
    
    def __init__(self, output_dir: str = ".", verbose: bool = False):
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.stats = {
            'total_ips': 0,
            'ping_success': 0,
            'ping_failed': 0,
            'traceroute_ips': 0,
            'traceroute_success': 0,
            'traceroute_failed': 0,
            'plots_generated': []
        }
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, message: str, level: str = "INFO"):
        """Print log message with timestamp."""
        timestamp = time.strftime("%H:%M:%S")
        if level == "ERROR":
            print(f"[{timestamp}] ❌ ERROR: {message}", file=sys.stderr)
        elif level == "SUCCESS":
            print(f"[{timestamp}] ✓ {message}")
        elif level == "VERBOSE" and self.verbose:
            print(f"[{timestamp}] → {message}")
        else:
            print(f"[{timestamp}] {message}")
    
    def print_separator(self, char="=", length=70):
        """Print a separator line."""
        print(char * length)
    
    def load_ip_addresses(self, input_file: Optional[str] = None) -> List[str]:
        """
        Load IP addresses from either website (default) or custom file.
        
        Args:
            input_file: Optional path to CSV or text file with IP addresses
            
        Returns:
            List of IP addresses/hostnames
        """
        self.print_separator()
        self.log("STEP 1: Loading IP Addresses")
        self.print_separator()
        
        try:
            if input_file:
                self.log(f"Loading IP addresses from file: {input_file}")
                
                # Determine file format
                file_path = Path(input_file)
                if not file_path.exists():
                    raise FileNotFoundError(f"Input file not found: {input_file}")
                
                if file_path.suffix.lower() == '.csv':
                    # Try to load as CSV with IP/HOST column
                    df = pd.read_csv(file_path)
                    if 'IP/HOST' in df.columns:
                        addrs = df['IP/HOST'].dropna().tolist()
                    elif 'ip' in df.columns:
                        addrs = df['ip'].dropna().tolist()
                    elif 'host' in df.columns:
                        addrs = df['host'].dropna().tolist()
                    else:
                        # Assume first column contains IPs
                        addrs = df.iloc[:, 0].dropna().tolist()
                else:
                    # Load as plain text file (one IP per line)
                    with open(file_path, 'r') as f:
                        addrs = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                
                # Filter out empty strings
                addrs = [addr for addr in addrs if addr]
                self.log(f"Loaded {len(addrs)} IP addresses from file", "SUCCESS")
                
            else:
                # Fetch from website (default)
                self.log("Fetching IP addresses from iperf3serverlist.net...")
                df = load_servers_dataframe()
                addrs = extract_addrs_list(df)
                self.log(f"Fetched {len(addrs)} IP addresses from website", "SUCCESS")
            
            self.stats['total_ips'] = len(addrs)
            
            if len(addrs) == 0:
                raise ValueError("No IP addresses found in input source")
            
            # Show sample of IPs
            if self.verbose:
                sample_size = min(5, len(addrs))
                self.log(f"Sample IPs: {addrs[:sample_size]}", "VERBOSE")
            
            return addrs
            
        except Exception as e:
            self.log(f"Failed to load IP addresses: {e}", "ERROR")
            raise
    
    def run_part1_ping(self, addrs: List[str]) -> str:
        """
        Run Part 1: Ping all IP addresses and save results.
        
        Args:
            addrs: List of IP addresses to ping
            
        Returns:
            Path to output CSV file
        """
        self.print_separator()
        self.log("PART 1: Ping Test and Round-Trip Time (RTT)")
        self.print_separator()
        
        output_csv = self.output_dir / "ping_results.csv"
        
        try:
            self.log(f"Pinging {len(addrs)} IP addresses (100 packets each)...")
            self.log("This may take a while. Please be patient.")
            
            start_time = time.time()
            
            # Run ping for all addresses
            results = ping_all_addrs(addrs)
            
            elapsed_time = time.time() - start_time
            
            # Count successes and failures
            for result in results:
                if result['error'] is None:
                    self.stats['ping_success'] += 1
                else:
                    self.stats['ping_failed'] += 1
            
            # Convert results to DataFrame and save
            results_df = pd.DataFrame(results)
            results_df.to_csv(output_csv, index=False)
            
            self.log(f"Ping tests completed in {elapsed_time:.1f} seconds", "SUCCESS")
            self.log(f"Results saved to: {output_csv}", "SUCCESS")
            self.log(f"Success: {self.stats['ping_success']}, Failed: {self.stats['ping_failed']}")
            
            return str(output_csv)
            
        except Exception as e:
            self.log(f"Ping tests failed: {e}", "ERROR")
            raise
    
    def run_part2_traceroute(self, addrs: List[str], num_ips: int = 5) -> str:
        """
        Run Part 2: Traceroute for randomly selected IP addresses.
        
        Args:
            addrs: List of IP addresses
            num_ips: Number of random IPs to traceroute (default: 5)
            
        Returns:
            Path to output CSV file
        """
        self.print_separator()
        self.log("PART 2: Latency Breakdown (Traceroute)")
        self.print_separator()
        
        output_csv = self.output_dir / "traceroute_results.csv"
        
        try:
            # Select random IPs (prefer actual IPs over hostnames)
            import re
            ip_pattern = re.compile(r'^\d+\.\d+\.\d+\.\d+$')
            valid_ips = [addr for addr in addrs if ip_pattern.match(addr)]
            
            if len(valid_ips) == 0:
                self.log("No valid IP addresses found (only hostnames). Using all addresses.", "VERBOSE")
                valid_ips = addrs
            
            num_to_select = min(num_ips, len(valid_ips))
            
            # Randomly select IPs
            import random
            selected_ips = random.sample(valid_ips, num_to_select)
            
            self.stats['traceroute_ips'] = len(selected_ips)
            
            self.log(f"Selected {len(selected_ips)} random IPs for traceroute:")
            for i, ip in enumerate(selected_ips, 1):
                self.log(f"  {i}. {ip}")
            
            # Run traceroute for each selected IP
            all_hops = []
            
            for i, ip in enumerate(selected_ips, 1):
                self.log(f"[{i}/{len(selected_ips)}] Tracing route to {ip}...")
                
                try:
                    output = run_traceroute(ip)
                    
                    if output:
                        hops = parse_traceroute(output, ip)
                        
                        if hops:
                            # Filter responsive hops
                            responsive_hops = [h for h in hops if h.get('is_responsive', True)]
                            
                            if responsive_hops:
                                # Replace final hop RTT with ping result
                                final_hop = None
                                for hop in reversed(hops):
                                    if hop.get('is_responsive', True) and hop.get('hop_ip'):
                                        final_hop = hop
                                        break
                                
                                if final_hop:
                                    ping_result = run_ping(ip)
                                    if ping_result:
                                        final_hop['min_rtt'] = ping_result['min_rtt']
                                        final_hop['max_rtt'] = ping_result['max_rtt']
                                        final_hop['avg_rtt'] = ping_result['avg_rtt']
                                
                                all_hops.extend(hops)
                                self.stats['traceroute_success'] += 1
                                self.log(f"  Found {len(responsive_hops)} responsive hops", "VERBOSE")
                            else:
                                self.log(f"  No responsive hops found", "VERBOSE")
                                self.stats['traceroute_failed'] += 1
                        else:
                            self.log(f"  No hops parsed from output", "VERBOSE")
                            self.stats['traceroute_failed'] += 1
                    else:
                        self.log(f"  Traceroute failed (no output)", "VERBOSE")
                        self.stats['traceroute_failed'] += 1
                        
                except Exception as e:
                    self.log(f"  Error tracing {ip}: {e}", "VERBOSE")
                    self.stats['traceroute_failed'] += 1
            
            # Write results to CSV
            if all_hops:
                write_results_to_csv(all_hops, str(output_csv))
                self.log(f"Traceroute results saved to: {output_csv}", "SUCCESS")
                self.log(f"Success: {self.stats['traceroute_success']}, Failed: {self.stats['traceroute_failed']}")
            else:
                self.log("No traceroute results to save", "ERROR")
                # Create empty CSV file to avoid errors in plotting
                pd.DataFrame(columns=['destination_ip', 'hop_number', 'hop_ip', 'min_rtt', 'max_rtt', 'avg_rtt']).to_csv(output_csv, index=False)
            
            return str(output_csv)
            
        except Exception as e:
            self.log(f"Traceroute tests failed: {e}", "ERROR")
            raise
    
    def generate_plots(self, ping_csv: str, traceroute_csv: str):
        """
        Generate all PDF plots from experiment results.
        
        Args:
            ping_csv: Path to ping results CSV
            traceroute_csv: Path to traceroute results CSV
        """
        self.print_separator()
        self.log("GENERATING PLOTS")
        self.print_separator()
        
        # Plot 1: Distance vs RTT
        try:
            self.log("Generating distance_vs_rtt.pdf...")
            output_file = self.output_dir / "distance_vs_rtt.pdf"
            plot_distance_vs_rtt(ping_csv, str(output_file))
            self.stats['plots_generated'].append(str(output_file))
            self.log(f"Generated: {output_file}", "SUCCESS")
        except Exception as e:
            self.log(f"Failed to generate distance_vs_rtt.pdf: {e}", "ERROR")
        
        # Plot 2: Latency Breakdown (stacked bar chart)
        try:
            self.log("Generating latency_breakdown.pdf...")
            output_file = self.output_dir / "latency_breakdown.pdf"
            plot_latency_breakdown(traceroute_csv, str(output_file))
            self.stats['plots_generated'].append(str(output_file))
            self.log(f"Generated: {output_file}", "SUCCESS")
        except Exception as e:
            self.log(f"Failed to generate latency_breakdown.pdf: {e}", "ERROR")
        
        # Plot 3: Hop Count vs RTT
        try:
            self.log("Generating hopcount_vs_rtt.pdf...")
            output_file = self.output_dir / "hopcount_vs_rtt.pdf"
            plot_hopcount_vs_rtt(traceroute_csv, str(output_file))
            self.stats['plots_generated'].append(str(output_file))
            self.log(f"Generated: {output_file}", "SUCCESS")
        except Exception as e:
            self.log(f"Failed to generate hopcount_vs_rtt.pdf: {e}", "ERROR")
    
    def print_summary(self):
        """Print final summary report."""
        self.print_separator("=")
        self.log("EXPERIMENT SUMMARY")
        self.print_separator("=")
        
        print(f"\n📊 Statistics:")
        print(f"  Total IP addresses: {self.stats['total_ips']}")
        print(f"\n  Part 1 - Ping Tests:")
        print(f"    Success: {self.stats['ping_success']}")
        print(f"    Failed:  {self.stats['ping_failed']}")
        
        print(f"\n  Part 2 - Traceroute Tests:")
        print(f"    IPs traced: {self.stats['traceroute_ips']}")
        print(f"    Success:    {self.stats['traceroute_success']}")
        print(f"    Failed:     {self.stats['traceroute_failed']}")
        
        print(f"\n📁 Output Files:")
        print(f"  CSV Files:")
        print(f"    - {self.output_dir / 'ping_results.csv'}")
        print(f"    - {self.output_dir / 'traceroute_results.csv'}")
        
        print(f"\n  PDF Plots:")
        if self.stats['plots_generated']:
            for plot in self.stats['plots_generated']:
                print(f"    - {plot}")
        else:
            print("    (No plots generated)")
        
        self.print_separator("=")
        self.log("All experiments completed!", "SUCCESS")
        self.print_separator("=")


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated network experiments: ping tests, traceroute, and plotting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                                    # Use default website source
  python main.py --input-file my_servers.csv        # Use custom input file
  python main.py --output-dir ./results             # Custom output directory
  python main.py --skip-ping                        # Skip ping tests
  python main.py --skip-traceroute                  # Skip traceroute tests
  python main.py -v                                 # Verbose output
        """
    )
    
    parser.add_argument(
        '-i', '--input-file',
        type=str,
        default=None,
        help='Path to CSV or text file with IP addresses (default: fetch from iperf3serverlist.net)'
    )
    
    parser.add_argument(
        '-o', '--output-dir',
        type=str,
        default='.',
        help='Output directory for results and plots (default: current directory)'
    )
    
    parser.add_argument(
        '--skip-ping',
        action='store_true',
        help='Skip Part 1 (ping tests)'
    )
    
    parser.add_argument(
        '--skip-traceroute',
        action='store_true',
        help='Skip Part 2 (traceroute tests)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    # Parse arguments
    args = parse_arguments()
    
    # Create experiment runner
    runner = ExperimentRunner(output_dir=args.output_dir, verbose=args.verbose)
    
    try:
        # Print banner
        runner.print_separator("=")
        print("╔═══════════════════════════════════════════════════════════════════╗")
        print("║         NETWORK EXPERIMENTS - AUTOMATED EXECUTION                 ║")
        print("║         CS536 - Homework 1                                        ║")
        print("╚═══════════════════════════════════════════════════════════════════╝")
        runner.print_separator("=")
        
        start_time = time.time()
        
        # Step 1: Load IP addresses
        addrs = runner.load_ip_addresses(args.input_file)
        
        # Step 2: Run Part 1 (Ping Tests)
        if not args.skip_ping:
            ping_csv = runner.run_part1_ping(addrs)
        else:
            runner.log("Skipping Part 1 (Ping Tests)")
            ping_csv = runner.output_dir / "ping_results.csv"
            if not ping_csv.exists():
                runner.log("Warning: ping_results.csv not found. Some plots may fail.", "ERROR")
        
        # Step 3: Run Part 2 (Traceroute Tests)
        if not args.skip_traceroute:
            traceroute_csv = runner.run_part2_traceroute(addrs, num_ips=5)
        else:
            runner.log("Skipping Part 2 (Traceroute Tests)")
            traceroute_csv = runner.output_dir / "traceroute_results.csv"
            if not traceroute_csv.exists():
                runner.log("Warning: traceroute_results.csv not found. Some plots may fail.", "ERROR")
        
        # Step 4: Generate all plots
        runner.generate_plots(str(ping_csv), str(traceroute_csv))
        
        # Print summary
        total_time = time.time() - start_time
        runner.print_summary()
        print(f"\n⏱️  Total execution time: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
        
        return 0
        
    except KeyboardInterrupt:
        runner.log("\nExecution interrupted by user", "ERROR")
        return 130
    except Exception as e:
        runner.log(f"Fatal error: {e}", "ERROR")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
