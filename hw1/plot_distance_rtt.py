#!/usr/bin/env python3
"""
Script to create a scatter plot: distance vs RTT
where distance is the geographical distance between your location and destination IP address.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

def plot_distance_vs_rtt(csv_file: str = 'ping_results.csv', output_file: str = 'distance_vs_rtt.pdf'):
    """
    Create a scatter plot of geographical distance vs round-trip time.
    
    Args:
        csv_file: Path to the CSV file containing ping results
        output_file: Path to save the plot image
    """
    # Read the CSV file
    df = pd.read_csv(csv_file)
    
    # Filter out rows with missing data (errors, None values)
    # Also filter out RTT values <= 0 or very small (< 1 ms) which likely indicate blocked/failed pings
    df_clean = df[
        df['geo_distance_km'].notna() & 
        df['avg_rtt'].notna() & 
        (df['error'].isna() | (df['error'] == '')) &
        (df['avg_rtt'] > 1.0)  # Filter out RTT <= 1 ms (likely blocked/failed pings)
    ].copy()
    
    if len(df_clean) == 0:
        print("No valid data points found for plotting.")
        return
    
    # Count how many points were filtered out
    total_valid = len(df[df['geo_distance_km'].notna() & df['avg_rtt'].notna() & (df['error'].isna() | (df['error'] == ''))])
    filtered_out = total_valid - len(df_clean)
    if filtered_out > 0:
        print(f"Filtered out {filtered_out} data point(s) with RTT <= 1 ms (likely blocked/failed pings)")
    
    print(f"Plotting {len(df_clean)} data points...")
    
    # Create the scatter plot
    plt.figure(figsize=(10, 6))
    plt.scatter(df_clean['geo_distance_km'], df_clean['avg_rtt'], 
                alpha=0.6, s=50, edgecolors='black', linewidth=0.5)
    
    # Add labels and title
    plt.xlabel('Geographical Distance (km)', fontsize=12)
    plt.ylabel('Average Round-Trip Time (ms)', fontsize=12)
    plt.title('Distance vs Round-Trip Time', fontsize=14, fontweight='bold')
    plt.grid(True, alpha=0.3, linestyle='--')
    
    # Add some statistics as text
    correlation = df_clean['geo_distance_km'].corr(df_clean['avg_rtt'])
    plt.text(0.05, 0.95, f'Correlation: {correlation:.3f}', 
             transform=plt.gca().transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    # Tight layout for better appearance
    plt.tight_layout()
    
    # Save the plot
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Plot saved to {output_file}")
    
    # Optionally display the plot (uncomment if running interactively)
    # plt.show()
    
    # Print some statistics
    print(f"\nStatistics:")
    print(f"  Total valid data points: {len(df_clean)}")
    print(f"  Distance range: {df_clean['geo_distance_km'].min():.2f} - {df_clean['geo_distance_km'].max():.2f} km")
    print(f"  RTT range: {df_clean['avg_rtt'].min():.2f} - {df_clean['avg_rtt'].max():.2f} ms")
    print(f"  Correlation coefficient: {correlation:.3f}")


def main():
    plot_distance_vs_rtt()


if __name__ == '__main__':
    main()
