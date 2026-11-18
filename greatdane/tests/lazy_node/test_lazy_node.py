#!/usr/bin/env python3
"""Local, no-network tests for Dane lazy-node loading / TLSA policy.

Binds 127.0.0.1 only. Uses synthetic names (lazytest-*.pepe), never real
DogeNet/PepeNet names, seeds, or nodes. No mach build.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_node import (
    FakeNode,
    build_dns_query,
    dns_rcode,
    parse_ede,
)
from lazy_policy import (
    DEFAULT_LAZY_TIMEOUT_SEC,
    FAIL,
    LAZY_LOADING_EDE,
    LAZY_NODE_CLI_FLAG,
    LAZY_NODE_ENV_NAME,
    LOADING_TIMEOUT,
    MATCH,
    RCODE_NXDOMAIN,
    RCODE_SERVFAIL,
    TLSA_STATUS_LOADING,
    UNOWNED,
    classify_chain_failure,
    is_lazy_loading_dns,
    is_lazy_loading_status,
    wait_for_tlsa,
    _spki_sha256_hex,
)

# Synthetic SPKI bytes — not a key file, just material for a SHA-256 compare.
LEAF_SPKI = b"lazy-node-test-spki-v1"
GOOD_HASH = _spki_sha256_hex(LEAF_SPKI)
BAD_HASH = "ab" * 32

OK_TLSA = {
    "status": "ok",
    "usage": "3",
    "selector": "1",
    "mtype": "1",
    "data": GOOD_HASH,
}
BAD_TLSA = dict(OK_TLSA, data=BAD_HASH)
LOADING_BODY = {"status": TLSA_STATUS_LOADING}


def http_fetch(port, host, timeout):
    url = f"http://127.0.0.1:{port}/gd/tlsa?host={host}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return ("ok", json.loads(resp.read().decode("utf-8")))
    except socket.timeout:
        return ("timeout", None)
    except TimeoutError:
        return ("timeout", None)
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return ("timeout", None)
        if isinstance(reason, ConnectionRefusedError):
            return ("connect_fail", None)
        if reason is not None and "timed out" in str(reason).lower():
            return ("timeout", None)
        return ("connect_fail", None)


def dns_query(port, name, timeout=5.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(timeout)
    try:
        sock.sendto(build_dns_query(name), ("127.0.0.1", port))
        resp, _ = sock.recvfrom(2048)
        return dns_rcode(resp), parse_ede(resp)
    finally:
        sock.close()


class PolicyConstantsTests(unittest.TestCase):
    def test_placeholders_are_marked(self):
        self.assertEqual(LAZY_NODE_CLI_FLAG, "--lazy")
        self.assertEqual(LAZY_NODE_ENV_NAME, "GREATDANE_NODE_LAZY")
        # 0 means not yet assigned: must not treat any EDE as loading.
        self.assertEqual(LAZY_LOADING_EDE, 0)
        self.assertEqual(DEFAULT_LAZY_TIMEOUT_SEC, 10)

    def test_http_status_loading_is_loading(self):
        self.assertTrue(is_lazy_loading_status({"status": "loading"}))

    def test_plain_servfail_is_not_loading_while_ede_is_placeholder(self):
        self.assertFalse(is_lazy_loading_status({"status": "error", "rcode": 2, "ede": 0}))
        self.assertFalse(is_lazy_loading_status({"rcode": "SERVFAIL", "ede": 0}))
        self.assertFalse(is_lazy_loading_dns(RCODE_SERVFAIL, 0))
        self.assertFalse(is_lazy_loading_dns(RCODE_SERVFAIL, None))

    def test_servfail_plus_assigned_ede_is_loading(self):
        # Once TODO-KEEPER-EDE is replaced, this is the dnsd contract.
        ede = 99
        self.assertTrue(is_lazy_loading_status(
            {"rcode": "SERVFAIL", "ede": ede}, loading_ede=ede))
        self.assertTrue(is_lazy_loading_dns(RCODE_SERVFAIL, ede, loading_ede=ede))
        self.assertFalse(is_lazy_loading_dns(RCODE_SERVFAIL, 7, loading_ede=ede))
        self.assertFalse(is_lazy_loading_dns(RCODE_NXDOMAIN, ede, loading_ede=ede))

    def test_classify_loading_is_not_a_security_error(self):
        self.assertEqual(classify_chain_failure("loading"), "GD_ZONE_LOADING")
        self.assertEqual(
            classify_chain_failure("loading", tls_fail=True),
            "GD_ZONE_LOADING",
        )
        self.assertEqual(classify_chain_failure("unowned"), "GD_NAME_UNOWNED")
        self.assertEqual(classify_chain_failure("ok", tls_fail=True), "GD_TLS_UNTRUSTED")
        self.assertEqual(classify_chain_failure(""), "GD_TLS_UNTRUSTED")


class FakeNodeTests(unittest.TestCase):
    def setUp(self):
        assigned_ede = 99  # stand-in for TODO-KEEPER-EDE in the DNS cases
        self.assigned_ede = assigned_ede
        records = {
            "lazytest-warm.pepe": {
                "delay": 0,
                "http": OK_TLSA,
                "dns_rcode": 0,
            },
            "lazytest-cold.pepe": {
                "delay": 3.0,
                "http": OK_TLSA,
                "dns_rcode": 0,
            },
            "lazytest-slow.pepe": {
                "delay": 0,
                "http": LOADING_BODY,
                "dns_rcode": RCODE_SERVFAIL,
                "dns_ede": assigned_ede,
            },
            "lazytest-nx.pepe": {
                "delay": 0,
                "http": {"status": "unowned"},
                "dns_rcode": RCODE_NXDOMAIN,
            },
            "lazytest-bad.pepe": {
                "delay": 0,
                "http": BAD_TLSA,
                "dns_rcode": 0,
            },
            "lazytest-servfail.pepe": {
                "delay": 0,
                "http": {"status": "error", "rcode": "SERVFAIL"},
                "dns_rcode": RCODE_SERVFAIL,
                # no EDE: existing fail-closed path
            },
        }
        names = [
            "lazytest-warm",
            "lazytest-cold",
            "lazytest-slow",
            "lazytest-nx",
            "lazytest-bad",
            "lazytest-other",
        ]
        self.node = FakeNode(records, names=names).start()

    def tearDown(self):
        self.node.stop()

    def _wait(self, host, timeout_sec, lazy=True, loading_ede=LAZY_LOADING_EDE):
        # Each HTTP attempt is allowed the remaining budget (mirrors C++).
        def fetch():
            # Use a slightly longer socket timeout than the policy budget
            # so a delayed-but-successful answer (cold: 3s) is received.
            return http_fetch(self.node.http_port, host, timeout=timeout_sec + 1)

        t0 = time.monotonic()
        verdict = wait_for_tlsa(
            fetch,
            LEAF_SPKI,
            lazy=lazy,
            timeout_sec=timeout_sec,
            loading_ede=loading_ede,
        )
        return verdict, time.monotonic() - t0

    def test_warm_immediate_match(self):
        verdict, elapsed = self._wait("lazytest-warm.pepe", timeout_sec=10)
        self.assertEqual(verdict, MATCH)
        self.assertLess(elapsed, 1.5)

    def test_cold_waits_and_tlsa_passes(self):
        verdict, elapsed = self._wait("lazytest-cold.pepe", timeout_sec=10)
        self.assertEqual(verdict, MATCH)
        self.assertGreaterEqual(elapsed, 2.8)
        self.assertLess(elapsed, 8.0)

    def test_cold_too_slow_is_retryable_not_tlsa_failure(self):
        # Node keeps answering "loading"; budget is short so the test stays cheap.
        verdict, elapsed = self._wait("lazytest-slow.pepe", timeout_sec=1)
        self.assertEqual(verdict, LOADING_TIMEOUT)
        self.assertNotEqual(verdict, FAIL)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertEqual(classify_chain_failure("loading"), "GD_ZONE_LOADING")
        # Raw dnsd contract (with an assigned EDE stand-in): SERVFAIL+EDE.
        rcode, ede = dns_query(self.node.dns_port, "lazytest-slow.pepe", timeout=2)
        self.assertEqual(rcode, RCODE_SERVFAIL)
        self.assertEqual(ede, self.assigned_ede)
        self.assertTrue(is_lazy_loading_dns(rcode, ede, loading_ede=self.assigned_ede))

    def test_real_nxdomain_is_not_found(self):
        verdict, elapsed = self._wait("lazytest-nx.pepe", timeout_sec=5)
        self.assertEqual(verdict, UNOWNED)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(classify_chain_failure("unowned"), "GD_NAME_UNOWNED")
        rcode, ede = dns_query(self.node.dns_port, "lazytest-nx.pepe")
        self.assertEqual(rcode, RCODE_NXDOMAIN)
        self.assertIsNone(ede)
        self.assertFalse(is_lazy_loading_dns(rcode, ede, loading_ede=self.assigned_ede))

    def test_bad_tlsa_is_rejected(self):
        verdict, elapsed = self._wait("lazytest-bad.pepe", timeout_sec=5)
        self.assertEqual(verdict, FAIL)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(classify_chain_failure("ok", tls_fail=True), "GD_TLS_UNTRUSTED")

    def test_plain_servfail_without_ede_is_existing_fail_path(self):
        verdict, _ = self._wait("lazytest-servfail.pepe", timeout_sec=5)
        self.assertEqual(verdict, FAIL)
        self.assertNotEqual(verdict, LOADING_TIMEOUT)
        rcode, ede = dns_query(self.node.dns_port, "lazytest-servfail.pepe")
        self.assertEqual(rcode, RCODE_SERVFAIL)
        self.assertIsNone(ede)
        self.assertFalse(is_lazy_loading_dns(rcode, ede, loading_ede=self.assigned_ede))
        # HTTP body has SERVFAIL and no loading status / no matching EDE.
        kind, body = http_fetch(self.node.http_port, "lazytest-servfail.pepe", timeout=2)
        self.assertEqual(kind, "ok")
        self.assertFalse(is_lazy_loading_status(body))
        self.assertFalse(is_lazy_loading_status(body, loading_ede=self.assigned_ede))

    def test_names_work_while_a_zone_is_still_loading(self):
        # Namespace-only sync keeps the full name list; suggestions unchanged.
        url = f"http://127.0.0.1:{self.node.http_port}/gd/names?prefix=lazytest-&limit=10"
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertIn("lazytest-slow", data["names"])
        self.assertIn("lazytest-warm", data["names"])
        self.assertIn("lazytest-other", data["names"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
