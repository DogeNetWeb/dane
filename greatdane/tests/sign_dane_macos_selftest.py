#!/usr/bin/env python3
"""Self-test for greatdane/tools/sign_dane_macos.py. Runs anywhere (Linux or macOS), with no real codesign.

Builds fake Dane.app layouts in a temp dir and puts a MOCK `codesign` first on PATH. Nothing is ever really
signed; the mock only records calls and returns canned `codesign -d` output.
    python3 greatdane/tests/sign_dane_macos_selftest.py [-v]
Exit 0 only if every case behaves as expected.
"""
import os, plistlib, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.abspath(os.path.join(HERE, "..", ".."))
TOOL = os.path.join(TREE, "greatdane", "tools", "sign_dane_macos.py")
ENTDIR = os.path.join(TREE, "security", "mac", "hardenedruntime", "production")
VERBOSE = "-v" in sys.argv
MOCK = r'''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]; p = a[-1] if a else ""
log = os.environ.get("MOCK_LOG")
if log:
    open(log, "a").write(" ".join(a) + "\n")
ents = {"plugin-container.app": "plugin-container.xml", "media-plugin-helper.app": "media-plugin-helper.xml"}
D = os.environ["MOCK_ENTDIR"]
base = os.path.basename(p.rstrip("/"))
if a[:2] == ["-d", "--entitlements"]:
    e = ents.get(base)
    if base == os.environ.get("MOCK_TOP", "Dane.app"):
        e = os.environ.get("MOCK_TOP_ENT", "dane.browser.xml")
    if os.environ.get("MOCK_BAD_GPU") and base == "gpu-helper.app":
        e = "dane.browser.xml"
    if e:
        sys.stdout.buffer.write(open(os.path.join(D, e), "rb").read())
elif a[:1] == ["-dvv"]:
    flags = "0x10000(runtime)" if not os.environ.get("MOCK_NO_RUNTIME") else "0x0(none)"
    sys.stderr.write("CodeDirectory v=20500 size=1 flags=%s hashes=1\n" % flags)
    sys.stderr.write("TeamIdentifier=%s\n" % os.environ.get("MOCK_TEAM", "MNL79V994R"))
    if not os.environ.get("MOCK_NO_TS"):
        sys.stderr.write("Timestamp=Nov 10, 2026 at 4:00:00 PM\n")
elif a[:1] == ["--verify"]:
    sys.stderr.write(p + ": valid on disk\n")
elif "--sign" in a:
    pass  # pretend to sign
'''


def mk(path, data=b"\xcf\xfa\xed\xfe fake-macho"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def mkapp(path, exe):
    os.makedirs(os.path.join(path, "Contents", "MacOS"), exist_ok=True)
    with open(os.path.join(path, "Contents", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleExecutable": exe}, f)
    mk(os.path.join(path, "Contents", "MacOS", exe))


def mkframework(path, name):
    """Real-style framework: Versions/A + Current symlink + top-level symlinks."""
    va = os.path.join(path, "Versions", "A")
    mk(os.path.join(va, name))
    os.makedirs(os.path.join(va, "Resources"), exist_ok=True)
    with open(os.path.join(va, "Resources", "Info.plist"), "wb") as f:
        plistlib.dump({"CFBundleExecutable": name}, f)
    os.symlink("A", os.path.join(path, "Versions", "Current"))
    os.symlink("Versions/Current/" + name, os.path.join(path, name))
    os.symlink("Versions/Current/Resources", os.path.join(path, "Resources"))


def fake_app(root):
    A = os.path.join(root, "Dane.app")
    M = os.path.join(A, "Contents", "MacOS")
    mkapp(A, "greatdane")
    for f in ["XUL", "libmozglue.dylib", "libnss3.dylib", "libfreebl3.dylib", "libsoftokn3.dylib",
              "liblgpllibs.dylib", "libosclientcerts.dylib", "greatdane-node", "pingsender", "nmhproxy",
              "crashhelper"]:
        mk(os.path.join(M, f))
    mkapp(os.path.join(M, "crashreporter.app"), "crashreporter")
    mkapp(os.path.join(M, "plugin-container.app"), "plugin-container")
    mkapp(os.path.join(M, "media-plugin-helper.app"), "Dane Media Plugin Helper")
    mkapp(os.path.join(M, "gpu-helper.app"), "Dane GPU Helper")
    mkapp(os.path.join(M, "updater.app"), "surf.dogecoin.dane.updater")
    mkframework(os.path.join(M, "updater.app", "Contents", "Frameworks", "UpdateSettings.framework"), "UpdateSettings")
    mk(os.path.join(A, "Contents", "Library", "LaunchServices", "surf.dogecoin.dane.updater"))
    mk(os.path.join(A, "Contents", "Library", "LaunchServices", "surf.dogecoin.dane.dmgInstallHelper"))
    mkframework(os.path.join(A, "Contents", "Frameworks", "ChannelPrefs.framework"), "ChannelPrefs")
    mk(os.path.join(A, "Contents", "Resources", "gmp-clearkey", "0.1", "libclearkey.dylib"))
    mk(os.path.join(A, "Contents", "Resources", "omni.ja"), b"PK not macho")
    # symlink to a Mach-O must be ignored (only regular files are units)
    os.symlink("../MacOS/XUL", os.path.join(A, "Contents", "Resources", "XUL-link"))
    return A


results = []


def run(name, args, expect_rc, must=(), mustnot=(), env=None, cwd=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([sys.executable, "-B", TOOL] + args, capture_output=True, text=True, env=e, cwd=cwd)
    out = p.stdout + p.stderr
    ok = p.returncode == expect_rc and all(re.search(m, out) for m in must) and not any(
        re.search(m, out) for m in mustnot)
    results.append((name, ok, p.returncode, expect_rc))
    print("%s %-62s rc=%d (want %d)" % ("PASS" if ok else "FAIL", name, p.returncode, expect_rc))
    if VERBOSE or not ok:
        print("    " + out.strip().replace("\n", "\n    "))
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="dane-signtest-")
    try:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        cs = os.path.join(bindir, "codesign")
        open(cs, "w").write(MOCK)
        os.chmod(cs, 0o755)
        mock = {"PATH": bindir + os.pathsep + os.environ["PATH"], "MOCK_ENTDIR": ENTDIR}
        good = fake_app(os.path.join(tmp, "good"))

        # --- positive ---
        run("P1 plan OK (framework symlinks, symlinked Mach-O ignored)", ["plan", good], 0, [r"PLAN OK"],
            [r"XUL-link", r"PROBLEM"])
        run("P2 sign --dry-run OK", ["sign", good, "--dry-run"], 0, [r"DRY RUN: nothing signed",
            r"<identity redacted; team MNL79V994R>"], [r"--deep"])
        run("P3 check PASS with mock codesign", ["check", good], 0, [r"CHECK PASS"], env=mock)
        jpath = os.path.join(tmp, "ent.json")
        run("P4 check --json writes report", ["check", good, "--json", jpath], 0, [r"CHECK PASS"], env=mock)
        assert os.path.isfile(jpath)
        run("P5 no-DLV main-app variant plan OK", ["plan", good], 0, [r"dane.browser.no-dlv.xml", r"PLAN OK"],
            env={"DANE_BROWSER_ENTITLEMENTS": "dane.browser.no-dlv.xml"})
        logf = os.path.join(tmp, "cs.log")
        ident = "Developer ID Application: Example Person (MNL79V994R)"
        run("P6 mock sign: identity never printed", ["sign", good], 0, [r"CHECK PASS"],
            [r"Example Person"], env=dict(mock, DANE_SIGN_IDENTITY=ident, MOCK_LOG=logf))
        calls = open(logf).read()
        signs = [l for l in calls.splitlines() if "--sign" in l]
        okdeep = all("--deep" not in l for l in signs) and signs and "Dane.app" in signs[-1].split()[-1]
        results.append(("P7 sign calls: no --deep, app signed last", bool(okdeep), 0, 0))
        print("%s %-62s" % ("PASS" if okdeep else "FAIL", "P7 sign calls: no --deep, app signed last"))

        # --- M1: nested non-main Mach-O inside mapped bundles ---
        def variant(tag, rel, data=b"\xcf\xfa\xed\xfe"):
            root = os.path.join(tmp, tag)
            shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
            mk(os.path.join(root, "Dane.app", rel), data)
            return os.path.join(root, "Dane.app")
        a = variant("m1a", "Contents/MacOS/crashreporter.app/Contents/MacOS/minidump-analyzer")
        run("N1 crashreporter.app/Contents/MacOS/minidump-analyzer refused", ["plan", a], 2,
            [r"not covered by the map: Contents/MacOS/crashreporter.app/Contents/MacOS/minidump-analyzer"])
        a = variant("m1b", "Contents/MacOS/plugin-container.app/Contents/Resources/evil.dylib")
        run("N2 plugin-container.app/Contents/Resources/evil.dylib refused", ["plan", a], 2,
            [r"not covered by the map: .*plugin-container.app/Contents/Resources/evil.dylib"])
        a = variant("m1c", "Contents/Frameworks/ChannelPrefs.framework/Versions/A/Helpers/tool")
        run("N3 non-main Mach-O inside framework refused", ["plan", a], 2,
            [r"not covered by the map: .*ChannelPrefs.framework/Versions/A/Helpers/tool"])
        a = variant("m1d", "Contents/MacOS/gpu-helper.app/Contents/MacOS/second-exe")
        run("N4 second executable in mapped .app refused", ["plan", a], 2, [r"second-exe"])
        a = variant("m1e", "Contents/Resources/stray-tool")
        run("N5 stray top-level Mach-O refused", ["plan", a], 2, [r"stray-tool"])
        root = os.path.join(tmp, "m1f"); shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
        mkapp(os.path.join(root, "Dane.app", "Contents", "MacOS", "plugin-container.app", "Contents", "Helpers",
                           "nested.app"), "nested")
        run("N6 unmapped nested bundle inside mapped bundle refused", ["plan", os.path.join(root, "Dane.app")], 2,
            [r"nested.app"])
        root = os.path.join(tmp, "m1g"); shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
        shutil.rmtree(os.path.join(root, "Dane.app", "Contents", "MacOS", "media-plugin-helper.app"))
        run("N7 required helper missing refused", ["plan", os.path.join(root, "Dane.app")], 2,
            [r"required row has no match: Contents/MacOS/media-plugin-helper.app"])

        # --- entitlement policy ---
        run("N8 restricted entitlements without profile refused", ["sign", good, "--dry-run"], 2,
            [r"restricted entitlements .* without Contents/embedded.provisionprofile"],
            env={"DANE_BROWSER_ENTITLEMENTS": "firefox.browser.xml"})
        run("N9 sign without identity refused", ["sign", good], 2, [r"set DANE_SIGN_IDENTITY"])
        run("N10 --json without a value refused (no traceback)", ["check", good, "--json"], 2,
            [r"--json needs a value"], [r"Traceback"], env=mock)

        # --- M2: path guard ---
        for i, pth in enumerate(["/Volumes/Dane/Dane.app", "/Volumes/Dane 1/Dane.app", "/Volumes/Dane-1/Dane.app",
                                 "/volumes/dane/Dane.app", "/Volumes/DANE/Dane.app", "/Volumes/Dane 12/x/Dane.app",
                                 "/System/Volumes/Data/Volumes/Dane/Dane.app",
                                 os.path.join(tmp, "x", "danenotarized", "Dane.app"),
                                 os.path.join(tmp, "DaneNotarized.app"),
                                 os.path.join(tmp, "Library", "Application Support", "GreatDANE", "x.app")]):
            run("G%d owner path refused: %s" % (i + 1, pth.replace(tmp, "<tmp>")), ["plan", pth], 2,
                [r"REFUSE: off-limits"])
        run("G11 other /Volumes path refused without allowlist", ["plan", "/Volumes/Other/Dane.app"], 2,
            [r"need --allow-volume"])
        run("G12 allowlisted /Volumes dir passes guard", ["plan", "/Volumes/Other/w/Dane.app", "--allow-volume",
            "/Volumes/Other"], 2, [r"not an app bundle"], [r"need --allow-volume"])
        run("G13 allowlist via env passes guard", ["plan", "/Volumes/Other/w/Dane.app"], 2, [r"not an app bundle"],
            env={"DANE_SIGN_ALLOW_VOLUMES": "/tmp/nothing:/Volumes/Other"})
        run("G14 allowlisting the owner volume is refused", ["plan", "/Volumes/Other/Dane.app", "--allow-volume",
            "/Volumes/Dane"], 2, [r"allowlist entry is itself off-limits"])
        run("G15 owner path refused even if allowlisted", ["plan", "/Volumes/Dane 1/Dane.app", "--allow-volume",
            "/Volumes/Dane 1"], 2, [r"off-limits"])
        run("G16 '/Volumes/Danes' prefix is NOT the owner volume (needs allowlist)",
            ["plan", "/Volumes/Danes/Dane.app"], 2, [r"need --allow-volume"], [r"off-limits"])

        # --- L5: failing mocks for check ---
        run("C1 check FAIL: no hardened runtime", ["check", good], 1, [r"no hardened runtime", r"CHECK FAIL"],
            env=dict(mock, MOCK_NO_RUNTIME="1"))
        run("C2 check FAIL: wrong team", ["check", good], 1, [r"team ABCDE12345 != MNL79V994R", r"CHECK FAIL"],
            env=dict(mock, MOCK_TEAM="ABCDE12345"))
        run("C3 check FAIL: no secure timestamp", ["check", good], 1, [r"no secure timestamp", r"CHECK FAIL"],
            env=dict(mock, MOCK_NO_TS="1"))
        run("C4 check FAIL: helper with browser entitlements", ["check", good], 1,
            [r"FAIL Contents/MacOS/gpu-helper.app"], env=dict(mock, MOCK_BAD_GPU="1"))

        # --- L3: team ID from one config file ---
        conf = os.path.join(tmp, "signing-mismatch.conf")
        open(conf, "w").write("TEAM_ID=ABCDE12345\n")
        run("T1 signing.conf team mismatch fails check", ["check", good], 1,
            [r"team MNL79V994R != ABCDE12345", r"CHECK FAIL"], env=dict(mock, DANE_SIGNING_CONF=conf))
        bad = os.path.join(tmp, "signing-bad.conf")
        open(bad, "w").write("TEAM_ID=nope\n")
        run("T2 malformed signing.conf refused", ["plan", good], 2, [r"TEAM_ID .* must be"],
            env={"DANE_SIGNING_CONF": bad})
        cfg = os.path.join(TREE, "build", "moz.configure", "update-programs.configure")
        team = re.search(r"^TEAM_ID=(\S+)", open(os.path.join(TREE, "greatdane", "macos", "signing.conf")).read(), re.M).group(1)
        if os.path.isfile(cfg):
            ous = re.findall(r'subject\.OU\]\s*=\s*\\?"([A-Z0-9]{10})', open(cfg).read())
            ok = bool(ous) and all(o == team for o in ous)
            results.append(("T3 update-programs.configure OU == signing.conf", ok, 0, 0))
            print("%s %-62s %s" % ("PASS" if ok else "FAIL", "T3 update-programs.configure OU == signing.conf", ous))
        else:
            print("SKIP T3 update-programs.configure not in this tree")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print("\n%d cases, %d passed, %d failed" % (len(results), len(results) - len(failed), len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
