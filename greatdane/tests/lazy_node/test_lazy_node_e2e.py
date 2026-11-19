#!/usr/bin/env python3
"""End-to-end checks of Dane's lazy-node contract against a REAL greatdane-node.

Localhost only, synthetic names (lazye2e-*.pepe), throwaway --data dir.
Must run in a private netns so the node cannot reach any real seed/mesh:

    unshare -Urn -- sh -c 'ip link set lo up && \\
      GREATDANE_NODE=/path/to/greatdane-node python3 test_lazy_node_e2e.py'

Never touches ~/.pepenet or ~/.local/share/greatdane. No mach.

What is real vs stubbed is printed at the end:
  REAL  — launch, stdio status, /gd/names, /gd/tlsa loading (EDE 14),
          unowned, CONNECT 503 loading. EDE 22 if the node emits it.
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
    lazy_node_args,
    lazy_node_env,
    wait_for_tlsa,
    _spki_sha256_hex,
)
from test_lazy_node import BAD_TLSA, LEAF_SPKI, OK_TLSA, LOADING_14  # noqa: E402

NODE = os.environ.get("GREATDANE_NODE", "")
# Short wait avoids a confirmed SIGSEGV in the node at the default 3000 ms
# wait when no peers can answer a lazy zget (see Keeper notes in the report).
E2E_WAIT_MS = os.environ.get("GREATDANE_NODE_LAZY_WAIT_MS", "200")
OWNED = "lazye2e-owned"
UNOWNED = "lazye2e-nosuch"
LEASE = 2_000_000_000  # well past now; owner_now is lease-gated


def _in_private_netns():
    if os.environ.get("GD_TEST_NETNS_OK"):
        return True
    try:
        lines = Path("/proc/self/net/dev").read_text().splitlines()[2:]
    except OSError:
        return False
    others = [ln for ln in lines if " lo:" not in ln]
    return len(others) == 0


def _http(port, path, timeout=8, method="GET", host="x"):
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
    status = int(lines[0].split()[1])
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
    def __init__(self, node, wait_ms="200"):
        self.node = node
        self.wait_ms = str(wait_ms)
        self.dir = None
        self.proc = None
        self.ready = None

    def start(self, seed=True):
        self.dir = tempfile.mkdtemp(prefix="dane-lazy-e2e-")
        # First boot creates pep.db; seed a valid-lease name; restart.
        self._spawn()
        self._wait_ready()
        pepdb = next(Path(self.dir).rglob("pep.db"))
        if seed:
            c = sqlite3.connect(str(pepdb))
            c.execute(
                "INSERT OR REPLACE INTO names(name,owner,owner_type,lease_expiry,st) "
                "VALUES(?,?,0,?,1)",
                (OWNED, bytes([0x22]) * 20, LEASE),
            )
            c.commit()
            c.close()
            self.stop()
            self._spawn()
            self._wait_ready()
        return self

    def _spawn(self):
        env = os.environ.copy()
        env.pop("PEPENET_DNS_LISTEN", None)
        env["HOME"] = self.dir
        env.update(lazy_node_env(self.dir, enabled=True))
        env["GREATDANE_NODE_LAZY_WAIT_MS"] = self.wait_ms
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
            "--lazy-wait-ms", self.wait_ms,
        ]
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

    def pac(self):
        return int(self.ready["pac"])

    def get(self, path, timeout=8, method="GET", host="x"):
        return _http(self.pac(), path, timeout=timeout, method=method, host=host)

    def stop(self):
        if not self.proc:
            return
        if self.proc.stdin:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self.proc = None
        for fh in (getattr(self, "_out_f", None), getattr(self, "_err_f", None)):
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
        """One sequential pass: the isolated node can SIGSEGV a few seconds
        after a lazy zget starts with no peers (default 3s wait, or shortly
        after a short-wait query). Do the contract checks immediately.
        """
        n = RealLazyNode(NODE, wait_ms=E2E_WAIT_MS)
        try:
            n.start()
            self.assertEqual(n.proc.poll(), None, "node died during start")
            ready = n.ready
            self.assertEqual(ready.get("dane_api"), 1)
            st = n.status()
            self.assertIsNotNone(st)
            self.assertEqual(st.get("lazy"), 1)
            for k in ("namespace_synced", "zones_cached", "zones_loading", "zones_failed"):
                self.assertIn(k, st)
            # Isolated, no peers: height/peer_height are 0, so the node
            # reports namespace_synced false. Dane honors the field.
            self.assertIsInstance(st["namespace_synced"], bool)
            cache = Path(n.dir) / "lazy-zones-pep.db"
            self.assertTrue(cache.exists(), f"cache missing under --lazy-cache-dir: {cache}")
            err = n.err_path.read_text(errors="replace")
            self.assertIn("LAZY mode", err)
            self.assertIn(f"cache_dir={n.dir}", err)

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
            self.assertEqual(classify_chain_failure("unowned"), "GD_NAME_UNOWNED")

            status, _, body = n.get(f"/gd/tlsa?host={OWNED}.pepe", timeout=8)
            self.assertEqual(status, 200, body)
            j = _json_body(body)
            self.assertTrue(is_lazy_loading_status(j), j)
            self.assertEqual(j.get("status"), "loading")
            self.assertEqual(j.get("rcode"), "SERVFAIL")
            self.assertEqual(int(j.get("ede")), LAZY_LOADING_EDE)
            self.assertEqual(j.get("phase"), "fetching")
            self.assertEqual(int(j.get("retry_ms")), 1000)
            self.assertEqual(classify_chain_failure(j["status"]), "GD_ZONE_LOADING")

            status, headers, _ = n.get(
                f"{OWNED}.pepe:443", timeout=8, method="CONNECT", host=f"{OWNED}.pepe"
            )
            self.assertEqual(status, 503, headers)
            self.assertTrue(is_proxy_loading(status, headers), headers)
            self.assertEqual(headers.get("x-greatdane-status", "").lower(), "loading")
            self.assertEqual(headers.get("retry-after"), "1")
            self.assertEqual(
                classify_chain_failure(None, proxy_loading=True), "GD_ZONE_LOADING"
            )

            # Optional: if the node stays up, watch for EDE 22. A SIGSEGV
            # here is a node bug (reported to Keeper), not a Dane regression.
            saw22 = False
            died = None
            last = j
            deadline = time.time() + 6
            while time.time() < deadline:
                rc = n.proc.poll()
                if rc is not None:
                    died = rc
                    break
                try:
                    status, _, body = n.get(f"/gd/tlsa?host={OWNED}.pepe", timeout=8)
                except OSError as e:
                    died = n.proc.poll()
                    print(f"\n[e2e] /gd/tlsa poll error {e!r} node_rc={died}", file=sys.stderr)
                    break
                if status != 200:
                    print(f"\n[e2e] unexpected status {status} body={body!r}", file=sys.stderr)
                    break
                last = _json_body(body)
                self.assertTrue(is_lazy_loading_status(last), last)
                self.assertNotIn(last.get("status"), ("no_tlsa", "unowned"))
                if int(last.get("ede") or 0) == LAZY_FETCH_FAILED_EDE:
                    saw22 = True
                    self.assertEqual(last.get("phase"), "fetch_failed")
                    break
                time.sleep(0.4)
            print(
                f"\n[e2e] EDE22={saw22} node_rc={died} last={last} "
                f"final_status={n.status()}",
                file=sys.stderr,
            )
            if died is not None:
                # -11 == SIGSEGV; keep the earlier contract asserts as the pass/fail.
                print(
                    f"[e2e] node exited {died} after the loading query "
                    f"(stderr follows)\n{n.err_path.read_text(errors='replace')}",
                    file=sys.stderr,
                )
        finally:
            n.stop()

    def test_stubbed_ok_and_bad_tlsa_still_enforced_in_policy(self):
        # Seeding a fetched zone into an isolated node is out of scope; the
        # verifier policy itself is still checked here against synthetic bodies.
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
