#!/usr/bin/env python3
"""Per-binary Developer ID signing and entitlement check for Dane.app.

    sign_dane_macos.py plan  <Dane.app>                 # print the plan; runs anywhere, no codesign
    sign_dane_macos.py sign  <Dane.app> [--dry-run]     # codesign inside-out (macOS); needs DANE_SIGN_IDENTITY
    sign_dane_macos.py check <Dane.app> [--json OUT]    # read-only: per row, entitlements == map, hardened
                                                        # runtime flag, TeamIdentifier MNL79V994R, secure
                                                        # timestamp; then codesign --verify --deep --strict

Map: greatdane/macos/sign-map.tsv. Entitlements: security/mac/hardenedruntime/production/.
Never uses `codesign --deep` to SIGN (only to verify), so no helper inherits the browser's entitlements.
Never notarizes. Refuses the owner's installed app (/Volumes/Dane/...) and any DaneNotarized path.
Optional env: DANE_BROWSER_ENTITLEMENTS=dane.browser.no-dlv.xml selects the stricter main-app alternative.
"""
import fnmatch, json, os, plistlib, subprocess, sys

TREE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MAP = os.path.join(TREE, "greatdane", "macos", "sign-map.tsv")
ENTDIR = os.path.join(TREE, "security", "mac", "hardenedruntime", "production")
RESTRICTED = {"com.apple.application-identifier",
              "com.apple.developer.web-browser.public-key-credential",
              "com.apple.developer.team-identifier"}
FORBIDDEN = {"com.apple.security.get-task-allow",
             "com.apple.security.cs.allow-dyld-environment-variables",
             "com.apple.security.cs.allow-unsigned-executable-memory",
             "com.apple.security.cs.disable-executable-page-protection"}
MACHO = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
         b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"}
TEAM = "MNL79V994R"


def die(msg):
    print("REFUSE: " + msg, file=sys.stderr)
    sys.exit(2)


def guard(app):
    real = os.path.realpath(app)
    if real.startswith("/Volumes/Dane/") or real == "/Volumes/Dane" or "DaneNotarized" in real:
        die("owner's installed/notarized app is off-limits: " + real)
    if not os.path.isfile(os.path.join(real, "Contents", "Info.plist")):
        die("not an app bundle: " + real)
    return real


def load_map():
    rows = []
    for ln, line in enumerate(open(MAP, encoding="utf-8"), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3 or parts[2] not in ("required", "optional"):
            die("bad map line %d: %r" % (ln, line))
        glob, ent, need = parts
        if ent == "-":
            ent = None
        elif glob == "." and os.environ.get("DANE_BROWSER_ENTITLEMENTS"):
            ent = os.environ["DANE_BROWSER_ENTITLEMENTS"]
        rows.append({"glob": glob, "ent": ent, "need": need})
    return rows


def ent_dict(leaf):
    if leaf is None:
        return {}
    p = os.path.join(ENTDIR, leaf)
    if not os.path.isfile(p):
        die("missing entitlements file " + p)
    return plistlib.load(open(p, "rb"))


def seg_match(path, glob):
    """fnmatch per path segment, so '*' never crosses '/'."""
    a, b = path.split("/"), glob.split("/")
    return len(a) == len(b) and all(fnmatch.fnmatchcase(x, y) for x, y in zip(a, b))


def is_macho(p):
    try:
        with open(p, "rb") as f:
            return f.read(4) in MACHO
    except OSError:
        return False


def owner_bundle(app, rel):
    """Return the deepest enclosing .app/.framework (relative), or rel itself for a bare file."""
    parts = rel.split("/")
    best = None
    for i in range(1, len(parts)):
        if parts[i - 1].endswith((".app", ".framework")):
            best = "/".join(parts[:i])
    return best or rel


def plan(app):
    rows = load_map()
    contents = os.path.join(app, "Contents")
    for r in rows:
        if r["glob"] == ".":
            r["matches"] = ["."]
        else:
            r["matches"] = []
    # Candidate signable units: bundles (.app/.framework, not the top app) and bare Mach-O files.
    units = set()
    for dp, dns, fns in os.walk(contents):
        for d in dns:
            if d.endswith((".app", ".framework")):
                units.add(os.path.relpath(os.path.join(dp, d), app))
        for fn in fns:
            fp = os.path.join(dp, fn)
            if not os.path.islink(fp) and is_macho(fp):
                rel = os.path.relpath(fp, app)
                units.add(rel)
    # Bare Mach-O that live inside a nested bundle are covered by that bundle's signature
    # (its main executable) unless a row names them explicitly.
    claimed = {}
    for r in rows:
        if r["glob"] == ".":
            continue
        for u in sorted(units):
            if seg_match(u, r["glob"]):
                if u in claimed:
                    die("%s matches two rows: %s and %s" % (u, claimed[u], r["glob"]))
                claimed[u] = r["glob"]
                r["matches"].append(u)
    main_exe = plistlib.load(open(os.path.join(contents, "Info.plist"), "rb")).get("CFBundleExecutable")
    if main_exe:
        claimed["Contents/MacOS/" + main_exe] = "."  # signed as part of the app (last row)
    unclaimed = []
    for u in sorted(units):
        if u in claimed:
            continue
        enc = owner_bundle(app, u)
        if enc != u and (enc in claimed):
            continue  # inside a bundle that is signed as a unit
        unclaimed.append(u)
    problems = []
    for r in rows:
        if r["need"] == "required" and not r["matches"]:
            problems.append("required row has no match: " + r["glob"])
    if unclaimed:
        problems += ["Mach-O/bundle not covered by the map: " + u for u in unclaimed]
    has_profile = os.path.isfile(os.path.join(contents, "embedded.provisionprofile"))
    for r in rows:
        e = ent_dict(r["ent"])
        bad = FORBIDDEN & set(e)
        if bad:
            problems.append("%s: forbidden entitlements %s" % (r["ent"], sorted(bad)))
        if (RESTRICTED & set(e)) and not has_profile:
            problems.append("%s: restricted entitlements %s without Contents/embedded.provisionprofile"
                            % (r["ent"], sorted(RESTRICTED & set(e))))
        if (RESTRICTED & set(e)) and r["glob"] != ".":
            problems.append("%s: restricted entitlements allowed on the main app only" % r["glob"])
    return rows, problems


def print_plan(rows):
    for r in rows:
        ent = r["ent"] or "(none)"
        keys = sorted(ent_dict(r["ent"]))
        for m in r["matches"]:
            print("%-70s ent=%-28s %s" % (m, ent, ",".join(k.replace("com.apple.security.", "") for k in keys)))


def codesign_ent(path):
    out = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", path],
                         capture_output=True).stdout
    out = out.strip()
    return plistlib.loads(out) if out else {}


def codesign_info(path):
    """(hardened_runtime, team_id, timestamped) from `codesign -dvv`."""
    err = subprocess.run(["codesign", "-dvv", path], capture_output=True, text=True).stderr
    runtime = any(l.startswith("CodeDirectory") and "(runtime)" in l for l in err.splitlines())
    team = next((l.split("=", 1)[1] for l in err.splitlines() if l.startswith("TeamIdentifier=")), None)
    stamped = any(l.startswith("Timestamp=") for l in err.splitlines())
    return runtime, team, stamped


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("plan", "sign", "check"):
        print(__doc__)
        sys.exit(2)
    mode, app = sys.argv[1], guard(sys.argv[2])
    dry = "--dry-run" in sys.argv
    rows, problems = plan(app)
    print("tree:", TREE)
    print("app: ", app)
    print_plan(rows)
    if problems:
        for p in problems:
            print("PROBLEM:", p)
        if mode != "check":
            die("%d problem(s); nothing signed" % len(problems))
    if mode == "plan":
        print("PLAN OK")
        return
    if mode == "sign":
        ident = os.environ.get("DANE_SIGN_IDENTITY", "")
        if not dry and ("(%s)" % TEAM) not in ident:
            die("set DANE_SIGN_IDENTITY to the Developer ID Application identity for team " + TEAM)
        for r in rows:
            for m in r["matches"]:
                cmd = ["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", ident or "<identity>"]
                if r["ent"]:
                    cmd += ["--entitlements", os.path.join(ENTDIR, r["ent"])]
                cmd.append(app if m == "." else os.path.join(app, m))
                print("$", " ".join(cmd))
                if not dry:
                    subprocess.run(cmd, check=True)
        if dry:
            print("DRY RUN: nothing signed")
            return
    # check (also runs after sign)
    fails, report = [], []
    for r in rows:
        want = ent_dict(r["ent"])
        for m in r["matches"]:
            p = app if m == "." else os.path.join(app, m)
            got = codesign_ent(p)
            runtime, team, stamped = codesign_info(p)
            ok = got == want and runtime and team == TEAM and stamped
            report.append({"path": m, "expected": r["ent"], "ok": ok, "got": sorted(got),
                           "runtime": runtime, "team": team, "timestamp": stamped})
            print("%s %-70s runtime=%s team=%s ts=%s got=%s" % ("OK  " if ok else "FAIL", m, runtime, team,
                                                             stamped, sorted(got)))
            if not ok:
                fails.append(m)
    v = subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app],
                       capture_output=True, text=True)
    print(v.stderr.strip())
    if v.returncode != 0:
        fails.append("codesign --verify --deep --strict")
    if "--json" in sys.argv:
        json.dump({"app": app, "rows": report, "verify_rc": v.returncode, "problems": problems},
                  open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
    if fails or problems:
        print("CHECK FAIL:", fails + problems)
        sys.exit(1)
    print("CHECK PASS")


if __name__ == "__main__":
    main()
