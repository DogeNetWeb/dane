"""gd_guard: safety guard for Dane test suites.

Import first in every suite. On import it:
  * snapshots sha256+mtime of the REAL GreatDANE profiles.ini / installs.ini
    and fails the suite (exit 97) at exit, or on check(), if they changed;
  * creates throwaway mktemp dirs: gd_guard.profile(prefix) and gd_guard.ND
    (node data dir), refusing any path inside the real GreatDANE dir or real
    node data dirs.
Env (testing the guard only): GD_GUARD_REAL_DIR overrides the watched dir,
e.g. to point at a COPY.
"""
import atexit, hashlib, os, shutil, sys, tempfile

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


def safe(path):
    rp = os.path.realpath(path)
    for f in FORBIDDEN:
        if rp == f or rp.startswith(f + os.sep):
            sys.exit("gd_guard: REFUSING path inside real data dir: %s (%s)" % (path, f))
    if not rp.startswith(os.path.realpath(tempfile.gettempdir())):
        sys.exit("gd_guard: REFUSING non-throwaway path: %s" % path)
    return path


def profile(prefix="gd-test-"):
    d = tempfile.mkdtemp(prefix=prefix)
    _tmp.append(d)
    return safe(d)


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


@atexit.register
def _final():
    check("exit")
    if not os.environ.get("GD_GUARD_KEEP"):
        for d in _tmp:
            shutil.rmtree(d, ignore_errors=True)


def _watch():
    import time
    while True:
        time.sleep(2)
        check("during")


import threading as _th
_th.Thread(target=_watch, daemon=True).start()
