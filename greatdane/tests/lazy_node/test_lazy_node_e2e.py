#!/usr/bin/env python3
"""End-to-end checks of Dane's lazy-node contract against a REAL greatdane-node.

Localhost only, synthetic names (lazye2e-*.pepe), throwaway --data dir.
Must run in a private netns so the node cannot reach any real seed/mesh:

    unshare -Urn -- sh -c 'ip link set lo up && \\
      GREATDANE_NODE=/path/to/greatdane-node python3 test_lazy_node_e2e.py'

Never touches ~/.pepenet or ~/.local/share/greatdane. No mach.

Real vs stubbed is printed in the module docstring and at the end of
test_real_node_lazy_contract:

  REAL  — launch, stdio status (incl. namespace_sync_basis /
          best_known_height), healthy fixture (height>0, seller/buyer
          zeroblob(20)), default 3000 ms and 300 ms waits with no crash,
          --lazy-wait-ms reaching /gd/tlsa+CONNECT and beating env,
          /gd/names, /gd/tlsa EDE 14 then EDE 22, unowned, CONNECT 503,
          offline namespace_synced true after grace.
  STUB  — loading-then-ok and a bad-TLSA reject need a fetched zone
          (isolated 2-node seed is out of scope); those stay in
          test_lazy_node.py against the in-process fake node.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lazy_policy import (  # noqa: E402
    LAZY_FETCH_FAILED_EDE,
    LAZY_LOADING_EDE,
    classify_chain_failure,
    is_lazy_loading_status,
    is_proxy_loading,
    lazy_namespace_synced,
    lazy_node_args,
    lazy_node_env,
)
from test_lazy_node import BAD_TLSA, LEAF_SPKI, LOADING_14, OK_TLSA  # noqa: E402
from lazy_policy import wait_for_tlsa, _spki_sha256_hex  # noqa: E402

NODE = os.environ.get("GREATDANE_NODE", "")
# Official offline grace is 15s; shorten for tests (node allows 0..600).
E2E_GRACE_S = os.environ.get("GREATDANE_NODE_SYNC_GRACE_S", "3")
OWNED = "lazye2e-owned"
UNOWNED = "lazye2e-nosuch"
LEASE = 2_000_000_000
TIP = 1000


def _in_private_netns():
    if os.environ.get("GD_TEST_NETNS_OK"):
        return True
    try:
        lines = Path("/proc/self/net/dev").read_text().splitlines()[2:]
    except OSError:
        return False
    others = [ln for ln in lines if " lo:" not in ln]
    return len(others) == 0


def _http(port, path, timeout=15, method="GET", host="x"):
    s = socket.create_connection(("127.0.0.1", int(port)), timeout)
    s.settimeout(timeout)
    req = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    s.sendall(req.encode())
    b = b""
    while True:
        try:
            d = s.recv(8192)
        except socket.timeout:
            break
        if not d:
            break
        b += d
    s.close()
    raw = b.decode("utf-8", "replace")
    if "\r\n\r\n" not in raw:
        return 0, {}, raw
    head, body = raw.split("\r\n\r\n", 1)
    lines = head.split("\r\n")
    try:
        status = int(lines[0].split()[1])
    except (IndexError, ValueError):
        return 0, {}, raw
    headers = {}
    for ln in lines[1:]:
        if ":" in ln:
            k, v = ln.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return status, headers, body


def _json_body(body):
    body = body.strip()
    return json.loads(body) if body else {}


class RealLazyNode:
    def __init__(self, node, wait_ms=None, grace_s=E2E_GRACE_S):
        self.node = node
        self.wait_ms = None if wait_ms is None else str(wait_ms)
        self.grace_s = str(grace_s)
        self.dir = None
        self.proc = None
        self.ready = None
        self._out_f = None
        self._err_f = None

    def start(self, seed=True):
        self.dir = tempfile.mkdtemp(prefix="dane-lazy-e2e-")
        self._spawn()
        self._wait_ready()
        if seed:
            self._seed()
            self.stop()
            self._spawn()
            self._wait_ready()
        return self

    def _seed(self):
        # Healthy fixture (v2): seller/buyer zeroblob(20) and height > 0.
        pepdb = next(Path(self.dir).rglob("pep.db"))
        c = sqlite3.connect(str(pepdb))
        c.execute(
            "INSERT OR REPLACE INTO names("
            "name,owner,owner_type,lease_expiry,st,seller,buyer) "
            "VALUES(?,?,0,?,1,zeroblob(20),zeroblob(20))",
            (OWNED, bytes([0x22]) * 20, LEASE),
        )
        c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('height',?)", (str(TIP),))
        c.commit()
        c.close()

    def _spawn(self):
        env = os.environ.copy()
        env.pop("PEPENET_DNS_LISTEN", None)
        env.pop("GREATDANE_NODE_LAZY_WAIT_MS", None)
        env["HOME"] = self.dir
        env.update(lazy_node_env(self.dir, enabled=True))
        env["GREATDANE_NODE_SYNC_GRACE_S"] = self.grace_s
        args = [
            self.node,
            "--data", self.dir,
            "--only", "pep",
            "--ephemeral-ports",
            "--dane-api",
            "--stdio",
            "--no-listen",
            "--seeds", "127.0.0.1:9",
            *lazy_node_args(self.dir, enabled=True),
        ]
        if self.wait_ms is not None:
            env["GREATDANE_NODE_LAZY_WAIT_MS"] = self.wait_ms
            args.extend(["--lazy-wait-ms", self.wait_ms])
        self.out_path = Path(self.dir) / "node.out"
        self.err_path = Path(self.dir) / "node.err"
        self._out_f = open(self.out_path, "wb")
        self._err_f = open(self.err_path, "wb")
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=self._out_f,
            stderr=self._err_f,
            env=env,
            cwd=self.dir,
        )

    def _wait_ready(self, secs=20):
        deadline = time.time() + secs
        while time.time() < deadline:
            if self.out_path.exists():
                for line in self.out_path.read_text(errors="replace").splitlines():
                    if '"event":"ready"' in line:
                        self.ready = json.loads(line)
                        return
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"node exited {self.proc.returncode}: {self.err_path.read_text()[-2000:]}"
                )
            time.sleep(0.05)
        raise TimeoutError(
            "no ready line\n" + self.out_path.read_text(errors="replace")[-2000:]
            + "\n" + self.err_path.read_text(errors="replace")[-2000:]
        )

    def status(self):
        st = None
        for line in self.out_path.read_text(errors="replace").splitlines():
            if '"event":"status"' in line:
                try:
                    st = json.loads(line)
                except json.JSONDecodeError:
                    pass
        return st

    def request_status(self, wait=1.5):
        before = self.out_path.read_text(errors="replace").count('"event":"status"')
        if self.proc and self.proc.stdin:
            self.proc.stdin.write(b'{"cmd":"status"}\n')
            self.proc.stdin.flush()
        deadline = time.time() + wait
        while time.time() < deadline:
            now = self.out_path.read_text(errors="replace").count('"event":"status"')
            if now > before:
                return self.status()
            time.sleep(0.05)
        return self.status()

    def pac(self):
        return int(self.ready["pac"])

    def get(self, path, timeout=15, method="GET", host="x"):
        return _http(self.pac(), path, timeout=timeout, method=method, host=host)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if not self.proc:
            self._close_logs()
            return self.proc
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            rc = self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.proc.send_signal(signal.SIGTERM)
            try:
                rc = self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                rc = self.proc.wait(timeout=2)
        self.proc = None
        self._close_logs()
        return rc

    def _close_logs(self):
        for fh in (self._out_f, self._err_f):
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
        self._out_f = self._err_f = None


@unittest.skipUnless(NODE and os.path.isfile(NODE) and os.access(NODE, os.X_OK),
                     "set GREATDANE_NODE to a built greatdane-node")
@unittest.skipUnless(_in_private_netns(),
                     "refuse to run outside a private netns (unshare -Urn, lo up)")
class RealLazyNodeTests(unittest.TestCase):
    def test_real_node_lazy_contract(self):
        """Default 3000 ms wait, crash probe, EDE 14/22, offline sync."""
        n = RealLazyNode(NODE, wait_ms=None, grace_s=E2E_GRACE_S)
        try:
            n.start()
            self.assertTrue(n.alive(), "node died during start")
            self.assertEqual(n.ready.get("dane_api"), 1)
            st = n.status()
            self.assertIsNotNone(st)
            self.assertEqual(st.get("lazy"), 1)
            for k in (
                "namespace_synced", "zones_cached", "zones_loading",
                "zones_failed", "namespace_sync_basis", "best_known_height",
            ):
                self.assertIn(k, st, st)
            self.assertIsInstance(st["namespace_synced"], bool)
            cache = Path(n.dir) / "lazy-zones-pep.db"
            self.assertTrue(cache.exists(), f"cache missing under --lazy-cache-dir: {cache}")
            err = n.err_path.read_text(errors="replace")
            self.assertIn("LAZY mode", err)
            self.assertIn(f"cache_dir={n.dir}", err)
            self.assertIn("wait=3000ms", err)
            self.assertEqual(st.get("height"), TIP)

            status, _, body = n.get("/gd/names?prefix=lazye2e&limit=20")
            self.assertEqual(status, 200, body)
            names = [row["name"] for row in _json_body(body).get("names", [])]
            self.assertIn(OWNED, names)
            self.assertNotIn(UNOWNED, names)

            status, _, body = n.get(f"/gd/tlsa?host={UNOWNED}.pepe", timeout=5)
            self.assertEqual(status, 200, body)
            j = _json_body(body)
            self.assertEqual(j.get("status"), "unowned")
            self.assertFalse(is_lazy_loading_status(j), j)

            t0 = time.monotonic()
            status, _, body = n.get(f"/gd/tlsa?host={OWNED}.pepe", timeout=15)
            dt = (time.monotonic() - t0) * 1000
            self.assertTrue(n.alive(), f"node died during default 3000ms /gd/tlsa, rc={n.proc.poll() if n.proc else '?'}")
            self.assertEqual(status, 200, body)
            j = _json_body(body)
            self.assertTrue(is_lazy_loading_status(j), j)
            self.assertEqual(j.get("status"), "loading")
            self.assertEqual(j.get("rcode"), "SERVFAIL")
            self.assertEqual(int(j.get("ede")), LAZY_LOADING_EDE)
            self.assertEqual(j.get("phase"), "fetching")
            self.assertEqual(int(j.get("retry_ms")), 1000)
            self.assertGreaterEqual(dt, 2700)
            self.assertLessEqual(dt, 4500)
            self.assertEqual(classify_chain_failure(j["status"]), "GD_ZONE_LOADING")

            t0 = time.monotonic()
            status, headers, _ = n.get(
                f"{OWNED}.pepe:443", timeout=15, method="CONNECT", host=f"{OWNED}.pepe"
            )
            dt_c = (time.monotonic() - t0) * 1000
            self.assertTrue(n.alive(), "node died during default-wait CONNECT")
            self.assertEqual(status, 503, headers)
            self.assertTrue(is_proxy_loading(status, headers), headers)
            self.assertEqual(headers.get("x-greatdane-status", "").lower(), "loading")
            self.assertEqual(headers.get("retry-after"), "1")
            self.assertGreaterEqual(dt_c, 2700)
            self.assertLessEqual(dt_c, 4500)

            saw22 = False
            last = j
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and n.alive():
                status, _, body = n.get(f"/gd/tlsa?host={OWNED}.pepe", timeout=15)
                self.assertTrue(n.alive(), "node died while polling for EDE 22")
                self.assertEqual(status, 200, body)
                last = _json_body(body)
                self.assertTrue(is_lazy_loading_status(last), last)
                self.assertNotIn(last.get("status"), ("no_tlsa", "unowned"))
                if int(last.get("ede") or 0) == LAZY_FETCH_FAILED_EDE:
                    saw22 = True
                    self.assertEqual(last.get("phase"), "fetch_failed")
                    self.assertEqual(classify_chain_failure("loading"), "GD_ZONE_LOADING")
                    break
                time.sleep(0.4)
            self.assertTrue(n.alive(), "node died before EDE 22 poll finished")
            self.assertTrue(saw22, f"EDE 22 not observed; last={last}")

            # Offline namespace_synced after a finished pass + grace.
            synced = None
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and n.alive():
                st = n.request_status()
                if st and st.get("namespace_synced") is True:
                    synced = st
                    break
                time.sleep(0.4)
            self.assertTrue(n.alive(), "node died while waiting for namespace_synced")
            self.assertIsNotNone(synced, f"namespace_synced never became true; last={n.status()}")
            self.assertEqual(synced.get("namespace_sync_basis"), "offline")
            self.assertTrue(lazy_namespace_synced(synced))
            # height 1000 < activation 1130000 must not fail-close.
            self.assertLess(synced.get("height") or 0, synced.get("activation") or 0)
            print(
                f"\n[e2e] EDE22 last={last} synced={ {k: synced.get(k) for k in ('namespace_synced','namespace_sync_basis','best_known_height','height','passes')} }",
                file=sys.stderr,
            )
        finally:
            rc = n.stop()
            self.assertTrue(rc is None or rc < 128, f"node exited with signal rc={rc}")

    def test_300ms_wait_no_crash(self):
        n = RealLazyNode(NODE, wait_ms=300, grace_s=E2E_GRACE_S)
        try:
            n.start()
            t0 = time.monotonic()
            status, _, body = n.get(f"/gd/tlsa?host={OWNED}.pepe", timeout=8)
            dt = (time.monotonic() - t0) * 1000
            self.assertTrue(n.alive(), "node died on 300ms /gd/tlsa")
            self.assertEqual(status, 200, body)
            j = _json_body(body)
            self.assertTrue(is_lazy_loading_status(j), j)
            self.assertEqual(int(j.get("ede")), LAZY_LOADING_EDE)
            self.assertLess(dt, 1500)
            t0 = time.monotonic()
            status, headers, _ = n.get(
                f"{OWNED}.pepe:443", timeout=8, method="CONNECT", host=f"{OWNED}.pepe"
            )
            dt = (time.monotonic() - t0) * 1000
            self.assertTrue(n.alive(), "node died on 300ms CONNECT")
            self.assertEqual(status, 503, headers)
            self.assertTrue(is_proxy_loading(status, headers), headers)
            self.assertLess(dt, 1500)
            time.sleep(2)
            self.assertTrue(n.alive(), "node died 2s after 300ms loading queries")
        finally:
            rc = n.stop()
            self.assertTrue(rc is None or rc < 128, f"node exited with signal rc={rc}")

    def test_lazy_wait_ms_flag_beats_env(self):
        n = RealLazyNode(NODE, wait_ms=None, grace_s=E2E_GRACE_S)
        # Custom spawn: flag 700 vs env 5000.
        n.dir = tempfile.mkdtemp(prefix="dane-lazy-e2e-wait-")
        try:
            n._spawn()  # first boot to create pep.db
            n._wait_ready()
            n._seed()
            n.stop()
            env = os.environ.copy()
            env.pop("PEPENET_DNS_LISTEN", None)
            env["HOME"] = n.dir
            env.update(lazy_node_env(n.dir, enabled=True))
            env["GREATDANE_NODE_SYNC_GRACE_S"] = str(E2E_GRACE_S)
            env["GREATDANE_NODE_LAZY_WAIT_MS"] = "5000"
            args = [
                NODE, "--data", n.dir, "--only", "pep", "--ephemeral-ports",
                "--dane-api", "--stdio", "--no-listen", "--seeds", "127.0.0.1:9",
                *lazy_node_args(n.dir, enabled=True),
                "--lazy-wait-ms", "700",
            ]
            n.out_path = Path(n.dir) / "node.out"
            n.err_path = Path(n.dir) / "node.err"
            n._out_f = open(n.out_path, "wb")
            n._err_f = open(n.err_path, "wb")
            n.proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=n._out_f, stderr=n._err_f,
                env=env, cwd=n.dir,
            )
            n._wait_ready()
            err = n.err_path.read_text(errors="replace")
            self.assertIn("wait=700ms", err, err[-1500:])
            t0 = time.monotonic()
            status, _, body = n.get(f"/gd/tlsa?host={OWNED}.pepe", timeout=8)
            dt = (time.monotonic() - t0) * 1000
            self.assertTrue(n.alive(), "node died during flag-wait /gd/tlsa")
            self.assertEqual(status, 200, body)
            self.assertTrue(is_lazy_loading_status(_json_body(body)))
            self.assertGreaterEqual(dt, 550)
            self.assertLessEqual(dt, 2000)
            t0 = time.monotonic()
            status, headers, _ = n.get(
                f"{OWNED}.pepe:443", timeout=8, method="CONNECT", host=f"{OWNED}.pepe"
            )
            dt = (time.monotonic() - t0) * 1000
            self.assertTrue(n.alive())
            self.assertEqual(status, 503, headers)
            self.assertLessEqual(dt, 2000)
        finally:
            n.stop()

    def test_stubbed_ok_and_bad_tlsa_still_enforced_in_policy(self):
        def fetch_ok():
            return ("ok", OK_TLSA)

        def fetch_bad():
            return ("ok", BAD_TLSA)

        def fetch_then_ok():
            if not hasattr(fetch_then_ok, "n"):
                fetch_then_ok.n = 0
            fetch_then_ok.n += 1
            return ("ok", LOADING_14 if fetch_then_ok.n == 1 else OK_TLSA)

        t = [0.0]

        def sleep(s):
            t[0] += s

        self.assertEqual(
            wait_for_tlsa(fetch_ok, LEAF_SPKI, sleep=sleep, clock=lambda: t[0]),
            "match",
        )
        t[0] = 0.0
        self.assertEqual(
            wait_for_tlsa(fetch_bad, LEAF_SPKI, sleep=sleep, clock=lambda: t[0]),
            "fail",
        )
        t[0] = 0.0
        self.assertEqual(
            wait_for_tlsa(fetch_then_ok, LEAF_SPKI, sleep=sleep, clock=lambda: t[0]),
            "match",
        )
        self.assertEqual(_spki_sha256_hex(LEAF_SPKI), OK_TLSA["data"])


if __name__ == "__main__":
    if not NODE:
        sys.stderr.write(
            "test_lazy_node_e2e: SKIP — set GREATDANE_NODE to the built binary\n"
        )
        sys.exit(0)
    if not _in_private_netns():
        sys.stderr.write(
            "test_lazy_node_e2e: refusing to run outside a private netns\n"
            "  unshare -Urn -- sh -c 'ip link set lo up && "
            "GREATDANE_NODE=... python3 test_lazy_node_e2e.py'\n"
        )
        sys.exit(1)
    unittest.main(verbosity=2)
