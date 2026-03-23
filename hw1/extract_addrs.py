#!/usr/bin/env python3
"""
Script to extract addresses/hosts from iperf3serverlist.net
and convert them to a Python list and pandas DataFrame.
Fetches the latest data from the website each time it runs.
"""

import pandas as pd
import requests
from io import StringIO


def load_servers_dataframe(url: str = None) -> pd.DataFrame:
    """
    Load CSV data from URL into a pandas DataFrame.
    
    Args:
        url: URL to fetch CSV from. Defaults to iperf3serverlist.net export URL.
    
    Returns:
        DataFrame with server information
    """
    if url is None:
        url = 'https://export.iperf3serverlist.net/listed_iperf3_servers.csv'
    
    # Fetch CSV data from URL
    response = requests.get(url)
    response.raise_for_status()  # Raise exception for bad status codes
    
    # Parse CSV from response text
    df = pd.read_csv(StringIO(response.text))
    
    # Remove any rows with empty IP/HOST
    df = df[df['IP/HOST'].notna() & (df['IP/HOST'].str.strip() != '')]
    return df


def extract_addrs_list(df: pd.DataFrame) -> list[str]:
    """Extract IP/HOST column as a Python list."""
    return df['IP/HOST'].tolist()


def main():
    print("Fetching latest iperf3 server list from iperf3serverlist.net...")
    
    # Load into pandas DataFrame from URL
    df = load_servers_dataframe()
    
    # Extract IPs as a list
    addrs = extract_addrs_list(df)
    
    # Print as a Python list
    print("\n# List of iperf3 server IPs/hosts")
    print(f"IPERF3_SERVERS = {addrs}")
    print(f"\n# Total servers: {len(addrs)}")
    
    # Show DataFrame info
    print("\n# DataFrame Preview:")
    print(df.head(10))
    print(f"\n# DataFrame shape: {df.shape}")


if __name__ == '__main__':
    main()
