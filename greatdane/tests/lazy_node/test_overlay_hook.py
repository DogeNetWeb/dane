#!/usr/bin/env python3
"""Round-3 C1 / LOW: the overlay hook is wired into the series entry point
(greatdane/tools/apply-dane-series.sh), fails closed, commits its result,
and --check on an already-applied tree still runs the exact-count check.

Hermetic: uses small synthetic libpref files in temp git repos (no Firefox
tree, no network). When GREATDANE_FIREFOX_SRC points at an unpatched
Firefox tree, it also checks that the series' own libpref hunks (0003,
0016, 0163) leave the hook with nothing to do."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
APPLY = REPO / "greatdane/tools/apply-greatdane-static-prefs.sh"
OVERLAY = REPO / "greatdane/tools/apply-greatdane-overlay.sh"
SERIES_TOOL = REPO / "greatdane/tools/apply-dane-series.sh"
HOOK_DOC = REPO / "greatdane/tools/OVERLAY-HOOK.md"
PATCHES = REPO / "patches"
YAML_REL = "modules/libpref/init/StaticPrefList.yaml"
MOZ_REL = "modules/libpref/moz.build"

SYN_YAML = """\
#---------------------------------------------------------------------------
# Prefs starting with "gl."
#---------------------------------------------------------------------------

- name: gl.synthetic
  type: bool
  value: true
  mirror: always

#---------------------------------------------------------------------------
# Prefs starting with "html5."
#---------------------------------------------------------------------------

- name: html5.synthetic
  type: bool
  value: true
  mirror: always
"""

SYN_MOZ = """\
pref_groups = [
    "geo",
    "gfx",
    "gl",
    "html5",
    "idle_period",
    "image",
]
"""

ENV = dict(os.environ, GIT_AUTHOR_NAME="gd-test", GIT_AUTHOR_EMAIL="gd-test@invalid",
           GIT_COMMITTER_NAME="gd-test", GIT_COMMITTER_EMAIL="gd-test@invalid")


def run(*args, cwd=None):
    return subprocess.run([str(a) for a in args], cwd=cwd, env=ENV, check=False,
                          capture_output=True, text=True)


def git(td, *args):
    r = run("git", "-C", td, *args)
    if r.returncode != 0:
        raise AssertionError(f"git {args}: {r.stdout}{r.stderr}")
    return r.stdout.strip()


def make_tree(yaml=SYN_YAML, moz=SYN_MOZ) -> Path:
    td = Path(tempfile.mkdtemp(prefix="gd-overlay-hook-"))
    (td / "modules/libpref/init").mkdir(parents=True)
    (td / YAML_REL).write_text(yaml)
    (td / MOZ_REL).write_text(moz)
    git(td, "init", "-q")
    git(td, "add", "-A")
    git(td, "commit", "-q", "-m", "base")
    return td


def count(td: Path, name: str) -> int:
    return sum(1 for ln in (td / YAML_REL).read_text().splitlines()
               if ln.strip() == f"- name: {name}")


def dup_lazy_block(td: Path):
    """Append a second greatdane.node.lazy entry (an already-applied tree
    that also carries a duplicate)."""
    with open(td / YAML_REL, "a") as f:
        f.write("\n- name: greatdane.node.lazy\n  type: RelaxedAtomicBool\n"
                "  value: false\n  mirror: always\n")


class TestOverlayHook(unittest.TestCase):
    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def tree(self, **kw):
        td = make_tree(**kw)
        self.dirs.append(td)
        return td

    # --- LOW: --check on an already-applied tree runs the count check ---
    def test_check_on_applied_tree_with_duplicate_fails(self):
        td = self.tree()
        r = run(APPLY, td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = run(APPLY, "--check", td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("--check OK (already applied)", r.stdout)
        dup_lazy_block(td)
        before = (td / YAML_REL).read_text()
        for tool in (APPLY, OVERLAY):
            r = run(tool, "--check", td)
            self.assertNotEqual(r.returncode, 0, f"{tool.name}: {r.stdout}{r.stderr}")
            self.assertIn("expected exactly one greatdane.node.lazy", r.stderr)
            self.assertNotIn("check OK", r.stdout)
        self.assertEqual((td / YAML_REL).read_text(), before, "--check must not write")

    def test_check_on_applied_tree_with_wrong_type_fails(self):
        td = self.tree()
        self.assertEqual(run(APPLY, td).returncode, 0)
        y = (td / YAML_REL).read_text().replace("type: RelaxedAtomicInt32", "type: int32_t")
        (td / YAML_REL).write_text(y)
        git(td, "commit", "-qam", "drift")
        # The forward/reverse patch checks now fail on the type line, so this
        # must not report OK either way.
        r = run(APPLY, "--check", td)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)

    # --- C1: hook wired into the series entry point, fail closed, commits ---
    def test_hook_only_applies_and_commits_then_is_noop(self):
        td = self.tree()
        base = git(td, "rev-parse", "HEAD")
        r = run(SERIES_TOOL, "--hook-only", td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("committed the overlay hook result", r.stdout)
        self.assertIn("ready for clobber / configure", r.stdout)
        head = git(td, "rev-parse", "HEAD")
        self.assertNotEqual(head, base)
        self.assertEqual(git(td, "status", "--porcelain"), "")
        files = git(td, "diff", "--name-only", base, head).splitlines()
        self.assertEqual(sorted(files), sorted([YAML_REL, MOZ_REL]))
        self.assertEqual((count(td, "greatdane.node.lazy"), count(td, "greatdane.node.lazyTimeoutSec")), (1, 1))
        self.assertIn('"greatdane"', (td / MOZ_REL).read_text())
        r = run(SERIES_TOOL, "--hook-only", td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("made no changes", r.stdout)
        self.assertEqual(git(td, "rev-parse", "HEAD"), head)

    def test_hook_only_refuses_dirty_tree(self):
        td = self.tree()
        (td / MOZ_REL).write_text(SYN_MOZ + "# local edit\n")
        r = run(SERIES_TOOL, "--hook-only", td)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("tracked changes", r.stderr)
        self.assertEqual(count(td, "greatdane.node.lazy"), 0)

    def test_hook_check_failure_fails_closed(self):
        # Drifted moz.build: the hook's --check fails, nothing is written or committed.
        td = self.tree(moz=SYN_MOZ.replace('    "gl",\n', ""))
        base = git(td, "rev-parse", "HEAD")
        r = run(SERIES_TOOL, "--hook-only", td)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("--check failed", r.stderr)
        self.assertEqual(git(td, "rev-parse", "HEAD"), base)
        self.assertEqual(git(td, "status", "--porcelain"), "")

    def test_duplicate_tree_fails_closed_in_hook(self):
        td = self.tree()
        self.assertEqual(run(APPLY, td).returncode, 0)
        dup_lazy_block(td)
        git(td, "commit", "-qam", "dup")
        base = git(td, "rev-parse", "HEAD")
        r = run(SERIES_TOOL, "--hook-only", td)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertEqual(git(td, "rev-parse", "HEAD"), base)

    def test_full_mode_runs_series_then_hook(self):
        td = self.tree()
        # A one-patch series made in a scratch clone of the tree.
        work = Path(tempfile.mkdtemp(prefix="gd-overlay-series-"))
        self.dirs.append(work)
        clone = work / "c"
        self.assertEqual(run("git", "clone", "-q", td, clone).returncode, 0)
        (clone / "README.dane").write_text("dane\n")
        git(clone, "add", "README.dane")
        git(clone, "commit", "-qm", "add README.dane")
        pdir = work / "patches"
        pdir.mkdir()
        git(clone, "format-patch", "-q", "-1", "-o", pdir)
        names = sorted(p.name for p in pdir.glob("*.patch"))
        (pdir / "series").write_text("# test series\n" + "\n".join(names) + "\n")
        r = run(SERIES_TOOL, "--patches", pdir, td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("applied 1 patches", r.stdout)
        self.assertIn("committed the overlay hook result", r.stdout)
        log = git(td, "log", "--format=%s").splitlines()
        self.assertEqual(log[1], "add README.dane")
        self.assertTrue(log[0].startswith("GreatDANE: StaticPrefs overlay hook"))
        self.assertEqual(git(td, "status", "--porcelain"), "")

    def test_full_mode_am_failure_stops_before_hook(self):
        td = self.tree()
        pdir = Path(tempfile.mkdtemp(prefix="gd-overlay-bad-"))
        self.dirs.append(pdir)
        (pdir / "0001-bad.patch").write_text(
            "From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001\n"
            "From: gd-test <gd-test@invalid>\nDate: Thu, 19 Nov 2026 12:00:00 -0600\n"
            "Subject: [PATCH] bad\n\n---\n"
            "diff --git a/nope b/nope\n--- a/nope\n+++ b/nope\n@@ -1 +1 @@\n-x\n+y\n")
        (pdir / "series").write_text("0001-bad.patch\n")
        base = git(td, "rev-parse", "HEAD")
        r = run(SERIES_TOOL, "--patches", pdir, td)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("overlay hook did not run", r.stderr)
        self.assertEqual(git(td, "rev-parse", "HEAD"), base)
        self.assertEqual(count(td, "greatdane.node.lazy"), 0)

    def test_series_carries_libpref_patch(self):
        names = [n.strip() for n in (PATCHES / "series").read_text().splitlines()
                 if n.strip() and not n.startswith("#")]
        hits = []
        for n in names:
            t = (PATCHES / n).read_text(encoding="utf-8", errors="replace")
            if (f"diff --git a/{YAML_REL} b/{YAML_REL}" in t and f"diff --git a/{MOZ_REL} b/{MOZ_REL}" in t
                    and "+- name: greatdane.node.lazy\n" in t and '+    "greatdane",\n' in t):
                hits.append(n)
        self.assertEqual(len(hits), 1, hits)
        self.assertTrue(hits[0].startswith("0163-"), hits)

    def test_docs_and_tools_have_no_box_paths(self):
        for p in (OVERLAY, SERIES_TOOL, APPLY, HOOK_DOC):
            self.assertNotIn("/workspace", p.read_text(), p)
        doc = HOOK_DOC.read_text()
        self.assertIn("prepare-final-pin-sequence.sh", doc)
        self.assertIn("prepare-final-pin-sequence-r9.sh", doc)

    def test_series_libpref_hunks_leave_hook_nothing_to_do(self):
        env = os.environ.get("GREATDANE_FIREFOX_SRC")
        if not env:
            self.skipTest("no Firefox tree (set GREATDANE_FIREFOX_SRC)")
        src = Path(env)
        td = make_tree(yaml=(src / YAML_REL).read_text(), moz=(src / MOZ_REL).read_text())
        self.dirs.append(td)
        for n in (PATCHES / "series").read_text().splitlines():
            n = n.strip()
            if not n or n.startswith("#"):
                continue
            t = (PATCHES / n).read_text(encoding="utf-8", errors="replace")
            if f"diff --git a/{YAML_REL} " in t or f"diff --git a/{MOZ_REL} " in t:
                r = run("git", "-C", td, "apply", f"--include={YAML_REL}", f"--include={MOZ_REL}",
                        PATCHES / n)
                self.assertEqual(r.returncode, 0, f"{n}: {r.stderr}")
        git(td, "commit", "-qam", "series libpref hunks")
        r = run(OVERLAY, "--check", td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already applied", r.stdout)
        head = git(td, "rev-parse", "HEAD")
        r = run(SERIES_TOOL, "--hook-only", td)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("made no changes", r.stdout)
        self.assertEqual(git(td, "rev-parse", "HEAD"), head)
        self.assertEqual((count(td, "greatdane.node.lazy"), count(td, "greatdane.node.lazyTimeoutSec")), (1, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
