#!/usr/bin/env python3
"""
Script to plot a stacked bar chart showing the breakdown of latencies to each hop,
corresponding to each of the five chosen destination IP addresses.
Uses incremental RTT per hop (segment = RTT at hop N minus RTT at hop N-1).

The "breakdown" means showing how much latency each hop contributes to the total.
We compute incremental RTT: the additional latency added by each hop along the path.
This allows us to stack segments where each segment represents one hop's contribution.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


def load_and_compute_incremental_rtt(csv_file: str = 'traceroute_results.csv') -> pd.DataFrame:
    """
    Load traceroute results and compute incremental RTT per hop for each destination.
    
    Incremental RTT represents the latency added by each hop:
    - Hop 1: incremental = RTT at hop 1 (since prev_rtt = 0)
    - Hop 2: incremental = RTT at hop 2 - RTT at hop 1
    - Hop 3: incremental = RTT at hop 3 - RTT at hop 2
    - etc.
    
    This breakdown allows us to visualize each hop's contribution in a stacked bar chart.
    The sum of all incremental RTTs equals the total end-to-end RTT.

    Returns:
        DataFrame with index=destination_ip, columns=Hop_1, Hop_2, ... (incremental RTT in ms)
    """
    # Read the CSV file containing traceroute results
    df = pd.read_csv(csv_file)
    if df.empty:
        return pd.DataFrame()

    # Sort by destination_ip first, then by hop_number within each destination
    # This ensures hops are processed in order for each destination
    df = df.sort_values(['destination_ip', 'hop_number'])

    # Process each destination IP separately
    records = []
    for dest_ip, group in df.groupby('destination_ip'):
        # Sort the group by hop_number to ensure hops are in correct order
        # (traceroute may have gaps in hop_number due to filtered non-responsive hops)
        group = group.sort_values('hop_number')
        
        # Extract the average RTT values for all hops in order
        rtts = group['avg_rtt'].values
        
        # Compute incremental RTT for each hop
        # prev_rtt tracks the cumulative RTT up to the previous hop
        prev_rtt = 0.0  # Start with 0 for the first hop
        increments = []
        
        for rtt in rtts:
            # Incremental RTT = current RTT - previous RTT
            # This gives us the latency added by this specific hop
            # max(0.0, ...) ensures we never have negative increments (safety check)
            inc = max(0.0, float(rtt) - prev_rtt)
            increments.append(inc)
            prev_rtt = float(rtt)  # Update for next iteration
        
        # Store the destination IP and its list of incremental RTTs
        records.append((dest_ip, increments))

    # Find the maximum number of hops across all destinations
    # This determines how many columns we need in the DataFrame
    max_hops = max(len(r[1]) for r in records)
    
    # Create column names: "Hop 1", "Hop 2", ..., "Hop N"
    col_names = [f'Hop {i + 1}' for i in range(max_hops)]

    # Build rows for the DataFrame
    # Each row represents one destination IP
    rows = []
    for dest_ip, incs in records:
        # Pad shorter paths with zeros so all rows have the same length
        # This is necessary for creating a rectangular DataFrame
        # Destinations with fewer hops will have zeros for the extra hop columns
        row = incs + [0.0] * (max_hops - len(incs))
        rows.append(row)

    # Create DataFrame: rows = destinations, columns = Hop 1, Hop 2, ..., Hop N
    # Index is the destination IP addresses
    return pd.DataFrame(rows, index=[r[0] for r in records], columns=col_names)


def plot_latency_breakdown(
    csv_file: str = 'traceroute_results.csv',
    output_file: str = 'latency_breakdown.pdf',
):
    """
    Plot a stacked bar chart: one bar per destination IP, segments = incremental
    latency per hop (breakdown of latencies to each hop).
    
    Each bar represents one destination IP address. The bar is divided into segments,
    where each segment corresponds to one hop along the path. The height of each
    segment shows the incremental latency added by that hop. The total bar height
    equals the end-to-end RTT to that destination.
    """
    # Load and compute incremental RTT for each hop of each destination
    # Returns DataFrame: rows = destination IPs, columns = Hop 1, Hop 2, ..., Hop N
    df = load_and_compute_incremental_rtt(csv_file)
    if df.empty:
        print("No data in traceroute_results.csv. Run find_rtt.py first.")
        return

    # Get the number of hop columns (maximum hops across all destinations)
    n_hops = df.shape[1]
    
    # Generate colors for each hop segment using the viridis colormap
    # viridis: perceptually uniform, colorblind-friendly, goes from dark purple to yellow
    # np.linspace(0, 1, n_hops): Creates n_hops evenly spaced values from 0 to 1
    # This maps to colors: first hops = dark purple/blue (cooler), last hops = yellow (hotter)
    # This visual progression helps distinguish early hops from late hops
    colors = plt.cm.viridis(np.linspace(0, 1, n_hops))

    # Create figure and axis objects
    # figsize=(10, 6): Width=10 inches, Height=6 inches
    fig, ax = plt.subplots(figsize=(10, 6))

    # Create stacked bar chart using pandas plot function
    # kind='bar': Bar chart type
    # stacked=True: Stack segments on top of each other (required for breakdown visualization)
    # ax=ax: Use the axis object we created
    # color=colors: Use our color array (one color per hop segment)
    # width=0.7: Bar width as fraction of available space (70% of category width)
    # edgecolor='white': White border between segments for better visual separation
    # linewidth=0.5: Thin border lines
    df.plot(kind='bar', stacked=True, ax=ax, color=colors, width=0.7, edgecolor='white', linewidth=0.5)

    # Set axis labels and title
    ax.set_xlabel('Destination IP Address', fontsize=12)
    ax.set_ylabel('Round-Trip Time (ms)', fontsize=12)
    ax.set_title('Breakdown of Latencies to Each Hop by Destination', fontsize=14, fontweight='bold')
    
    # Rotate x-axis labels for better readability (IP addresses can be long)
    # rotation=15: Rotate labels 15 degrees
    # ha='right': Right-align rotated labels
    ax.set_xticklabels(ax.get_xticklabels(), rotation=15, ha='right')
    
    # Add legend showing which color corresponds to which hop
    # title='Hop': Legend title
    # bbox_to_anchor=(1.02, 1): Position legend outside plot area (right side)
    # loc='upper left': Anchor point for positioning
    # fontsize=8: Smaller font to fit many hop labels
    # ncol=1: Single column layout for legend
    ax.legend(title='Hop', bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=8, ncol=1)
    
    # Add grid lines on y-axis only (helps read RTT values)
    # axis='y': Only horizontal grid lines
    # alpha=0.3: Subtle grid (30% opacity)
    # linestyle='--': Dashed lines
    ax.grid(True, axis='y', alpha=0.3, linestyle='--')
    
    # Place grid lines behind the bars (better visual appearance)
    ax.set_axisbelow(True)

    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    # Save the plot as PDF
    # dpi=300: High resolution (300 dots per inch) for publication quality
    # bbox_inches='tight': Include all elements (legend, labels) in saved image
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    
    # Close the figure to free memory
    plt.close()
    print(f"Stacked bar chart saved to {output_file}")


def main():
    plot_latency_breakdown()


if __name__ == '__main__':
    main()
