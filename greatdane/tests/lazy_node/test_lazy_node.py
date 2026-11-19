#!/usr/bin/env python3
"""Local, no-network tests for Dane lazy-node loading / TLSA policy.

Binds 127.0.0.1 only. Uses synthetic names (lazytest-*.pepe), never real
DogeNet/PepeNet names, seeds, or nodes. No mach build.
"""

from __future__ import annotations

import http.client
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
    LAZY_FETCH_FAILED_EDE,
    LAZY_LOADING_EDE,
    LAZY_CACHE_DIR_CLI_FLAG,
    LAZY_CACHE_DIR_ENV_NAME,
    LAZY_NODE_CLI_FLAG,
    LAZY_NODE_ENV_NAME,
    NO_TLSA,
    LOADING_TIMEOUT,
    MATCH,
    RCODE_NXDOMAIN,
    RCODE_SERVFAIL,
    TLSA_STATUS_LOADING,
    UNOWNED,
    classify_chain_failure,
    is_lazy_loading_dns,
    is_lazy_loading_status,
    is_proxy_loading,
    loading_retry_sec,
    lazy_namespace_synced,
    lazy_node_args,
    lazy_node_env,
    lazy_retry_ms,
    namespace_sync_cell,
    peer_best_cell,
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
LOADING_14 = {
    "status": "loading",
    "rcode": "SERVFAIL",
    "ede": LAZY_LOADING_EDE,
    "phase": "fetching",
    "retry_ms": 1000,
}
LOADING_22 = {
    "status": "loading",
    "rcode": "SERVFAIL",
    "ede": LAZY_FETCH_FAILED_EDE,
    "phase": "fetch_failed",
    "retry_ms": 1000,
}


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


def proxy_connect(port, host, timeout=5.0):
    """Issue a CONNECT like the browser's PAC proxy path."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("CONNECT", f"{host}:443")
        resp = conn.getresponse()
        headers = {k: v for k, v in resp.getheaders()}
        return resp.status, headers
    finally:
        conn.close()


class PolicyConstantsTests(unittest.TestCase):
    def test_confirmed_constants(self):
        self.assertEqual(LAZY_NODE_CLI_FLAG, "--lazy")
        self.assertEqual(LAZY_NODE_ENV_NAME, "GREATDANE_NODE_LAZY")
        self.assertEqual(LAZY_CACHE_DIR_CLI_FLAG, "--lazy-cache-dir")
        self.assertEqual(LAZY_CACHE_DIR_ENV_NAME, "GREATDANE_NODE_LAZY_CACHE_DIR")
        self.assertEqual(LAZY_LOADING_EDE, 14)
        self.assertEqual(LAZY_FETCH_FAILED_EDE, 22)
        self.assertEqual(DEFAULT_LAZY_TIMEOUT_SEC, 10)

    def test_lazy_launch_passes_cache_dir_only_when_enabled(self):
        data = "/tmp/greatdane-test-data"
        self.assertEqual(
            lazy_node_args(data, enabled=True),
            ["--lazy", "--lazy-cache-dir", data],
        )
        self.assertEqual(
            lazy_node_env(data, enabled=True),
            {"GREATDANE_NODE_LAZY": "1", "GREATDANE_NODE_LAZY_CACHE_DIR": data},
        )
        self.assertEqual(lazy_node_args(data, enabled=False), [])
        self.assertEqual(lazy_node_env(data, enabled=False), {})
        # Other tunables stay at node defaults: not passed.
        for token in lazy_node_args(data):
            self.assertNotIn("wait-ms", token)
            self.assertNotIn("max-names", token)
            self.assertNotIn("max-mb", token)

    def test_namespace_synced_is_followed_live_not_latched(self):
        # Offline fixture: height 1000, activation 1130000, no peers.
        # The node says synced; Dane must not re-apply the activation gate.
        offline = {
            "height": 1000,
            "activation": 1_130_000,
            "peer_height": 0,
            "passes": 1,
            "namespace_synced": True,
            "namespace_sync_basis": "offline",
            "best_known_height": 0,
        }
        self.assertTrue(lazy_namespace_synced(offline))
        self.assertEqual(namespace_sync_cell(offline, "ready"), "ready (offline)")
        self.assertEqual(peer_best_cell(offline), "0 / 0")

        # A later peer with a higher tip flips the live flag back to false.
        behind = dict(offline, namespace_synced=False, namespace_sync_basis="none",
                      peer_height=5000, best_known_height=5000)
        self.assertFalse(lazy_namespace_synced(behind))
        self.assertEqual(namespace_sync_cell(behind, "syncing"), "syncing (none)")
        self.assertEqual(peer_best_cell(behind), "5000 / 5000")

        # Online at tip.
        peers = dict(offline, namespace_synced=True, namespace_sync_basis="peers",
                     peer_height=1000, best_known_height=1000)
        self.assertTrue(lazy_namespace_synced(peers))
        self.assertEqual(namespace_sync_cell(peers, "ready"), "ready (peers)")

        # Missing flag: height catch-up fallback, never treat height 0 as synced.
        self.assertFalse(lazy_namespace_synced({"height": 0, "peer_height": 0}))
        self.assertTrue(lazy_namespace_synced({"height": 100, "peer_height": 0}))
        self.assertTrue(lazy_namespace_synced({"height": 100, "peer_height": 100}))
        self.assertFalse(lazy_namespace_synced({"height": 100, "peer_height": 200}))
        self.assertEqual(peer_best_cell({}), "- / -")
        self.assertEqual(namespace_sync_cell({}, "ready"), "ready")

    def test_http_status_loading_is_loading(self):
        self.assertTrue(is_lazy_loading_status({"status": "loading"}))
        self.assertTrue(is_lazy_loading_status(LOADING_14))
        self.assertTrue(is_lazy_loading_status(LOADING_22))

    def test_servfail_plus_14_or_22_is_loading(self):
        self.assertTrue(is_lazy_loading_status({"rcode": "SERVFAIL", "ede": 14}))
        self.assertTrue(is_lazy_loading_status({"rcode": 2, "ede": 22}))
        self.assertTrue(is_lazy_loading_dns(RCODE_SERVFAIL, 14))
        self.assertTrue(is_lazy_loading_dns(RCODE_SERVFAIL, 22))

    def test_plain_servfail_without_those_edes_is_not_loading(self):
        self.assertFalse(is_lazy_loading_status({"status": "error", "rcode": 2}))
        self.assertFalse(is_lazy_loading_status({"rcode": "SERVFAIL", "ede": 0}))
        self.assertFalse(is_lazy_loading_status({"rcode": "SERVFAIL", "ede": 7}))
        self.assertFalse(is_lazy_loading_dns(RCODE_SERVFAIL, None))
        self.assertFalse(is_lazy_loading_dns(RCODE_SERVFAIL, 0))
        self.assertFalse(is_lazy_loading_dns(RCODE_NXDOMAIN, 14))

    def test_classify_loading_is_not_a_security_error(self):
        self.assertEqual(classify_chain_failure("loading"), "GD_ZONE_LOADING")
        self.assertEqual(
            classify_chain_failure("loading", tls_fail=True),
            "GD_ZONE_LOADING",
        )
        self.assertEqual(
            classify_chain_failure(None, proxy_loading=True),
            "GD_ZONE_LOADING",
        )
        self.assertEqual(classify_chain_failure("unowned"), "GD_NAME_UNOWNED")
        self.assertEqual(classify_chain_failure("ok", tls_fail=True), "GD_TLS_UNTRUSTED")
        self.assertEqual(classify_chain_failure(""), "GD_TLS_UNTRUSTED")
        # no_tlsa is final only as an explicit node status, never inferred.
        self.assertEqual(classify_chain_failure("no_tlsa"), "GD_NO_TLSA")
        self.assertNotEqual(classify_chain_failure("loading"), "GD_NO_TLSA")
        self.assertNotEqual(classify_chain_failure(None), "GD_NO_TLSA")
        self.assertNotEqual(classify_chain_failure(""), "GD_NO_TLSA")

    def test_retry_ms_clamped_to_budget(self):
        self.assertEqual(lazy_retry_ms({"retry_ms": 1000}, 10_000), 1000)
        self.assertEqual(lazy_retry_ms({"retry_ms": 30_000}, 10_000), 10_000)
        self.assertEqual(lazy_retry_ms({}, 10_000), 1000)
        self.assertEqual(loading_retry_sec(retry_ms=1000), 1)
        self.assertEqual(loading_retry_sec(retry_after=1), 1)
        self.assertEqual(loading_retry_sec(retry_ms=2500), 3)
        self.assertEqual(loading_retry_sec(retry_after=30, cap=10), 10)

    def test_retry_ms_is_honored_in_wait_loop(self):
        sleeps = []
        t = [0.0]

        def clock():
            return t[0]

        def sleep(s):
            sleeps.append(s)
            t[0] += s

        def fetch():
            return ("ok", dict(LOADING_14, retry_ms=250))

        verdict = wait_for_tlsa(
            fetch, LEAF_SPKI, lazy=True, timeout_sec=1, clock=clock, sleep=sleep
        )
        self.assertEqual(verdict, LOADING_TIMEOUT)
        self.assertTrue(sleeps)
        # Every pause should honor 250ms, except a possible leftover sliver.
        self.assertTrue(any(abs(s - 0.250) < 1e-9 for s in sleeps))
        self.assertTrue(all(s <= 0.250 + 1e-9 for s in sleeps))
        self.assertGreaterEqual(sum(sleeps), 0.75)


class FakeNodeTests(unittest.TestCase):
    def setUp(self):
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
                "http": LOADING_14,
                "dns_rcode": RCODE_SERVFAIL,
                "dns_ede": LAZY_LOADING_EDE,
            },
            "lazytest-failfetch.pepe": {
                "delay": 0,
                "http": LOADING_22,
                "dns_rcode": RCODE_SERVFAIL,
                "dns_ede": LAZY_FETCH_FAILED_EDE,
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
            },
        }
        names = [
            "lazytest-warm",
            "lazytest-cold",
            "lazytest-slow",
            "lazytest-failfetch",
            "lazytest-nx",
            "lazytest-bad",
            "lazytest-other",
        ]
        self.node = FakeNode(records, names=names).start()

    def tearDown(self):
        self.node.stop()

    def _wait(self, host, timeout_sec, lazy=True):
        def fetch():
            return http_fetch(self.node.http_port, host, timeout=timeout_sec + 1)

        t0 = time.monotonic()
        verdict = wait_for_tlsa(
            fetch,
            LEAF_SPKI,
            lazy=lazy,
            timeout_sec=timeout_sec,
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

    def test_cold_too_slow_ede14_is_retryable_not_tlsa_failure(self):
        verdict, elapsed = self._wait("lazytest-slow.pepe", timeout_sec=1)
        self.assertEqual(verdict, LOADING_TIMEOUT)
        self.assertNotEqual(verdict, FAIL)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertEqual(classify_chain_failure("loading"), "GD_ZONE_LOADING")
        rcode, ede = dns_query(self.node.dns_port, "lazytest-slow.pepe", timeout=2)
        self.assertEqual(rcode, RCODE_SERVFAIL)
        self.assertEqual(ede, LAZY_LOADING_EDE)
        self.assertTrue(is_lazy_loading_dns(rcode, ede))
        kind, body = http_fetch(self.node.http_port, "lazytest-slow.pepe", timeout=2)
        self.assertEqual(kind, "ok")
        self.assertEqual(body["phase"], "fetching")
        self.assertEqual(body["retry_ms"], 1000)
        self.assertEqual(body["ede"], 14)

    def test_ede22_fetch_failed_is_also_retryable_loading(self):
        verdict, _ = self._wait("lazytest-failfetch.pepe", timeout_sec=1)
        self.assertEqual(verdict, LOADING_TIMEOUT)
        rcode, ede = dns_query(self.node.dns_port, "lazytest-failfetch.pepe", timeout=2)
        self.assertEqual(rcode, RCODE_SERVFAIL)
        self.assertEqual(ede, LAZY_FETCH_FAILED_EDE)
        self.assertTrue(is_lazy_loading_dns(rcode, ede))
        kind, body = http_fetch(self.node.http_port, "lazytest-failfetch.pepe", timeout=2)
        self.assertEqual(body["phase"], "fetch_failed")
        self.assertEqual(body["ede"], 22)

    def test_proxy_connect_503_is_zone_loading(self):
        status, headers = proxy_connect(self.node.http_port, "lazytest-slow.pepe")
        self.assertEqual(status, 503)
        # header names from http.client are whatever the server sent
        self.assertTrue(is_proxy_loading(status, headers))
        norm = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(norm.get("x-greatdane-status"), "loading")
        self.assertEqual(norm.get("retry-after"), "1")
        self.assertEqual(
            classify_chain_failure(None, proxy_loading=True),
            "GD_ZONE_LOADING",
        )
        self.assertEqual(loading_retry_sec(retry_after=int(norm["retry-after"])), 1)
        # A real NXDOMAIN CONNECT is not a loading 503.
        status2, headers2 = proxy_connect(self.node.http_port, "lazytest-nx.pepe")
        self.assertNotEqual(status2, 503)
        self.assertFalse(is_proxy_loading(status2, headers2))

    def test_real_nxdomain_is_not_found(self):
        verdict, elapsed = self._wait("lazytest-nx.pepe", timeout_sec=5)
        self.assertEqual(verdict, UNOWNED)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(classify_chain_failure("unowned"), "GD_NAME_UNOWNED")
        rcode, ede = dns_query(self.node.dns_port, "lazytest-nx.pepe")
        self.assertEqual(rcode, RCODE_NXDOMAIN)
        self.assertIsNone(ede)
        self.assertFalse(is_lazy_loading_dns(rcode, ede))

    def test_bad_tlsa_is_rejected(self):
        verdict, elapsed = self._wait("lazytest-bad.pepe", timeout_sec=5)
        self.assertEqual(verdict, FAIL)
        self.assertLess(elapsed, 1.5)
        self.assertEqual(classify_chain_failure("ok", tls_fail=True), "GD_TLS_UNTRUSTED")

    def test_no_tlsa_is_final_only_when_the_node_says_so(self):
        # Explicit node status is final immediately; do not keep retrying.
        calls = {"n": 0}

        def fetch_final():
            calls["n"] += 1
            return ("ok", {"status": "no_tlsa"})

        self.assertEqual(
            wait_for_tlsa(fetch_final, LEAF_SPKI, lazy=True, timeout_sec=10,
                          sleep=lambda _s: None, clock=lambda: 0.0),
            NO_TLSA,
        )
        self.assertEqual(calls["n"], 1)

        # A loading signal, then the node's no_tlsa: final after the node says so.
        seq = [LOADING_14, {"status": "no_tlsa"}]
        t = [0.0]

        def clock():
            return t[0]

        def sleep(s):
            t[0] += s

        def fetch_then():
            body = seq.pop(0) if seq else {"status": "no_tlsa"}
            return ("ok", body)

        self.assertEqual(
            wait_for_tlsa(fetch_then, LEAF_SPKI, lazy=True, timeout_sec=10,
                          sleep=sleep, clock=clock),
            NO_TLSA,
        )
        self.assertEqual(seq, [])

        # Budget exhausted without a no_tlsa answer is still-loading, not no_tlsa.
        def fetch_loading():
            return ("ok", LOADING_14)

        self.assertEqual(
            wait_for_tlsa(fetch_loading, LEAF_SPKI, lazy=True, timeout_sec=1,
                          sleep=sleep, clock=clock),
            LOADING_TIMEOUT,
        )

    def test_plain_servfail_without_ede_is_existing_fail_path(self):
        verdict, _ = self._wait("lazytest-servfail.pepe", timeout_sec=5)
        self.assertEqual(verdict, FAIL)
        self.assertNotEqual(verdict, LOADING_TIMEOUT)
        rcode, ede = dns_query(self.node.dns_port, "lazytest-servfail.pepe")
        self.assertEqual(rcode, RCODE_SERVFAIL)
        self.assertIsNone(ede)
        self.assertFalse(is_lazy_loading_dns(rcode, ede))
        kind, body = http_fetch(self.node.http_port, "lazytest-servfail.pepe", timeout=2)
        self.assertEqual(kind, "ok")
        self.assertFalse(is_lazy_loading_status(body))

    def test_names_work_while_a_zone_is_still_loading(self):
        url = f"http://127.0.0.1:{self.node.http_port}/gd/names?prefix=lazytest-&limit=10"
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertIn("lazytest-slow", data["names"])
        self.assertIn("lazytest-warm", data["names"])
        self.assertIn("lazytest-other", data["names"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
