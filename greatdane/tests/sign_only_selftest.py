#!/usr/bin/env python3
"""Self-test for greatdane/tools/sign-only.sh. Runs on Linux or macOS with NO real signing.

Copies the scripts, map, signing.conf and entitlements into a temp tree and puts stub ditto, xattr, hdiutil,
security and a MOCK codesign first on PATH (the mock is shared with sign_dane_macos_selftest.py). It checks
the R2-M3 DANE_ARCH allowlist (before any rm), the existing-dmg refusal, realpath owner guards, and an
ad-hoc vs Developer ID run end to end.
    python3 greatdane/tests/sign_only_selftest.py [-v]
"""
import os, plistlib, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import sign_dane_macos_selftest as base  # noqa: E402  (MOCK codesign, fake_app, TEAM)

VERBOSE = "-v" in sys.argv
results = []
STUBS = {
    "ditto": '#!/bin/sh\nwhile [ "${1#--}" != "$1" ]; do shift; done\ncp -a "$1" "$2"\n',
    "xattr": "#!/bin/sh\nexit 0\n",
    "hdiutil": '#!/bin/sh\nif [ "$1" = info ]; then printf \'<?xml version="1.0"?><plist version="1.0"><dict>'
               '<key>images</key><array/></dict></plist>\'; exit 0; fi\n'
               'if [ "$1" = create ]; then for a; do last=$a; done; echo fake-dmg > "$last"; exit 0; fi\nexit 1\n',
    "security": '#!/bin/sh\necho "  1) ABCDEF \\"Developer ID Application: Example Person (%s)\\""\n'
                'echo "     1 valid identities found"\n' % base.TEAM,
}


def run(name, env, expect_rc, must=(), mustnot=(), post=None):
    e = dict(os.environ)
    e.update(env)
    p = subprocess.run(["bash", SCRIPT], capture_output=True, text=True, env=e)
    out = p.stdout + p.stderr
    ok = p.returncode == expect_rc and all(re.search(m, out) for m in must) and not any(
        re.search(m, out) for m in mustnot)
    if ok and post:
        ok = bool(post())
    results.append((name, ok))
    print("%s %-66s rc=%d (want %d)" % ("PASS" if ok else "FAIL", name, p.returncode, expect_rc))
    if VERBOSE or not ok:
        print("    " + out.strip().replace("\n", "\n    "))


def main():
    global SCRIPT
    tmp = tempfile.mkdtemp(prefix="dane-signonly-test-")
    try:
        G = os.path.join(tmp, "build")
        T = os.path.join(G, "firefox-esr153")
        for rel in ["greatdane/tools", "greatdane/macos", "security/mac/hardenedruntime/production"]:
            shutil.copytree(os.path.join(TREE, rel), os.path.join(T, rel))
        os.makedirs(os.path.join(T, "browser", "config"))
        open(os.path.join(T, "browser", "config", "version_display.txt"), "w").write("153.7.0esr\n")
        open(os.path.join(G, "dane-policies.json"), "w").write('{"policies": {}}\n')
        SCRIPT = os.path.join(T, "greatdane", "tools", "sign-only.sh")
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        for n, body in dict(STUBS, codesign=base.MOCK).items():
            open(os.path.join(bindir, n), "w").write(body)
            os.chmod(os.path.join(bindir, n), 0o755)
        src = base.fake_app(os.path.join(tmp, "src"))
        node = os.path.join(tmp, "greatdane-node")
        base.mk(node)
        os.chmod(node, 0o755)
        out = os.path.join(T, "obj-gd", "dist", "gd-release")
        log = os.path.join(tmp, "cs.log")
        env = {"PATH": bindir + os.pathsep + os.environ["PATH"], "MOCK_ENTDIR": base.ENTDIR, "MOCK_TEAM": base.TEAM,
               "MOCK_LOG": log, "DANE_APP_SRC": src, "DANE_NODE": node}

        # R2-M3: DANE_ARCH allowlist before any rm
        sentinel = os.path.join(out, "keep", "file")
        os.makedirs(os.path.dirname(sentinel))
        open(sentinel, "w").write("x")
        for i, arch in enumerate(["../keep", "universal/../../keep", "universal; rm -rf /", "nope", "Universal", "x86_64 "]):
            run("O%d DANE_ARCH=%r refused before any rm" % (i + 1, arch), dict(env, DANE_ARCH=arch), 2,
                [r"DANE_ARCH must be exactly"], post=lambda: os.path.isfile(sentinel))
        # existing dmg is never overwritten
        dmg = os.path.join(out, "Dane-153.7.0esr-mac-universal.dmg")
        open(dmg, "w").write("OLD")
        run("O7 existing dmg refused and left untouched", env, 2, [r"dmg already exists, not overwriting"],
            post=lambda: open(dmg).read() == "OLD" and not os.path.exists(os.path.join(out, "stage-universal")))
        os.remove(dmg)
        # realpath owner guards on source/target
        link = os.path.join(tmp, "innocent-link")
        os.symlink("/Volumes/Dane 1/Dane.app", link)
        run("O8 DANE_APP_SRC symlink to /Volumes/Dane 1 refused (realpath)", dict(env, DANE_APP_SRC=link), 2,
            [r"off-limits .*Dane 1"])
        run("O9 DANE_APP_SRC=/Applications/Dane.app refused", dict(env, DANE_APP_SRC="/Applications/Dane.app"), 2,
            [r"installed app location"])
        link2 = os.path.join(tmp, "out-link")
        os.symlink(os.path.join(tmp, "x", "DaneNotarized"), link2)
        run("O10 DANE_OUT symlink into DaneNotarized refused (realpath)", dict(env, DANE_OUT=link2), 2,
            [r"DaneNotarized"])
        run("O11 DANE_OUT=/ refused as too broad", dict(env, DANE_OUT="/"), 2, [r"DANE_OUT too broad"])
        run("O12 DANE_APP_SRC inside the stage dir refused", dict(env, DANE_OUT=os.path.join(tmp, "o12"),
            DANE_APP_SRC=os.path.join(tmp, "o12", "stage-universal", "Dane.app")), 2, [r"inside the stage dir"])
        e = dict(os.environ, **env)
        p = subprocess.run(["bash", SCRIPT, "--legacy"], capture_output=True, text=True, env=e)
        ok = p.returncode == 2 and "takes no arguments" in p.stderr
        results.append(("O18 legacy-style arguments refused", ok))
        print("%s %-66s rc=%d (want 2)" % ("PASS" if ok else "FAIL", "O18 legacy-style arguments refused", p.returncode))
        # dry run
        run("O13 dry run: stage + plan + codesign lines, no dmg", dict(env, DANE_DRY_RUN="1"), 0,
            [r"PLAN OK", r"DRY RUN: nothing signed, no dmg"], [r"\$ codesign .*--deep"],
            post=lambda: not os.path.exists(dmg) and os.path.isfile(os.path.join(
                out, "stage-universal", "Dane.app", "Contents", "Resources", "distribution", "policies.json")))
        # ad-hoc end to end
        open(log, "w").close()
        adm = os.path.join(out, "Dane-153.7.0esr-mac-universal-ADHOC.dmg")
        run("O14 ad-hoc run: CHECK PASS (AD-HOC), -ADHOC dmg, no timestamp",
            dict(env, DANE_SIGN_IDENTITY="-", MOCK_ADHOC="1"), 0,
            [r"AD-HOC throwaway", r"CHECK PASS \(AD-HOC", r"done \(AD-HOC"], [r"\$ codesign .*--deep", r"check .*--strict"],
            post=lambda: os.path.isfile(adm) and all("--timestamp" not in l for l in open(log) if "--sign" in l)
            and any(l.split()[-1] == adm for l in open(log) if "--sign" in l))
        run("O15 second ad-hoc run refuses the existing -ADHOC dmg", dict(env, DANE_SIGN_IDENTITY="-",
            MOCK_ADHOC="1"), 2, [r"dmg already exists"])
        # Developer ID run (keychain via stub security) uses check --strict
        open(log, "w").close()
        run("O16 Developer ID run: identity from keychain stub, check --strict PASS, identity never printed", env, 0,
            [r"(?m)^CHECK PASS$", r"done \(NOT notarized\)"], [r"Example Person", r"AD-HOC"],
            post=lambda: os.path.isfile(dmg) and any("--timestamp" in l and l.split()[-1] == dmg for l in open(log)))
        os.remove(dmg)
        shutil.rmtree(os.path.join(out, "stage-universal"))
        run("O17 Developer ID run where codesign produced ad-hoc FAILS (strict)", dict(env, MOCK_ADHOC="1"), 1,
            [r"strict: Developer ID required", r"CHECK FAIL"], post=lambda: not os.path.exists(dmg))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print("\n%d cases, %d passed, %d failed" % (len(results), len(results) - len(failed), len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
