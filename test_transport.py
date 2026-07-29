"""Smoke test for the TCP loopback transport layer.

Tests the server listener + client connection without Blender.
Run: python test_transport.py
"""
import json
import socket
import struct
import threading
import time
import sys
import os

# Add src to path so we can import the server module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from blender_weave.server import BlenderConnection, _pid_alive, SERVERS_DIR


def send_framed(sock, data: dict):
    payload = json.dumps(data).encode('utf-8')
    sock.sendall(struct.pack('>I', len(payload)) + payload)


def recv_framed(sock) -> dict:
    header = b''
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            raise ConnectionError("closed")
        header += chunk
    msg_len = struct.unpack('>I', header)[0]
    buf = b''
    while len(buf) < msg_len:
        chunk = sock.recv(msg_len - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return json.loads(buf.decode('utf-8'))


def test_listener_starts_and_metadata():
    """Server starts, binds a port, writes metadata JSON."""
    conn = BlenderConnection()
    conn.start_listener()
    try:
        assert conn.port is not None, "Port not assigned"
        assert conn.port > 0, f"Invalid port: {conn.port}"
        assert conn.meta_path.exists(), "Metadata file not written"

        meta = json.loads(conn.meta_path.read_text())
        assert meta["port"] == conn.port
        assert meta["pid"] == os.getpid()
        assert "started" in meta
        print(f"  OK: listener on 127.0.0.1:{conn.port}, meta written")
    finally:
        conn.stop_listener()

    assert not conn.meta_path.exists(), "Metadata not cleaned up"
    print("  OK: metadata cleaned up after stop")


def test_client_connect_and_roundtrip():
    """Fake client connects, sends a message, gets a response."""
    conn = BlenderConnection()
    conn.start_listener()
    try:
        # Connect a fake client
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5.0)
        client.connect(('127.0.0.1', conn.port))
        time.sleep(0.2)  # let accept loop pick it up

        assert conn.connect(), "Server didn't register client"
        print(f"  OK: client connected to port {conn.port}")

        # Server sends a command to the client
        command = {"type": "test_ping", "params": {"msg": "hello"}}
        response_holder = [None]
        error_holder = [None]

        def server_send():
            try:
                response_holder[0] = conn._send_and_receive(command)
            except Exception as e:
                error_holder[0] = e

        t = threading.Thread(target=server_send)
        t.start()

        # Client receives and responds
        received = recv_framed(client)
        assert received["type"] == "test_ping", f"Wrong type: {received}"
        assert received["params"]["msg"] == "hello"
        print(f"  OK: client received command: {received['type']}")

        response = {"status": "ok", "result": {"pong": True}}
        send_framed(client, response)

        t.join(timeout=5.0)
        assert error_holder[0] is None, f"Server error: {error_holder[0]}"
        assert response_holder[0] == {"pong": True}
        print("  OK: round-trip message exchange works")

        client.close()
    finally:
        conn.stop_listener()


def test_client_reconnect():
    """Second client connection replaces the first."""
    conn = BlenderConnection()
    conn.start_listener()
    try:
        c1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c1.connect(('127.0.0.1', conn.port))
        time.sleep(0.2)
        assert conn.connect()

        c2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c2.connect(('127.0.0.1', conn.port))
        time.sleep(0.2)
        assert conn.connect()
        print("  OK: second client replaced first")

        c1.close()
        c2.close()
    finally:
        conn.stop_listener()


def test_pid_alive():
    """_pid_alive works for current process and fake PID."""
    assert _pid_alive(os.getpid()), "Current process should be alive"
    assert not _pid_alive(99999999), "Fake PID should not be alive"
    print("  OK: _pid_alive works")


def test_stale_cleanup():
    """Stale metadata from dead PIDs gets cleaned up."""
    SERVERS_DIR.mkdir(parents=True, exist_ok=True)
    stale_meta = SERVERS_DIR / "stale_test_999.json"
    stale_meta.write_text(json.dumps({
        "pid": 99999999,
        "port": 11111,
        "cwd": "/tmp",
        "started": "2020-01-01T00:00:00+00:00",
    }))
    assert stale_meta.exists()

    BlenderConnection._cleanup_stale_servers()
    assert not stale_meta.exists(), "Stale metadata not cleaned up"
    print("  OK: stale server metadata cleaned up")


def test_no_af_unix_references():
    """Verify no AF_UNIX references remain in source files."""
    server_py = os.path.join(os.path.dirname(__file__), 'src', 'blender_weave', 'server.py')
    bridge_py = os.path.join(os.path.dirname(__file__), 'addon', 'server_bridge.py')
    for path in [server_py, bridge_py]:
        # encoding is explicit: on Windows the default locale codec (cp1252)
        # cannot decode the UTF-8 punctuation in these sources.
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                assert 'AF_UNIX' not in line, f"AF_UNIX at {path}:{i}"
                # Check for .sock file paths (not .socket attribute)
                if '.sock"' in line or ".sock'" in line or '.sock)' in line:
                    raise AssertionError(f".sock file ref at {path}:{i}")
    print("  OK: no AF_UNIX or .sock file references in source")


if __name__ == '__main__':
    tests = [
        test_pid_alive,
        test_stale_cleanup,
        test_listener_starts_and_metadata,
        test_client_connect_and_roundtrip,
        test_client_reconnect,
        test_no_af_unix_references,
    ]
    passed = 0
    failed = 0
    for test in tests:
        print(f"\n{test.__name__}:")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
