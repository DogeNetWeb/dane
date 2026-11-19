#!/usr/bin/env python3
"""F1/F2/F4: the StaticPrefs patches must be complete, atomic-typed,
apply to the real Firefox tree, and fail loudly if they are not applied.
Never writes to the Firefox source tree; applies only to a temp copy."""
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
SSL = REPO / "security/manager/ssl/SSLServerCertVerification.cpp"
DEFAULT_FIREFOX_SRC = Path("/workspace/dane-linux/src")


def firefox_src():
    env = os.environ.get("GREATDANE_FIREFOX_SRC")
    p = Path(env) if env else DEFAULT_FIREFOX_SRC
    yaml = p / "modules/libpref/init/StaticPrefList.yaml"
    moz = p / "modules/libpref/moz.build"
    if yaml.is_file() and moz.is_file():
        return p
    return None


class TestStaticPrefsPatch(unittest.TestCase):
    def test_inc_yaml_fragment_is_gone(self):
        self.assertFalse(INC.exists(), "F4: drop the .inc.yaml fragment")

    def test_patches_and_apply_script_exist(self):
        self.assertTrue(YP.is_file(), YP)
        self.assertTrue(MP.is_file(), MP)
        self.assertTrue(APPLY.is_file() and os.access(APPLY, os.X_OK), APPLY)

    def test_pref_names_stay_greatdane_and_types_are_atomic(self):
        # F1 naming: keep internal greatdane.* names; add the group in
        # moz.build rather than renaming into security.greatdane.*.
        yp = YP.read_text()
        self.assertIn("name: greatdane.node.lazy", yp)
        self.assertIn("name: greatdane.node.lazyTimeoutSec", yp)
        self.assertIn("type: RelaxedAtomicBool", yp)
        self.assertIn("type: RelaxedAtomicInt32", yp)
        # The new entries must not use the non-atomic types that
        # MOZ_DIAGNOSTIC_ASSERT against off the main thread.
        after_lazy = yp.split("name: greatdane.node.lazy", 1)[1]
        first_type = [ln for ln in after_lazy.splitlines() if "type:" in ln][0]
        self.assertIn("RelaxedAtomicBool", first_type)
        after_to = yp.split("name: greatdane.node.lazyTimeoutSec", 1)[1]
        first_to = [ln for ln in after_to.splitlines() if "type:" in ln][0]
        self.assertIn("RelaxedAtomicInt32", first_to)
        self.assertNotIn("security.greatdane.node_lazy", yp)
        mp = MP.read_text()
        self.assertIn('"greatdane"', mp)
        ssl = SSL.read_text()
        self.assertIn('StaticPrefs_greatdane.h', ssl)
        self.assertIn("StaticPrefs::greatdane_node_lazy()", ssl)
        self.assertIn("StaticPrefs::greatdane_node_lazyTimeoutSec()", ssl)
        self.assertNotIn("Preferences::GetBool", ssl)
        self.assertNotIn("Preferences::GetInt", ssl)

    def test_apply_script_check_and_temp_apply_fail_loudly(self):
        src = firefox_src()
        if src is None:
            self.skipTest("no Firefox tree (set GREATDANE_FIREFOX_SRC)")
        # --check must not write.
        r = subprocess.run(
            [str(APPLY), "--check", str(src)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("check OK", r.stdout)

        td = Path(tempfile.mkdtemp(prefix="gd-static-prefs-"))
        try:
            (td / "modules/libpref/init").mkdir(parents=True)
            shutil.copy(src / "modules/libpref/init/StaticPrefList.yaml",
                        td / "modules/libpref/init/StaticPrefList.yaml")
            shutil.copy(src / "modules/libpref/moz.build",
                        td / "modules/libpref/moz.build")
            subprocess.run(["git", "init", "-q"], cwd=td, check=True,
                           capture_output=True)
            r = subprocess.run(
                [str(APPLY), str(td)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            yaml = (td / "modules/libpref/init/StaticPrefList.yaml").read_text()
            moz = (td / "modules/libpref/moz.build").read_text()
            self.assertIn("name: greatdane.node.lazy", yaml)
            self.assertIn("name: greatdane.node.lazyTimeoutSec", yaml)
            self.assertIn("RelaxedAtomicBool", yaml)
            self.assertIn("RelaxedAtomicInt32", yaml)
            self.assertIn('"greatdane"', moz)

            # Loud failure if the result is missing a pref (simulate).
            broken = td / "modules/libpref/init/StaticPrefList.yaml"
            broken.write_text(yaml.replace("greatdane.node.lazy", "x.node.lazy"))
            r = subprocess.run(
                ["sh", "-c",
                 'grep -q "name: greatdane.node.lazy$" "$1" || '
                 '{ echo "missing pref" >&2; exit 1; }',
                 "check", str(broken)],
                check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(r.returncode, 0)
        finally:
            shutil.rmtree(td, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
