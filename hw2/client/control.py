# control.py

import socket
import json
import struct
import os
import time
from typing import Optional

COOKIE_SIZE = 37
RNDCHARS = b"abcdefghijklmnopqrstuvwxyz234567"  # Base32 character set
TEST_START = 1
TEST_RUNNING = 2
TEST_END = b'\x04'  # TEST_END is sent by client as a single byte
PARAM_EXCHANGE = 9
CREATE_STREAMS = 10
EXCHANGE_RESULTS = 13
DISPLAY_RESULTS = 14
IPERF_DONE = b'\x10'  # IPERF_DONE is sent by client as a single byte

# Helper Functions
def recv_exact(sock: socket.socket, n: int) -> bytes:
    """
    Receive exactly n bytes from the socket.
    Raises ConnectionError if the connection closes early.
    """
    data = b''
    while len(data) < n:
        try:
            packet = sock.recv(n - len(data))
        except socket.timeout:
            raise ConnectionError("Socket receive timed out")
        if not packet:
            raise ConnectionError("Socket connection lost")
        data += packet
    return data

def send_json(sock: socket.socket, obj: dict) -> None:
    """
    Send a JSON object with iperf3 length-prefixed framing.
    """
    payload = json.dumps(obj).encode('utf-8')
    length_prefix = struct.pack('!I', len(payload))
    sock.sendall(length_prefix)
    sock.sendall(payload)

def recv_json(sock: socket.socket) -> dict:
    """
    Receive a length-prefixed JSON object from the socket.
    """
    raw_len = recv_exact(sock, 4)
    msg_len = struct.unpack("!I", raw_len)[0]

    payload = recv_exact(sock, msg_len)
    return json.loads(payload.decode('utf-8'))

def make_cookie():
    """
    Generate a random 37-byte cookie for iperf3 authentication.
    """
    # Generate random bytes
    random_bytes = bytearray(os.urandom(COOKIE_SIZE))
    
    # Map each byte (except last) into base32 character set
    for i in range(COOKIE_SIZE - 1):
        random_bytes[i] = RNDCHARS[random_bytes[i] % len(RNDCHARS)]

    # Last byte is null terminator
    random_bytes[COOKIE_SIZE - 1] = 0
    return bytes(random_bytes)

# Control Class
class ControlConnection:
    """
    Handles the iperf3 control channel:
    - Connect
    - Parameter negotiation
    - Control message exchange
    - Data connection and throughput measurement
    """ 

    def __init__(self, host: str, port: int = 5201, timeout: float = 20.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.data_sock: Optional[socket.socket] = None
        self.test_params: Optional[dict] = None
        self.cookie = make_cookie()

    def expect(self, expected_byte: int) -> None:
        """
        Helper method to read a single byte and check if it matches expected_byte.
        Raises RuntimeError if it doesn't match or if there's a receive error.
        """
        try:
            response = recv_exact(self.sock, 1)
        except Exception as e:
            print("expect: Error receiving byte from server:", repr(e))
            raise RuntimeError("Failed to receive expected byte from server") from e
        
        if response[0] != expected_byte:
            raise RuntimeError(f"Unexpected byte from server: {response[0]}, expected {expected_byte}")

    def connect(self) -> None:
        """
        Establish a TCP connection to the iperf3 server.
        """
        self.sock = socket.create_connection(
            (self.host, self.port), 
            timeout=self.timeout
        )

        # Disable Nagle's algorithm for low-latency control messages
        self.sock.setsockopt(
            socket.IPPROTO_TCP, 
            socket.TCP_NODELAY, 
            1
        )

        self.sock.sendall(self.cookie)

    def negotiate(self, duration: int = 60, block_size: int = 131072) -> dict:
        """
        Perform iperf3 parameter negotiation.
        Returns server response JSON.
        """
        
        if self.sock is None:
            raise RuntimeError("Control socket not connected")
        
        # Read initial server greeting
        self.expect(PARAM_EXCHANGE)  # Expect "PARAM_EXCHANGE" message from server
        
        # iperf3 client parameters matching the spec
        params = {
            "tcp": True,
            "omit": 0,
            "time": duration,
            "num": 0,
            "blockcount": 0,
            "parallel": 1,
            "len": block_size,
            "pacing_timer": 1000,
            "client_version": "3.20"
        }

        # Read server "Create streams" message before creating data connection
        send_json(self.sock, params)
        self.expect(CREATE_STREAMS)

    def open_data_connection(self, server_port: Optional[int] = None) -> None:
        """
        Open a separate data connection to the server.
        If server_port is None, uses the control port + 1 (iperf3 default).
        """
        if self.sock is None:
            raise RuntimeError("Control socket not connected")
        
        if server_port is None:
            server_port = self.port
        
        self.data_sock = socket.create_connection(
            (self.host, server_port),
            timeout=self.timeout
        )
        self.data_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.data_sock.sendall(self.cookie)  # Send cookie on data channel to indicate data connection is ready

        self.expect(TEST_START)

        self.expect(TEST_RUNNING)

    def send_data(
        self,
        duration: float,
        block_size: int = 131072,
        log_filename: Optional[str] = "TEST.csv",
        log_format: str = "csv",
    ) -> dict:
        """
        Send data continuously for the specified duration.

        Every 200 ms the TCP_INFO struct is sampled and a set of statistics is
        recorded along with a timestamp and interval goodput.  If *log_filename*
        is provided the measurements are written to that file in either CSV or
        JSON format (controlled by *log_format*).

        Returns a dict with bytes_sent, duration_actual, throughput_mbps, and
        an "intervals" list containing the recorded samples.
        """
        if self.data_sock is None:
            raise RuntimeError("Data connection not open")

        data_buffer = os.urandom(block_size)
        bytes_sent = 0
        start_time = time.time()
        check_now = start_time + 0.2  # Check every 200 ms
        last_check = start_time
        last_bytes_acked = 0
        intervals: list[dict] = []
        TCP_INFO = socket.TCP_INFO

        # helper to decode the TCP_INFO struct and pull fields we care about
        def parse_tcp_info(buf: bytes) -> dict:
            retransmits = struct.unpack('B', buf[2:3])[0]
            lost = struct.unpack('I', buf[32:36])[0]
            delivered = struct.unpack('I', buf[192:196])[0]
            bytes_acked = struct.unpack('Q', buf[120:128])[0]
            retrans = struct.unpack('I', buf[100:104])[0]
            rtt = struct.unpack('I', buf[68:72])[0]
            snd_cwnd = struct.unpack('I', buf[80:84])[0]
            rttvar = struct.unpack('I', buf[72:76])[0]
            pacing_rate = struct.unpack('Q', buf[104:112])[0]
            bytes_sent = struct.unpack('Q', buf[200:208])[0]

            return {
                'retransmits': retransmits,
                'lost': lost,
                'delivered': delivered,
                'bytes_acked': bytes_acked,
                'retrans': retrans,
                'rtt_ms': rtt / 1000.0,  # Convert microseconds to milliseconds
                'snd_cwnd': snd_cwnd,
                'rttvar_ms': rttvar / 1000.0,  # Convert microseconds to milliseconds
                'pacing_rate_bps': pacing_rate,
                'bytes_sent': bytes_sent,
            }

        try:
            while True:
                now = time.time()
                elapsed = now - start_time
                if elapsed >= duration:
                    break

                if now >= check_now:
                    buf = self.data_sock.getsockopt(socket.IPPROTO_TCP, TCP_INFO, 232)
                    tcp_stats = parse_tcp_info(buf)

                    interval = now - last_check
                    # goodput is based on bytes actually acknowledged by the peer
                    delta_acked = tcp_stats['bytes_acked'] - last_bytes_acked
                    goodput_bps = (delta_acked * 8) / (interval) if interval > 0 else 0

                    last_check = now
                    last_bytes_acked = tcp_stats['bytes_acked']
                    check_now += 0.2  # schedule next check

                    stats = {
                        'timestamp': now - start_time,
                        'interval_s': interval,
                        'bytes_sent': bytes_sent,
                        'goodput_bps': goodput_bps,
                        **tcp_stats,
                    }
                    intervals.append(stats)

                try:
                    sent = self.data_sock.send(data_buffer)
                    if sent == 0:
                        break
                    bytes_sent += sent
                except (socket.timeout, BrokenPipeError, ConnectionResetError):
                    print("Data connection lost during send")
                    break
        except Exception as e:
            print("Error during data send:", repr(e))
            pass  # ignore errors during shutdown

        actual_duration = time.time() - start_time
        throughput_mbps = (bytes_sent * 8) / (actual_duration * 1_000_000) if actual_duration > 0 else 0

        # persist the intervals if requested
        if log_filename and intervals:
            def dump():
                if log_format.lower() == 'json':
                    with open(log_filename, 'w') as f:
                        json.dump(intervals, f, indent=2)
                else:
                    # CSV
                    keys = list(intervals[0].keys())
                    with open(log_filename, 'w') as f:
                        f.write(','.join(keys) + '\n')
                        for entry in intervals:
                            f.write(','.join(str(entry[k]) for k in keys) + '\n')
            try:
                dump()
            except Exception:
                pass

        self.sock.sendall(TEST_END)

        if self.data_sock:
            try:
                self.data_sock.close()
            except Exception:
                pass
            self.data_sock = None

        return {
            'bytes_sent': bytes_sent,
            'duration': actual_duration,
            'throughput_mbps': throughput_mbps,
            'intervals': intervals,
        }

    def send_control_message(self, obj: dict) -> None:
        """
        Send arbitrary control JSON (used for termination)
        """
        if self.sock is None:
            raise RuntimeError("Control socket not connected")
        send_json(self.sock, obj)

    def receive_control_message(self) -> dict:
        """
        Receive arbitrary control JSON.
        """
        if self.sock is None:
            raise RuntimeError("Control socket not connected")
        return recv_json(self.sock)
    
    def close(self) -> None:
        """
        Close both control and data sockets.
        """
        if self.data_sock:
            try:
                self.data_sock.close()
            except Exception:
                pass
            self.data_sock = None
        
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def run_test(self, duration: int = 60, block_size: int = 131072, log_filename: str = "TEST.csv", log_format: str = "csv") -> Optional[dict]:
        """
        Convenience method to run the full test sequence: negotiate, open data connection, send data.
        Returns result dict or None if failed.
        """
        try:
            self.connect()
        
            self.negotiate(duration=duration)
            print("Negotiation succeeded")

            cpu_user_start = os.times().user
            cpu_system_start = os.times().system
  
            self.open_data_connection()
            print("run_test: Data connection opened")
            result = self.send_data(duration=duration, log_filename=log_filename, log_format=log_format)
            print(f"Data transfer complete: {result['throughput_mbps']:.2f} Mbps")
        
            cpu_user_end = os.times().user
            cpu_system_end = os.times().system

            self.expect(EXCHANGE_RESULTS)
            # Use util produced by send_data if available, otherwise send minimal empty util
            util = {
                "cpu_util_total": cpu_user_end - cpu_user_start + cpu_system_end - cpu_system_start,
                "cpu_util_user": cpu_user_end - cpu_user_start,
                "cpu_util_system": cpu_system_end - cpu_system_start,
                "sender_has_retransmits": 0,
                "streams": [
                    {
                        "id": 1,
                        "bytes": (result["bytes_sent"] if result else 0),
                        "retransmits": -1,
                        "jitter": 0,
                        "errors": 0,
                        "omitted_errors": 0,
                        "packets": 0,
                        "omitted_packets": 0,
                        "start_time": 0,
                        "end_time": (result["duration"] if result else 0),
                    }
                ]
            }
            # print("Sending results to server:", util)
            send_json(self.sock, util)
        
            results = recv_json(self.sock) # Expect server to respond with results JSON
            # print("Received results from server:", results)
            results["throughput_mbps"] = result["throughput_mbps"] if result else 0
            results["bytes_sent"] = result["bytes_sent"] if result else 0

            self.expect(DISPLAY_RESULTS)
            self.sock.sendall(IPERF_DONE)  # Send IPERF_DONE message to server

            return results
        finally:
            self.close()