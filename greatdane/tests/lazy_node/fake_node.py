"""Localhost-only fake greatdane-node / dnsd for lazy-node tests.

No real DogeNet/PepeNet names, seeds, or nodes. Binds 127.0.0.1 only.
Answers /gd/tlsa, /gd/names, and a tiny DNS listener after a per-name delay.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from lazy_policy import (
    LAZY_LOADING_EDE,
    RCODE_NOERROR,
    RCODE_NXDOMAIN,
    RCODE_SERVFAIL,
    TLSA_STATUS_LOADING,
)

# EDNS option code for Extended DNS Error (RFC 8914).
EDNS_OPTION_EDE = 15


def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.rstrip(".").split("."):
        raw = label.encode("ascii")
        if not raw or len(raw) > 63:
            raise ValueError(f"bad label in {name!r}")
        out.append(len(raw))
        out.extend(raw)
    out.append(0)
    return bytes(out)


def build_dns_response(query: bytes, rcode: int, ede=None) -> bytes:
    """Minimal DNS response echoing the query question, with optional EDE."""
    if len(query) < 12:
        raise ValueError("short DNS query")
    tid, flags, qdcount, *_ = struct.unpack("!HHHHHH", query[:12])
    # Build a response: copy id, set QR=1, rcode, RA=1, keep question.
    rflags = 0x8000 | 0x0080 | (rcode & 0xF)  # QR + RA + rcode
    # Keep the question section as-is if we can find it; else empty.
    # Find end of first question: after QNAME + QTYPE + QCLASS.
    i = 12
    try:
        while i < len(query) and query[i] != 0:
            i += 1 + query[i]
        i += 1 + 4  # root + type/class
        question = query[12:i] if qdcount else b""
        qdc = 1 if question else 0
    except Exception:
        question, qdc = b"", 0

    additional = b""
    arcount = 0
    if ede is not None:
        # RFC 6891 OPT record + RFC 8914 EDE option (INFO-CODE only).
        # NAME=root, TYPE=OPT (41), CLASS=udp payload, TTL=0, RDATA=option.
        option_data = struct.pack("!H", int(ede))  # INFO-CODE, empty EXTRA-TEXT
        option = struct.pack("!HH", EDNS_OPTION_EDE, len(option_data)) + option_data
        additional = b"\x00" + struct.pack("!HHIH", 41, 1232, 0, len(option)) + option
        arcount = 1

    header = struct.pack("!HHHHHH", tid, rflags, qdc, 0, 0, arcount)
    return header + question + additional


def parse_qname(query: bytes) -> str:
    if len(query) < 13:
        return ""
    labels = []
    i = 12
    while i < len(query) and query[i] != 0:
        n = query[i]
        if i + 1 + n > len(query):
            return ""
        labels.append(query[i + 1 : i + 1 + n].decode("ascii", "replace"))
        i += 1 + n
    return ".".join(labels).lower()


def parse_ede(resp: bytes):
    """Return the first EDE INFO-CODE in an OPT record, or None."""
    if len(resp) < 12:
        return None
    *_, arcount = struct.unpack("!HHHHHH", resp[:12])
    if arcount < 1:
        return None
    # Skip questions, no answers/authority in our stub.
    _, flags, qdcount, ancount, nscount, _ = struct.unpack("!HHHHHH", resp[:12])
    i = 12
    for _ in range(qdcount):
        while i < len(resp) and resp[i] != 0:
            i += 1 + resp[i]
        i += 1 + 4
    # No AN/NS in our replies; additional starts here.
    if i >= len(resp) or resp[i] != 0:
        return None
    i += 1
    if i + 8 > len(resp):
        return None
    typ, _cls, _ttl, rdlen = struct.unpack("!HHIH", resp[i : i + 10])
    i += 10
    if typ != 41:
        return None
    end = i + rdlen
    while i + 4 <= end:
        opt, optlen = struct.unpack("!HH", resp[i : i + 4])
        i += 4
        if opt == EDNS_OPTION_EDE and optlen >= 2:
            return struct.unpack("!H", resp[i : i + 2])[0]
        i += optlen
    return None


def dns_rcode(resp: bytes) -> int:
    if len(resp) < 12:
        return -1
    flags = struct.unpack("!HHHHHH", resp[:12])[1]
    return flags & 0xF


class FakeNode:
    """Configurable per-host delayed answers for /gd/tlsa, /gd/names, and DNS."""

    def __init__(self, records, names=None):
        # records: host -> dict with keys:
        #   delay (sec), http (dict body or callable),
        #   dns_rcode, dns_ede (optional)
        self.records = {k.lower().rstrip("."): v for k, v in records.items()}
        self.names = list(names or [])
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.dns.bind(("127.0.0.1", 0))
        self._stop = threading.Event()
        self._threads = []
        self.http_port = self.http.server_address[1]
        self.dns_port = self.dns.getsockname()[1]

    def _lookup(self, host):
        return self.records.get(host.lower().rstrip("."))

    def _handler(self):
        node = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return  # keep tests quiet; no hostnames to the console needed

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/gd/tlsa":
                    host = parse_qs(u.query).get("host", [""])[0]
                    rec = node._lookup(host)
                    if rec is None:
                        body = {"status": "unowned"}
                        delay = 0
                    else:
                        delay = float(rec.get("delay", 0))
                        http = rec.get("http")
                        body = http() if callable(http) else dict(http)
                    if delay:
                        time.sleep(delay)
                    raw = json.dumps(body).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if u.path == "/gd/names":
                    # Namespace-only: the full name list is available even
                    # when individual zones are still being fetched.
                    qs = parse_qs(u.query)
                    prefix = (qs.get("prefix", [""])[0] or "").lower()
                    try:
                        limit = int(qs.get("limit", ["5"])[0])
                    except ValueError:
                        limit = 5
                    names = [n for n in node.names if n.startswith(prefix)][:limit]
                    raw = json.dumps({"status": "ok", "names": names}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self.send_error(404)

        return Handler

    def _dns_loop(self):
        self.dns.settimeout(0.2)
        while not self._stop.is_set():
            try:
                data, addr = self.dns.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            qname = parse_qname(data)
            rec = self._lookup(qname)
            if rec is None:
                rcode, ede, delay = RCODE_NXDOMAIN, None, 0
            else:
                delay = float(rec.get("delay", 0))
                rcode = rec.get("dns_rcode", RCODE_NOERROR)
                ede = rec.get("dns_ede")
            if delay:
                time.sleep(delay)
            try:
                self.dns.sendto(build_dns_response(data, rcode, ede), addr)
            except OSError:
                break

    def start(self):
        t_http = threading.Thread(target=self.http.serve_forever, daemon=True)
        t_dns = threading.Thread(target=self._dns_loop, daemon=True)
        t_http.start()
        t_dns.start()
        self._threads = [t_http, t_dns]
        return self

    def stop(self):
        self._stop.set()
        try:
            self.http.shutdown()
        except Exception:
            pass
        try:
            self.http.server_close()
        except Exception:
            pass
        try:
            self.dns.close()
        except Exception:
            pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def build_dns_query(name: str, qtype: int = 1) -> bytes:
    header = struct.pack("!HHHHHH", 0x4242, 0x0100, 1, 0, 0, 0)
    return header + _encode_name(name) + struct.pack("!HH", qtype, 1)
