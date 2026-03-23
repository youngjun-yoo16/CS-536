#!/usr/bin/env python3
"""
Script to ping IP addresses/hosts from Python list
and report min, max, and average round-trip times.
"""
from numpy import long
import pandas as pd
from icmplib import ping
from extract_addrs import extract_addrs_list, load_servers_dataframe
from geo_addr import get_geo

def ping_addr(addr_or_hostname: str) -> dict:
    """Ping an IP address/hostname and return round-trip time statistics."""
    
    try:
        # Ping handles both IP addresses and hostnames
        print("--------------------------------")
        print(f"Pinging {addr_or_hostname}...")
        response = ping(addr_or_hostname, count=100, interval=0.2, timeout=10, privileged=False)
        
        # Try to get geolocation 
        distance = None
        location = None
        try:
            geo_data = get_geo([addr_or_hostname])
            # handle error 
            if geo_data:
                distance = geo_data.get(addr_or_hostname, {}).get('distance_km')
                longitude = geo_data.get(addr_or_hostname, {}).get('longitude')
                latitude = geo_data.get(addr_or_hostname, {}).get('latitude')
                location = geo_data.get(addr_or_hostname, {}).get('location')
                if distance is None or location is None or longitude is None or latitude is None or distance == 'N/A' or location == 'N/A' or longitude == 'N/A' or latitude == 'N/A':
                    raise Exception("Geolocation data incomplete")
            else:
                raise Exception("Geolocation data not found")
        except Exception:
            # If geolocation fails (e.g., hostname not resolved), continue without it
            pass
        print("--------------------------------")
        
        return {
            'addr': addr_or_hostname,
            'min_rtt': response.min_rtt,
            'max_rtt': response.max_rtt,
            'avg_rtt': response.avg_rtt,
            'packet_loss': response.packet_loss,
            'geo_distance_km': distance,
            'longitude': longitude,
            'latitude': latitude,
            'location': location,
            'error': None
        }
    except Exception as e:
        # Handle nonresponsive servers or other errors
        return {
            'addr': addr_or_hostname,
            'min_rtt': None,
            'max_rtt': None,
            'avg_rtt': None,
            'packet_loss': None,
            'geo_distance_km': None,
            'longitude': None,
            'latitude': None,
            'location': None,
            'error': str(e)
        }
    
def ping_all_addrs(addrs: list[str]) -> list[dict]:
    """Ping all IP addresses/hosts in the list and return their statistics."""
    results = []
    for addr in addrs:
        stats = ping_addr(addr)
        results.append(stats)
    return results


def main():
    url = 'https://export.iperf3serverlist.net/listed_iperf3_servers.csv'
    
    # Load into pandas DataFrame
    df = load_servers_dataframe(url)
    
    # Extract Addrs (IPs, hostnames) as a list
    addrs = extract_addrs_list(df)
    
    results = ping_all_addrs(addrs)
    for result in results:
        if result['error']:
            print(f"Addr {result['addr']} - Error: {result['error']}")
        else:
            print(f"Addr {result['addr']} - Min RTT: {result['min_rtt']} ms, Max RTT: {result['max_rtt']} ms, "
                  f"Avg RTT: {result['avg_rtt']} ms, Packet Loss: {result['packet_loss']}%, "
                  f"Geo Distance: {result['geo_distance_km']} km, Longitude: {result['longitude']}, Latitude: {result['latitude']}, Location: {result['location']}")

    # Convert results to DataFrame for better visualization if needed
    results_df = pd.DataFrame(results)
    print("\n# Ping Results DataFrame Preview:")
    print(results_df.head(10))
    print(f"\n# Ping Results DataFrame shape: {results_df.shape}")
    
    # Save results to CSV file
    output_csv = 'ping_results.csv'
    results_df.to_csv(output_csv, index=False)
    print(f"\n# Results saved to {output_csv}")

if __name__ == '__main__':
    main()
