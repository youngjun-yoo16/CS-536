#!/usr/bin/env python3
"""
Script to create a scatter plot: hop count vs RTT
where hop count is the number of hops to reach each destination IP address.
Each data point corresponds to a destination IP address.

This script reads traceroute results and plots the relationship between
the number of network hops and the round-trip time for each destination.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np


def plot_hopcount_vs_rtt(csv_file: str = 'traceroute_results.csv', output_file: str = 'hopcount_vs_rtt.pdf'):
    """
    Create a scatter plot of hop count vs round-trip time.
    Each data point corresponds to a destination IP address.
    
    Args:
        csv_file: Path to the CSV file containing traceroute results
        output_file: Path to save the plot image
    """
    # Read the CSV file containing traceroute results
    # Expected columns: destination_ip, hop_number, hop_ip, min_rtt, max_rtt, avg_rtt
    df = pd.read_csv(csv_file)
    
    if df.empty:
        print("No data found in traceroute_results.csv")
        return
    
    # Group by destination_ip to process each destination separately
    # Each group contains all the hops (rows) for that destination IP
    results = []
    for dest_ip, group in df.groupby('destination_ip'):
        # Hop count: Count the number of responsive hops for this destination
        # This represents the path length (number of intermediate routers + destination)
        # We use len(group) because each row in the group is one responsive hop
        hop_count = len(group)
        
        # RTT: We use the final hop's RTT (the destination's RTT)
        # 
        # Why the final hop? The assignment asks for "hop count vs rtt" where each
        # data point corresponds to a destination IP. The RTT for a destination IP
        # should be the end-to-end round-trip time from your machine to that destination,
        # which is measured at the final hop (the destination itself).
        #
        # We sort by hop_number first because traceroute results may not be in order
        # (some hops might be filtered out, creating gaps in hop_number sequence).
        # Then we take the last row (iloc[-1]) which corresponds to the highest
        # hop_number, i.e., the final hop that reached the destination.
        group_sorted = group.sort_values('hop_number')
        final_rtt = group_sorted.iloc[-1]['avg_rtt']
        
        # Store the results for this destination
        results.append({
            'destination_ip': dest_ip,
            'hop_count': hop_count,
            'rtt': final_rtt
        })
    
    # Create a DataFrame from the collected results
    # This DataFrame has one row per destination IP with columns: destination_ip, hop_count, rtt
    plot_df = pd.DataFrame(results)
    
    if len(plot_df) == 0:
        print("No valid data points found for plotting.")
        return
    
    print(f"Plotting {len(plot_df)} data points...")
    
    # Create the scatter plot figure with appropriate size (width=10, height=6 inches)
    plt.figure(figsize=(10, 6))
    
    # Plot scatter points: x=hop_count, y=rtt
    # alpha=0.7: Makes points semi-transparent so overlapping points are visible
    # s=100: Size of the scatter points (in points^2)
    # edgecolors='black': Black border around each point for better visibility
    # linewidth=1.0: Width of the border line
    plt.scatter(plot_df['hop_count'], plot_df['rtt'], 
                alpha=0.7, s=100, edgecolors='black', linewidth=1.0)
    
    # Add axis labels and title
    plt.xlabel('Hop Count', fontsize=12)
    plt.ylabel('Round-Trip Time (ms)', fontsize=12)
    plt.title('Hop Count vs Round-Trip Time', fontsize=14, fontweight='bold')
    
    # Add grid lines for easier reading of values
    # alpha=0.3: Makes grid lines subtle (30% opacity)
    # linestyle='--': Dashed lines for the grid
    plt.grid(True, alpha=0.3, linestyle='--')
    
    # Annotate each scatter point with its destination IP address
    # This helps identify which point corresponds to which destination
    for _, row in plot_df.iterrows():
        plt.annotate(row['destination_ip'], 
                    (row['hop_count'], row['rtt']),  # Position of the point
                    xytext=(5, 5),  # Offset the label 5 points right and 5 points up
                    textcoords='offset points',  # Use offset coordinates
                    fontsize=8,  # Smaller font so labels don't clutter
                    alpha=0.7)  # Slightly transparent labels
    
    # Calculate and display the correlation coefficient
    # This quantifies the linear relationship between hop count and RTT
    # Values range from -1 (perfect negative correlation) to +1 (perfect positive correlation)
    correlation = plot_df['hop_count'].corr(plot_df['rtt'])
    
    # Add correlation text in the top-left corner
    # transform=plt.gca().transAxes: Use axes coordinates (0-1) instead of data coordinates
    # This ensures the text stays in the same relative position regardless of data range
    plt.text(0.05, 0.95, f'Correlation: {correlation:.3f}', 
             transform=plt.gca().transAxes, fontsize=10,
             verticalalignment='top',  # Align text to top of bounding box
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))  # Rounded box background
    
    # Adjust layout to prevent label cutoff
    # tight_layout() automatically adjusts subplot parameters to fit labels
    plt.tight_layout()
    
    # Save the plot as a PDF file
    # dpi=300: High resolution (300 dots per inch) for publication quality
    # bbox_inches='tight': Include all elements (labels, annotations) in the saved image
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Plot saved to {output_file}")
    
    # Print summary statistics for verification
    print(f"\nStatistics:")
    print(f"  Total data points: {len(plot_df)}")
    print(f"  Hop count range: {plot_df['hop_count'].min()} - {plot_df['hop_count'].max()}")
    print(f"  RTT range: {plot_df['rtt'].min():.2f} - {plot_df['rtt'].max():.2f} ms")
    print(f"  Correlation coefficient: {correlation:.3f}")


def main():
    plot_hopcount_vs_rtt()


if __name__ == '__main__':
    main()
