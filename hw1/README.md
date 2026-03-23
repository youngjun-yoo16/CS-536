# Writeup

## 1d) Explain whether and how distance relates to rtt.

## 1d) What do min and max rtt convey about the distance, and the network state?

## 2d) How does hop count relate to rtt?

Link to Course Website for easy access: https://stygianet.cs.purdue.edu/courses/2026springcs536.html

Link to Google Docs Writeup: https://docs.google.com/document/d/1jXdxOfkUqxfiSWhg5-Fuh_FxBvig86KIpE3WEbfVg08/edit?usp=sharing


________INSTRUCTIONS ON RUNNING main.py_________
# main.py - Quick Summary

## What It Does

The `main.py` script is a one-shot automation tool that runs all required experiments for the homework assignment:

**Part 1 - Ping Tests (Requirements 1a-1b):**
- Pings all IP addresses from iperf3serverlist.net (or custom file)
- Collects min/max/avg RTT for each IP
- Automatically fetches geolocation data for each IP
- Calculates geographical distance from your location to each server
- Generates `distance_vs_rtt.pdf` scatter plot

**Part 2 - Traceroute Analysis (Requirements 2a-2c):**
- Randomly selects 5 IPs from the list
- Runs traceroute to find all intermediate hops
- Filters out non-responsive hops automatically
- Generates `latency_breakdown.pdf` (stacked bar chart showing per-hop latency)
- Generates `hopcount_vs_rtt.pdf` (scatter plot of hop count vs RTT)

## How It Works

1. **Load IPs**: Fetches from website or reads from input file
2. **Part 1 Execution**: Pings all IPs (100 packets each), gets geolocation, saves to `ping_results.csv`
3. **Part 2 Execution**: Traceroutes 5 random IPs, saves to `traceroute_results.csv`
4. **Plotting**: Generates all 3 PDF plots automatically
5. **Summary**: Displays statistics and output file locations

## Usage

### Basic Usage (Default - Uses Website)
```bash
python main.py
```
This fetches all IPs from https://iperf3serverlist.net and runs all experiments.

### Use Custom Input File
```bash
python main.py --input-file my_servers.txt
```
Supports:
- Text files (one IP per line)
- CSV files (with IP/HOST column)

### Specify Output Directory
```bash
python main.py --output-dir ./results
```

### Advanced Options
```bash
python main.py --skip-ping          # Skip ping tests (use existing data)
python main.py --skip-traceroute    # Skip traceroute tests
python main.py -v                   # Verbose output
```

## Output Files

After running, you'll get:

**Data Files:**
- `ping_results.csv` - All ping statistics and geolocation data
- `traceroute_results.csv` - Traceroute hop-by-hop data

**Plot Files:**
- `distance_vs_rtt.pdf` - Distance vs RTT scatter plot (Part 1b)
- `latency_breakdown.pdf` - Stacked bar chart per hop (Part 2b)
- `hopcount_vs_rtt.pdf` - Hop count vs RTT scatter plot (Part 2c)

## Error Handling

The script automatically handles:
- Non-responsive servers (continues with others)
- Missing geolocation data (skips that entry)
- Traceroute timeouts (records failure, continues)
- Network failures (logs error, continues where possible)

## Example Run

```bash
# Full run with default website source
python main.py

# Quick test with sample IPs
python main.py --input-file test_servers.txt -v

# Re-generate plots from existing data
python main.py --skip-ping --skip-traceroute
```

## Notes

- **Time**: Expect 30-60+ minutes for full website run (depends on number of IPs)
- **Requirements**: Run `pip install -r req.txt` first
- **Permissions**: May need sudo for traceroute on some systems
- **Reproducibility**: Use `--input-file` with fixed IPs for consistent results
