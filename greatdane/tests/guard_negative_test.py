# Negative tests for gd_guard: proves the guard FAILS on out-of-root profile/node data dirs.
# Launches no browser. Each case runs a child python that imports gd_guard, then misbehaves.
# Usage: guard_negative_test.py   (exit 0 = every negative case was caught and the positive control passed)
import os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
PRE = "import sys; sys.path.insert(0, %r); import gd_guard, os, tempfile\n" % os.path.join(HERE, "..", "tools")
STRAY = os.path.join(HERE, "gd-neg-stray-dir")
CASES = [
  # name, child code, expect nonzero, expected stderr marker
  ("control: dataDir = gd_guard.safe(gd_guard.ND)",
   "p=gd_guard.profile('gd-neg-'); open(p+'/user.js','w').write('user_pref(\"greatdane.node.dataDir\", \"%s\");\\n' % gd_guard.safe(gd_guard.ND))",
   False, ""),
  ("safe() on a $TMPDIR dir outside the mkdtemp roots",
   "d=tempfile.mkdtemp(prefix='gd-neg-outside-')\ntry: gd_guard.safe(d)\nfinally: os.rmdir(d)",
   True, "outside this run's mkdtemp roots"),
  ("safe() on the real GreatDANE dir (path only, never opened)",
   "gd_guard.safe(os.path.expanduser('~/Library/Application Support/GreatDANE/x'))",
   True, "inside real data dir"),
  ("safe() on a relative path (the old quoting bug)",
   "gd_guard.safe(\"' + gd_guard.ND + '\")",
   True, "outside this run's mkdtemp roots"),
  ("user.js with the literal-quoted relative dataDir (old gmp_check bug)",
   "p=gd_guard.profile('gd-neg-'); open(p+'/user.js','w').write('''user_pref(\"greatdane.node.dataDir\", \"' + gd_guard.ND + '\");\\n''')",
   True, "out-of-root"),
  ("user.js dataDir in $TMPDIR but outside the mkdtemp roots",
   "p=gd_guard.profile('gd-neg-'); open(p+'/user.js','w').write('user_pref(\"greatdane.node.dataDir\", \"%s\");\\n' % tempfile.gettempdir())",
   True, "out-of-root"),
  ("node data dir created in the greatdane/ source tree during the run",
   "os.makedirs(%r + '/pep', exist_ok=True)" % STRAY,
   True, "stray dir"),
]
fails = 0
for name, code, expect_fail, marker in CASES:
    cwd = tempfile.mkdtemp(prefix="gd-neg-cwd-")
    try:
        r = subprocess.run([sys.executable, "-c", PRE + code], cwd=cwd, capture_output=True, text=True, timeout=60)
    finally:
        shutil.rmtree(cwd, ignore_errors=True); shutil.rmtree(STRAY, ignore_errors=True)
    out = (r.stdout + r.stderr).strip().replace("\n", " | ")
    ok = (r.returncode != 0 and marker in out) if expect_fail else (r.returncode == 0)
    fails += 0 if ok else 1
    print("PASS" if ok else "FAIL", "[%s]" % ("must fail" if expect_fail else "must pass"), name, "-> rc=%d" % r.returncode, out[:300])
print("RESULT", "PASS" if fails == 0 else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
