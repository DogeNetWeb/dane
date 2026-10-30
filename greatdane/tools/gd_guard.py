"""gd_guard: safety guard for Dane test suites.

Import first in every suite. On import it:
  * snapshots sha256+mtime of the REAL GreatDANE profiles.ini / installs.ini
    and fails the suite (exit 97) at exit, or on check(), if they changed;
  * creates throwaway mktemp dirs: gd_guard.profile(prefix) and gd_guard.ND
    (node data dir), refusing any path inside the real GreatDANE dir or real
    node data dirs, and any path not inside one of this run's mkdtemp roots;
  * at exit, fails the suite (exit 96) if any created profile's user.js/prefs.js
    points greatdane.node.dataDir outside the mkdtemp roots, or if new dirs
    appeared in the greatdane/ source tree, the cwd, or $HOME during the run.
Env (testing the guard only): GD_GUARD_REAL_DIR overrides the watched dir,
e.g. to point at a COPY.
"""
import atexit, hashlib, os, re, shutil, sys, tempfile, time

REAL = os.path.realpath(os.environ.get("GD_GUARD_REAL_DIR") or
                        os.path.expanduser("~/Library/Application Support/GreatDANE"))
FORBIDDEN = [os.path.realpath(os.path.expanduser(p)) for p in (
    "~/Library/Application Support/GreatDANE", "/Volumes/Storage/dnnode",
    "~/.pepecoin", "~/.dogecoin", "~/Library/Application Support/Pepecoin",
    "~/Library/Application Support/Dogecoin")] + [REAL]
WATCH = ("profiles.ini", "installs.ini")


def _snap():
    out = {}
    for n in WATCH:
        f = os.path.join(REAL, n)
        try:
            st = os.stat(f)
            out[n] = (hashlib.sha256(open(f, "rb").read()).hexdigest(), st.st_mtime_ns)
        except FileNotFoundError:
            out[n] = None
    return out


BASE = _snap()
_tmp = []


def _forbidden(rp):
    for f in FORBIDDEN:
        if rp == f or rp.startswith(f + os.sep):
            return f
    return None


def inroot(path):
    """True if path is one of this run's mkdtemp roots or inside one."""
    rp = os.path.realpath(path)
    for r in (os.path.realpath(d) for d in _tmp):
        if rp == r or rp.startswith(r + os.sep):
            return True
    return False


def safe(path):
    rp = os.path.realpath(path)
    f = _forbidden(rp)
    if f:
        sys.exit("gd_guard: REFUSING path inside real data dir: %s (%s)" % (path, f))
    if not os.path.isabs(path) or not inroot(path):
        sys.exit("gd_guard: REFUSING path outside this run's mkdtemp roots: %r" % (path,))
    return path


def profile(prefix="gd-test-"):
    d = tempfile.mkdtemp(prefix=prefix)
    _tmp.append(d)
    return safe(d)


TREE = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HOME = os.path.realpath(os.path.expanduser("~"))
CWD = os.path.realpath(os.getcwd())
_SKIP = {"__pycache__", ".git", ".pytest_cache"}


def _dirs():
    out = set()
    for dp, dn, _ in os.walk(TREE):  # greatdane/ source tree: full walk (small)
        dn[:] = [d for d in dn if d not in _SKIP]
        out.update(os.path.join(dp, d) for d in dn)
    for top in (HOME, CWD):  # top level only (cheap)
        try:
            out.update(os.path.realpath(e.path) for e in os.scandir(top) if e.is_dir(follow_symlinks=False))
        except OSError:
            pass
    return out


START_DIRS = _dirs()
IGNORE = [os.path.realpath(p) for p in os.environ.get("GD_GUARD_IGNORE", "").split(os.pathsep) if p]
ND = tempfile.mkdtemp(prefix="gd-nodedata-")
_tmp.append(ND)
safe(ND)


def check(where="check"):
    now = _snap()
    bad = [n for n in WATCH if now[n] != BASE[n]]
    if bad:
        sys.stderr.write("gd_guard: FAIL (%s): real %s changed in %s\n" % (where, ", ".join(bad), REAL))
        os._exit(97)
    return True


_DD = re.compile(r'user_pref\(\s*"greatdane\.node\.dataDir"\s*,\s*"((?:[^"\\]|\\.)*)"')


def bad_datadirs():
    """dataDir prefs in created profiles that are not absolute paths inside a mkdtemp root."""
    bad = []
    for d in _tmp:
        for n in ("user.js", "prefs.js"):
            try:
                txt = open(os.path.join(d, n), encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for v in _DD.findall(txt):
                if not os.path.isabs(v) or _forbidden(os.path.realpath(v)) or not inroot(v):
                    bad.append("%s/%s dataDir=%r" % (d, n, v))
    return bad


def stray_dirs():
    """Dirs created during the run in the source tree, the cwd, or $HOME (top level)."""
    return sorted(d for d in _dirs() - START_DIRS
                  if not any(d == i or d.startswith(i + os.sep) for i in IGNORE))


def teardown_problems():
    return ["out-of-root " + b for b in bad_datadirs()] + ["stray dir " + d for d in stray_dirs()]


@atexit.register
def _final():
    check("exit")
    probs = teardown_problems()
    if not os.environ.get("GD_GUARD_KEEP"):
        for d in _tmp:
            shutil.rmtree(d, ignore_errors=True)
    if probs:
        for p in probs:
            sys.stderr.write("gd_guard: FAIL (teardown): %s\n" % p)
        sys.stderr.flush(); sys.stdout.flush()
        os._exit(96)


def _watch():
    import time
    while True:
        time.sleep(2)
        check("during")


import threading as _th
_th.Thread(target=_watch, daemon=True).start()
