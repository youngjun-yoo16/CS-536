import os
import time

def check_lag(host):
    print(f"Testing latency to {host}... Press Ctrl+C to stop.")
    while True:
        # Sends 1 packet, waits 1 second
        response = os.popen(f"ping -c 1 {host}").read()
        if "time=" in response:
            time_ms = response.split("time=")[1].split(" ms")[0]
            print(f"Current Latency: {time_ms} ms")
        else:
            print("Packet Dropped!")
        time.sleep(0.5)

check_lag("37.19.206.20")