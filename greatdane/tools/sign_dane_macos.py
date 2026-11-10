#!/usr/bin/env python3
"""Per-binary Developer ID signing and entitlement check for Dane.app.

    sign_dane_macos.py plan  <Dane.app> [--allow-volume DIR]...            # print the plan; no codesign needed
    sign_dane_macos.py sign  <Dane.app> [--dry-run] [--allow-volume DIR]... # codesign inside-out (macOS);
                                                                            # needs DANE_SIGN_IDENTITY
    sign_dane_macos.py check <Dane.app> [--json OUT] [--strict] [--allow-volume DIR]...
        read-only: for each row, entitlements == map, hardened-runtime flag, TeamIdentifier == TEAM_ID from
        greatdane/macos/signing.conf, secure timestamp; then codesign --verify --deep --strict
    sign_dane_macos.py guard-path <path>...   # owner-path rules only (used by sign-only.sh); rc 2 if refused
  Common options: --allow-volume DIR (must be under /Volumes), --work-dir DIR (see owner bundle-ID rule).

Ad-hoc (throwaway check runs only): DANE_SIGN_IDENTITY=- signs with "-" (no --timestamp, no keychain) but keeps
--options runtime and the per-binary entitlements. `check` then reports ad-hoc rows as "expected, not Developer
ID" (team/timestamp not required) and prints CHECK PASS (AD-HOC ...). With --strict or DANE_SIGN_STRICT=1, an
ad-hoc signature FAILS check. A mix of ad-hoc and Developer ID rows always fails.

Map: greatdane/macos/sign-map.tsv. Entitlements: security/mac/hardenedruntime/production/.
Team ID: greatdane/macos/signing.conf (TEAM_ID=...); env DANE_SIGNING_CONF overrides the path (tests).
Never uses `codesign --deep` to SIGN (only to verify), so no helper inherits the browser's entitlements.
Never notarizes. The signing identity is never printed.

Path guard (case-insensitive, on the realpath):
  - /System/Volumes/Data/<x> is treated as /<x> before every rule (firmlinks).
  - always refused: /Volumes/Dane, plus " N" / "-N" variants (the owner's installed app); any path component
    containing "danenotarized"; anything under "Application Support/GreatDANE"; anything under /Applications
    or ~/Applications (installed apps); anything inside an attached disk image (per `hdiutil info`) whose image
    file name contains "dane" or whose mount holds a top-level Dane.app (owner dmg on a custom mount point).
  - a Dane.app whose CFBundleIdentifier is an owner ID (surf.dogecoin.dane, org.mozilla.surf.pepecoin.greatdane)
    is refused unless it is inside this source tree (e.g. obj-gd/dist/gd-release/stage-*) or a --work-dir DIR /
    env DANE_SIGN_WORK_DIRS entry.
  - anything else under /Volumes is refused unless it is under a directory given with --allow-volume DIR or in
    env DANE_SIGN_ALLOW_VOLUMES (colon-separated). Allowlist entries must themselves be under /Volumes (rc 2
    otherwise). The owner rules above still apply inside an allowed dir.
  - plan refuses any symlink inside the bundle that resolves outside the bundle.
Optional env: DANE_BROWSER_ENTITLEMENTS=dane.browser.no-dlv.xml selects the stricter main-app alternative.
"""
import fnmatch, json, os, plistlib, re, shutil, subprocess, sys

TREE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MAP = os.path.join(TREE, "greatdane", "macos", "sign-map.tsv")
CONF = os.environ.get("DANE_SIGNING_CONF") or os.path.join(TREE, "greatdane", "macos", "signing.conf")
ENTDIR = os.path.join(TREE, "security", "mac", "hardenedruntime", "production")
RESTRICTED = {"com.apple.application-identifier",
              "com.apple.developer.web-browser.public-key-credential",
              "com.apple.developer.team-identifier"}
FORBIDDEN = {"com.apple.security.get-task-allow",
             "com.apple.security.cs.allow-dyld-environment-variables",
             "com.apple.security.cs.allow-unsigned-executable-memory",
             "com.apple.security.cs.disable-executable-page-protection"}
MACHO = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
         b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"}
BUNDLE_EXT = (".app", ".framework", ".xpc", ".appex", ".bundle", ".plugin")
OWNER_VOLUME = re.compile(r"^dane([ -]\d+)?$")
OWNER_BUNDLE_IDS = {"surf.dogecoin.dane", "org.mozilla.surf.pepecoin.greatdane"}


def die(msg):
    print("REFUSE: " + msg, file=sys.stderr)
    sys.exit(2)


def load_conf():
    conf = {}
    if not os.path.isfile(CONF):
        die("missing signing config " + CONF)
    for line in open(CONF, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()
    if not re.fullmatch(r"[A-Z0-9]{10}", conf.get("TEAM_ID", "")):
        die("TEAM_ID in %s must be a 10-character Apple team ID" % CONF)
    return conf


TEAM = load_conf()["TEAM_ID"]


def arg_values(flag):
    out, a = [], sys.argv
    for i, x in enumerate(a):
        if x == flag:
            if i + 1 >= len(a) or a[i + 1].startswith("--"):
                die(flag + " needs a value")
            out.append(a[i + 1])
    return out


def norm(p):
    p = os.path.realpath(p)
    low = p.lower()
    # macOS firmlinks: /System/Volumes/Data/<x> is the same place as /<x> (/Volumes, /Applications, /Users, ...),
    # so strip the prefix before any owner-path rule (round 4, L-b).
    if low == "/system/volumes/data":
        return "/"
    if low.startswith("/system/volumes/data/"):
        p = p[len("/System/Volumes/Data"):]
    return p


def under(path, root):
    a, b = path.lower().rstrip("/"), root.lower().rstrip("/")
    return a == b or a.startswith(b + "/")


def attached_images():
    """[(image_path, [mount points])] from `hdiutil info -plist`; [] where hdiutil is absent (non-macOS)."""
    if not shutil.which("hdiutil"):
        return []
    try:
        out = subprocess.run(["hdiutil", "info", "-plist"], capture_output=True, timeout=60).stdout
        info = plistlib.loads(out)
    except Exception:
        die("could not read `hdiutil info -plist`; refusing rather than guessing about mounted images")
    res = []
    for im in info.get("images", []):
        mps = [e["mount-point"] for e in im.get("system-entities", []) if e.get("mount-point")]
        res.append((im.get("image-path", ""), mps))
    return res


def owner_reason(real, images=None):
    low = real.lower().rstrip("/")
    parts = low.split("/")
    if len(parts) >= 3 and parts[1] == "volumes" and OWNER_VOLUME.match(parts[2]):
        return "owner's Dane volume (/Volumes/Dane and variants)"
    if any("danenotarized" in c for c in parts):
        return "DaneNotarized path"
    if "/application support/greatdane" in low:
        return "owner's GreatDANE profile/data"
    if under(low, "/applications") or re.match(r"^/users/[^/]+/applications(/|$)", low):
        return "installed app location (/Applications or ~/Applications)"
    for img, mps in (attached_images() if images is None else images):
        for mp in mps:
            mpr = norm(mp)
            if under(real, mpr) and ("dane" in os.path.basename(img).lower()
                                     or os.path.isdir(os.path.join(mpr, "Dane.app"))):
                return "inside attached disk image %s mounted at %s (owner dmg)" % (os.path.basename(img), mpr)
    return None


def list_dirs(flag, env):
    out = [norm(x) for x in arg_values(flag)]
    out += [norm(x) for x in os.environ.get(env, "").split(":") if x]
    return out


def guard(app):
    images = attached_images()
    real = norm(app)
    why = owner_reason(real, images)
    if why:
        die("off-limits (%s): %s" % (why, real))
    allowed = list_dirs("--allow-volume", "DANE_SIGN_ALLOW_VOLUMES")
    for a in allowed:
        if owner_reason(a, images):
            die("allowlist entry is itself off-limits: " + a)
        if not under(a, "/volumes") or a.lower().rstrip("/") == "/volumes":
            die("allowlist entry must be a directory under /Volumes: " + a)
    work = list_dirs("--work-dir", "DANE_SIGN_WORK_DIRS")
    for w in work:
        if owner_reason(w, images):
            die("work-dir entry is itself off-limits: " + w)
    if under(real, "/volumes") and not any(under(real, a) for a in allowed):
        die("paths under /Volumes need --allow-volume DIR or DANE_SIGN_ALLOW_VOLUMES: " + real)
    ip = os.path.join(real, "Contents", "Info.plist")
    if not os.path.isfile(ip):
        die("not an app bundle: " + real)
    bid = plistlib.load(open(ip, "rb")).get("CFBundleIdentifier", "")
    if bid in OWNER_BUNDLE_IDS and not under(real, norm(TREE)) and not any(under(real, w) for w in work):
        die("a %s Dane.app outside this tree and the --work-dir/DANE_SIGN_WORK_DIRS dirs looks like an installed"
            " or downloaded owner copy: %s" % (bid, real))
    return real


def guard_paths(paths):
    """Owner rules only (no app-bundle or /Volumes-allowlist requirement): for sign-only.sh source/target paths."""
    images = attached_images()
    bad = 0
    for p in paths:
        real = norm(p)
        why = owner_reason(real, images)
        if why:
            print("REFUSE: off-limits (%s): %s" % (why, real), file=sys.stderr)
            bad += 1
    sys.exit(2 if bad else 0)


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


def enclosing_bundle(rel):
    """Deepest enclosing bundle directory of rel (relative to the app), or None."""
    parts = rel.split("/")
    best = None
    for i in range(1, len(parts)):
        if parts[i - 1].endswith(BUNDLE_EXT):
            best = "/".join(parts[:i])
    return best


def bundle_main_executables(app, bundle_rel):
    """Main executable path(s) (relative) of a bundle, from its own Info.plist CFBundleExecutable.

    .app: Contents/Info.plist -> Contents/MacOS/<exe>.
    .framework: Versions/*/Resources/Info.plist (or Resources/Info.plist) -> Versions/*/<exe>.
    Falls back to the framework name only for .framework bundles with no Info.plist.
    """
    b = os.path.join(app, bundle_rel)
    out = set()
    if bundle_rel.endswith(".framework"):
        # Only the version that Versions/Current points at is exempt; any other real version's binary must have
        # its own map row (none do), so a second framework version is refused.
        vdir = os.path.join(b, "Versions")
        cur = None
        if os.path.isdir(vdir):
            cl = os.path.join(vdir, "Current")
            real_versions = [v for v in os.listdir(vdir) if not os.path.islink(os.path.join(vdir, v))
                             and os.path.isdir(os.path.join(vdir, v))]
            if os.path.islink(cl):
                t = os.readlink(cl).rstrip("/")
                if "/" not in t and t in real_versions:
                    cur = t
            elif len(real_versions) == 1:
                cur = real_versions[0]
        name = None
        for cand in ([os.path.join(vdir, cur, "Resources", "Info.plist")] if cur else []) + [
                os.path.join(b, "Resources", "Info.plist")]:
            if os.path.isfile(cand):
                name = plistlib.load(open(cand, "rb")).get("CFBundleExecutable")
                if name:
                    break
        name = name or os.path.basename(bundle_rel)[: -len(".framework")]
        if cur:
            out.add("%s/Versions/%s/%s" % (bundle_rel, cur, name))
        out.add("%s/%s" % (bundle_rel, name))
    else:
        ip = os.path.join(b, "Contents", "Info.plist")
        if os.path.isfile(ip):
            exe = plistlib.load(open(ip, "rb")).get("CFBundleExecutable")
            if exe:
                out.add("%s/Contents/MacOS/%s" % (bundle_rel, exe))
    return out


def plan(app):
    rows = load_map()
    contents = os.path.join(app, "Contents")
    for r in rows:
        r["matches"] = ["."] if r["glob"] == "." else []
    # Signable units: nested bundles and every regular (non-symlink) Mach-O file.
    units = set()
    escapes = []
    for dp, dns, fns in os.walk(contents):
        for n in dns + fns:
            full = os.path.join(dp, n)
            if os.path.islink(full):
                tgt = os.path.realpath(full)
                if not under(tgt, app):
                    escapes.append("%s -> %s" % (os.path.relpath(full, app), tgt))
        for d in dns:
            full = os.path.join(dp, d)
            if d.endswith(BUNDLE_EXT) and not os.path.islink(full):
                units.add(os.path.relpath(full, app))
        for fn in fns:
            fp = os.path.join(dp, fn)
            if not os.path.islink(fp) and is_macho(fp):
                units.add(os.path.relpath(fp, app))
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
    # Allowed without a row: ONLY the main executable named by the CFBundleExecutable of the app itself, or of
    # the mapped bundle that directly encloses the file. Every other Mach-O must have its own row.
    main_ok = set()
    top = plistlib.load(open(os.path.join(contents, "Info.plist"), "rb")).get("CFBundleExecutable")
    if top:
        main_ok.add("Contents/MacOS/" + top)
    for u in list(claimed):
        if u.endswith(BUNDLE_EXT):
            main_ok |= bundle_main_executables(app, u)
    unclaimed = []
    for u in sorted(units):
        if u in claimed:
            continue
        enc = enclosing_bundle(u)
        if u in main_ok and (enc is None or enc in claimed):
            continue
        unclaimed.append(u)
    problems = []
    for r in rows:
        if r["need"] == "required" and not r["matches"]:
            problems.append("required row has no match: " + r["glob"])
    problems += ["Mach-O/bundle not covered by the map: " + u for u in unclaimed]
    problems += ["symlink escapes the bundle: " + e for e in escapes]
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
    """(hardened_runtime, team_id, timestamped, adhoc) from `codesign -dvv`."""
    err = subprocess.run(["codesign", "-dvv", path], capture_output=True, text=True).stderr
    lines = err.splitlines()
    # flags=0x10000(runtime) for Developer ID; 0x10002(adhoc,runtime) for ad-hoc with hardened runtime
    cdflags = [set(m.split(",")) for l in lines if l.startswith("CodeDirectory")
               for m in re.findall(r"flags=0x[0-9a-fA-F]+\(([^)]*)\)", l)]
    runtime = any("runtime" in f for f in cdflags)
    team = next((l.split("=", 1)[1].strip() for l in lines if l.startswith("TeamIdentifier=")), None)
    stamped = any(l.startswith("Timestamp=") for l in lines)
    adhoc = any(l.strip() == "Signature=adhoc" for l in lines) or any("adhoc" in f for f in cdflags)
    return runtime, team, stamped, adhoc


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "guard-path":
        guard_paths([a for a in sys.argv[2:] if not a.startswith("--")])
    if len(sys.argv) < 3 or sys.argv[1] not in ("plan", "sign", "check"):
        print(__doc__)
        sys.exit(2)
    mode, app = sys.argv[1], guard(sys.argv[2])
    strict = "--strict" in sys.argv or os.environ.get("DANE_SIGN_STRICT") == "1"
    dry = "--dry-run" in sys.argv
    json_out = arg_values("--json")
    json_out = json_out[-1] if json_out else None
    rows, problems = plan(app)
    print("tree:", TREE)
    print("app: ", app)
    print("team:", TEAM, "(from %s)" % os.path.relpath(CONF, TREE) if CONF.startswith(TREE) else CONF)
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
        adhoc_sign = ident == "-"
        if not dry and not adhoc_sign and ("(%s)" % TEAM) not in ident:
            die("set DANE_SIGN_IDENTITY to the Developer ID Application identity for team " + TEAM
                + " (or '-' for an ad-hoc throwaway check run)")
        shown = "- (ad-hoc)" if adhoc_sign else "<identity redacted; team %s>" % TEAM
        for r in rows:
            for m in r["matches"]:
                tail = []
                if r["ent"]:
                    tail += ["--entitlements", os.path.join(ENTDIR, r["ent"])]
                tail.append(app if m == "." else os.path.join(app, m))
                base = ["codesign", "--force"] + ([] if adhoc_sign else ["--timestamp"]) + [
                    "--options", "runtime", "--sign"]
                print("$", " ".join(base + [shown] + tail))
                if not dry:
                    r2 = subprocess.run(base + [ident] + tail, capture_output=True, text=True)
                    if r2.returncode != 0:
                        print((r2.stderr or "").replace(ident, shown) if not adhoc_sign else r2.stderr or "",
                              file=sys.stderr)
                        die("codesign failed (rc %d) on %s" % (r2.returncode, m))
        if dry:
            print("DRY RUN: nothing signed")
            return
    # check (also runs after sign)
    fails, report, kinds = [], [], set()
    for r in rows:
        want = ent_dict(r["ent"])
        for m in r["matches"]:
            p = app if m == "." else os.path.join(app, m)
            got = codesign_ent(p)
            runtime, team, stamped, adhoc = codesign_info(p)
            kinds.add("adhoc" if adhoc else "devid")
            checks = [("entitlements", got != want), ("no hardened runtime", not runtime)]
            if adhoc and strict:
                checks.append(("ad-hoc signature (strict: Developer ID required)", True))
            if not adhoc or strict:
                checks += [("team %s != %s" % (team, TEAM), team != TEAM), ("no secure timestamp", not stamped)]
            why = [w for w, bad in checks if bad]
            ok = not why
            note = "  (ad-hoc: expected, not Developer ID)" if adhoc and ok else ""
            report.append({"path": m, "expected": r["ent"], "ok": ok, "why": why, "got": sorted(got),
                           "runtime": runtime, "team": team, "timestamp": stamped, "adhoc": adhoc})
            print("%s %-70s runtime=%s team=%s ts=%s got=%s%s%s" % (
                "OK  " if ok else "FAIL", m, runtime, team, stamped, sorted(got), note,
                "" if ok else "  <- " + "; ".join(why)))
            if not ok:
                fails.append(m)
    if kinds == {"adhoc", "devid"}:
        fails.append("mixed ad-hoc and Developer ID signatures")
    v = subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app],
                       capture_output=True, text=True)
    print(v.stderr.strip())
    if v.returncode != 0:
        fails.append("codesign --verify --deep --strict")
    if json_out:
        with open(json_out, "w") as f:
            json.dump({"app": app, "team": TEAM, "rows": report, "verify_rc": v.returncode,
                       "problems": problems, "strict": strict, "adhoc": kinds == {"adhoc"}}, f, indent=1)
    if fails or problems:
        print("CHECK FAIL:", fails + problems)
        sys.exit(1)
    if kinds == {"adhoc"}:
        print("CHECK PASS (AD-HOC: expected-not-Developer-ID; NOT distributable, NOT notarizable)")
        return
    print("CHECK PASS")


if __name__ == "__main__":
    main()
