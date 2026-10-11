"""A2S_INFO probe: healthy means CS2 answers queries, not merely a running process."""
import json
import socket
from pathlib import Path

port = json.loads(Path('/config/server.json').read_text())['port']
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
    sock.settimeout(3)
    query = b'\xff\xff\xff\xffTSource Engine Query\x00'
    sock.sendto(query, ('127.0.0.1', port))
    reply, address = sock.recvfrom(65535)
    if reply[:5] == b'\xff\xff\xff\xffA':
        sock.sendto(query + reply[5:9], address)
        reply, _ = sock.recvfrom(65535)
    if reply[:5] != b'\xff\xff\xff\xffI':
        raise SystemExit(1)
