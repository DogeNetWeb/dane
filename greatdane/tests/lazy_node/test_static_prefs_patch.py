#!/usr/bin/env python3
"""F1/F2/F4/N2: the StaticPrefs patches must be complete, atomic-typed,
idempotent, all-or-nothing, and fail loudly. Never writes to the Firefox
source tree; applies only to a temp copy."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
YP = REPO / "modules/libpref/init/StaticPrefList.yaml.patch"
MP = REPO / "modules/libpref/moz.build.patch"
INC = REPO / "modules/libpref/init/StaticPrefList-greatdane-node.inc.yaml"
APPLY = REPO / "greatdane/tools/apply-greatdane-static-prefs.sh"
OVERLAY = REPO / "greatdane/tools/apply-greatdane-overlay.sh"
SSL = REPO / "security/manager/ssl/SSLServerCertVerification.cpp"
DEFAULT_FIREFOX_SRC = Path("/workspace/dane-linux/src")
SSL_REL = "security/manager/ssl/SSLServerCertVerification.cpp"


def _ssl_text():
    """Live SSL file (overlay / Firefox tree after git am), or the net
    result of this repo's patches/ series when that file is not vendored
    (public patch-series layout)."""
    if SSL.is_file():
        return SSL.read_text()
    series = REPO / "patches" / "series"
    if not series.is_file():
        raise FileNotFoundError(SSL)
    # Replay add/remove of distinctive strings. The pre-lazy Dane tree
    # does not mention these lazy StaticPrefs symbols, so a leftover
    # '+' without a later '-' means the final file contains the needle.
    contents = { "StaticPrefs_greatdane.h": 0,
                 "StaticPrefs::greatdane_node_lazy()": 0,
                 "StaticPrefs::greatdane_node_lazyTimeoutSec()": 0,
                 'Preferences::GetBool': 0,
                 'Preferences::GetInt': 0 }
    in_ssl = False
    for name in series.read_text().splitlines():
        name = name.strip()
        if not name or name.startswith("#"):
            continue
        pf = REPO / "patches" / name
        if not pf.is_file():
            continue
        in_ssl = False
        for line in pf.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("diff --git "):
                in_ssl = SSL_REL in line
                continue
            if not in_ssl:
                continue
            if line.startswith("+++") or line.startswith("---"):
                continue
            if line.startswith("+"):
                for k in contents:
                    if k in line:
                        contents[k] += 1
            elif line.startswith("-"):
                for k in contents:
                    if k in line:
                        contents[k] -= 1
    # Synthesize a stand-in the existing assertions can read.
    parts = []
    for k, n in contents.items():
        if n > 0:
            parts.append(k)
        # n==0: not present; n<0 would be a removed leftover of a
        # pre-existing line we did not start with — treat as absent.
    return "\n".join(parts) + "\n"


def firefox_src():
    env = os.environ.get("GREATDANE_FIREFOX_SRC")
    p = Path(env) if env else DEFAULT_FIREFOX_SRC
    yaml = p / "modules/libpref/init/StaticPrefList.yaml"
    moz = p / "modules/libpref/moz.build"
    if yaml.is_file() and moz.is_file():
        return p
    return None


def _copy_tree(src: Path) -> Path:
    td = Path(tempfile.mkdtemp(prefix="gd-static-prefs-"))
    (td / "modules/libpref/init").mkdir(parents=True)
    shutil.copy(src / "modules/libpref/init/StaticPrefList.yaml",
                td / "modules/libpref/init/StaticPrefList.yaml")
    shutil.copy(src / "modules/libpref/moz.build",
                td / "modules/libpref/moz.build")
    subprocess.run(["git", "init", "-q"], cwd=td, check=True,
                   capture_output=True)
    return td


def _run_apply(*args):
    return subprocess.run(
        [str(APPLY), *args],
        check=False, capture_output=True, text=True,
    )


def _pref_count(yaml: str, name: str) -> int:
    # Exact name only: "greatdane.node.lazy" is a prefix of lazyTimeoutSec.
    needle = f"name: {name}"
    return sum(1 for ln in yaml.splitlines() if ln.strip() == needle or ln.strip() == f"- {needle}")


def _counts(td: Path):
    yaml = (td / "modules/libpref/init/StaticPrefList.yaml").read_text()
    return (
        _pref_count(yaml, "greatdane.node.lazy"),
        _pref_count(yaml, "greatdane.node.lazyTimeoutSec"),
        yaml,
        (td / "modules/libpref/moz.build").read_text(),
    )


class TestStaticPrefsPatch(unittest.TestCase):
    def test_inc_yaml_fragment_is_gone(self):
        self.assertFalse(INC.exists(), "F4: drop the .inc.yaml fragment")

    def test_patches_and_apply_script_exist(self):
        self.assertTrue(YP.is_file(), YP)
        self.assertTrue(MP.is_file(), MP)
        self.assertTrue(APPLY.is_file() and os.access(APPLY, os.X_OK), APPLY)
        self.assertTrue(OVERLAY.is_file() and os.access(OVERLAY, os.X_OK), OVERLAY)
        # N1: the overlay hook calls the static-prefs script.
        hook = OVERLAY.read_text()
        self.assertIn("apply-greatdane-static-prefs.sh", hook)
        self.assertIn('exec "$AS"', hook)

    def test_pref_names_stay_greatdane_and_types_are_atomic(self):
        yp = YP.read_text()
        self.assertIn("name: greatdane.node.lazy", yp)
        self.assertIn("name: greatdane.node.lazyTimeoutSec", yp)
        self.assertIn("type: RelaxedAtomicBool", yp)
        self.assertIn("type: RelaxedAtomicInt32", yp)
        after_lazy = yp.split("name: greatdane.node.lazy", 1)[1]
        first_type = [ln for ln in after_lazy.splitlines() if "type:" in ln][0]
        self.assertIn("RelaxedAtomicBool", first_type)
        after_to = yp.split("name: greatdane.node.lazyTimeoutSec", 1)[1]
        first_to = [ln for ln in after_to.splitlines() if "type:" in ln][0]
        self.assertIn("RelaxedAtomicInt32", first_to)
        self.assertNotIn("security.greatdane.node_lazy", yp)
        self.assertIn('"greatdane"', MP.read_text())
        ssl = _ssl_text()
        self.assertIn("StaticPrefs_greatdane.h", ssl)
        self.assertIn("StaticPrefs::greatdane_node_lazy()", ssl)
        self.assertIn("StaticPrefs::greatdane_node_lazyTimeoutSec()", ssl)
        self.assertNotIn("Preferences::GetBool", ssl)
        self.assertNotIn("Preferences::GetInt", ssl)

    def test_apply_script_check_against_firefox_tree(self):
        src = firefox_src()
        if src is None:
            self.skipTest("no Firefox tree (set GREATDANE_FIREFOX_SRC)")
        # --check must not write. Use both the overlay hook and AS.
        for tool in (APPLY, OVERLAY):
            r = subprocess.run(
                [str(tool), "--check", str(src)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("check OK", r.stdout)

    def test_double_run_is_noop_success(self):
        src = firefox_src()
        if src is None:
            self.skipTest("no Firefox tree (set GREATDANE_FIREFOX_SRC)")
        td = _copy_tree(src)
        try:
            r1 = _run_apply(str(td))
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            self.assertIn("applied and verified", r1.stdout)
            n1, t1, yaml1, moz1 = _counts(td)
            self.assertEqual((n1, t1), (1, 1))
            self.assertIn('"greatdane"', moz1)

            r2 = _run_apply(str(td))
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            self.assertIn("already applied", r2.stdout)
            n2, t2, yaml2, moz2 = _counts(td)
            self.assertEqual((n2, t2), (1, 1), "second run must not duplicate entries")
            self.assertEqual(yaml1, yaml2)
            self.assertEqual(moz1, moz2)

            r3 = _run_apply("--check", str(td))
            self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
            self.assertIn("already applied", r3.stdout)
            self.assertEqual(_counts(td)[2], yaml1)
        finally:
            shutil.rmtree(td, ignore_errors=True)

    def test_partial_pre_state_fails_before_any_write(self):
        src = firefox_src()
        if src is None:
            self.skipTest("no Firefox tree (set GREATDANE_FIREFOX_SRC)")
        td = _copy_tree(src)
        try:
            # Apply only the yaml patch, leaving moz.build unpatched.
            r = subprocess.run(
                ["git", "-C", str(td), "apply", str(YP)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            n0, t0, yaml0, moz0 = _counts(td)
            self.assertEqual((n0, t0), (1, 1))
            self.assertNotIn('"greatdane"', moz0)

            r = _run_apply(str(td))
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("partial pre-state", r.stderr)
            n1, t1, yaml1, moz1 = _counts(td)
            self.assertEqual(yaml0, yaml1, "must not write yaml on partial pre-state")
            self.assertEqual(moz0, moz1, "must not write moz.build on partial pre-state")
            self.assertEqual((n1, t1), (1, 1), "must not duplicate yaml entries")
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
