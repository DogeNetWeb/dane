#!/usr/bin/env python3
"""Self-test for greatdane/tools/sign_dane_macos.py (team ID read from greatdane/macos/signing.conf). Runs anywhere (Linux or macOS), with no real codesign.

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
CONF = os.path.join(TREE, "greatdane", "macos", "signing.conf")
TEAM = re.search(r"^TEAM_ID=(\S+)", open(CONF).read(), re.M).group(1)  # single source of truth (L3)
# Round 4c L1: flag text the tests must NOT see in the signer's output, built at runtime (no literal in this file,
# so the legacy-signing guard needs no waiver for it).
DEEP_FLAG = "".join(["-", "-", "de", "ep"])
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
    only = os.environ.get("MOCK_ADHOC_ONLY")
    adhoc = os.environ.get("MOCK_ADHOC") or (only and base == only)
    if adhoc:
        flags = flags.replace("0x10000(runtime)", "0x10002(adhoc,runtime)")
    sys.stderr.write("CodeDirectory v=20500 size=1 flags=%s hashes=1\n" % flags)
    if adhoc:
        sys.stderr.write("Signature=adhoc\nTeamIdentifier=not set\n")
    else:
        sys.stderr.write("TeamIdentifier=%s\n" % os.environ["MOCK_TEAM"])
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

GUARD = os.path.join(TREE, "greatdane", "tests", "no_legacy_deep_sign_check.py")
# Fixture text uses placeholders that are substituted at runtime, so these lines never look like commands to the
# guard when it scans greatdane/tests itself.
PH = {"@D@": DEEP_FLAG, "@V@": "-" * 2 + "verify", "@SO@": "".join(["sign-", "only.sh"]),
      "@BU@": "".join(["build-", "universal.sh"]), "@NO@": "".join(["notar", "ize.sh"]),
      "@BEP@": ".".join(["browser", "entitlements", "plist"]), "@SOG@": "".join(["sign-o", "*.sh"])}


def fx(text):
    for k, v in PH.items():
        text = text.replace(k, v)
    return text


def guard_tree(root, files):
    for rel, body in files.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").write(fx(body))
    return root


def run_guard(name, root, expect_rc, must=(), mustnot=()):
    p = subprocess.run([sys.executable, "-B", GUARD, "--root", root], capture_output=True, text=True)
    out = p.stdout + p.stderr
    ok = p.returncode == expect_rc and all(re.search(fx(m), out) for m in must) and not any(
        re.search(fx(m), out) for m in mustnot)
    results.append((name, ok, p.returncode, expect_rc))
    print("%s %-62s rc=%d (want %d)" % ("PASS" if ok else "FAIL", name, p.returncode, expect_rc))
    if VERBOSE or not ok:
        print("    " + out.strip().replace("\n", "\n    "))


def legacy_guard_cases(tmp):
    # L0 (round 4c L1): the tree passes with no hits, and the waiver mechanism is gone entirely.
    run_guard("L0 guard PASSES on this tree, 0 hits, no waivers", TREE, 0,
              [r"legacy-signing check: PASS \(0 hits, \d+ files\)"], [r"WAIVED", r"nolegacy", r"waived"])
    bad = [
        ("L1 sh line continuation", "greatdane/tools/a.sh", "codesign --force --sign - \\\n    @D@ a.app\n", r"a\.sh:1: codesign"),
        ("L2 sh wrapper variable $CS @D@", "greatdane/tools/a.sh", 'CS="codesign --force --sign -"\n$CS @D@ a.app\n', r"a\.sh:2: codesign"),
        ("L3 sh flag variable DEEP=@D@ / $DEEP", "greatdane/tools/a.sh", "DEEP=@D@\ncodesign --force $DEEP --sign - a\n", r"(?s)a\.sh:1:.*a\.sh:2:"),
        ("L4 sh verify and sign on one line", "greatdane/tools/a.sh", "codesign @V@ @D@ a; codesign --force @D@ --sign - a\n", r"a\.sh:1: codesign .*--sign"),
        ("L5 py '+' concatenation", "greatdane/tools/a.py", 'import subprocess\nsubprocess.run(["codesign", "--force", "--de" + "ep", "-s", "-", "a"])\n', r"a\.py:2: @D@ in a Python string"),
        ("L6 py implicit concatenation", "greatdane/tools/a.py", 'cmd = ["codesign", "--de" "ep", "-s", "-", "a"]\n', r"a\.py:1: @D@"),
        ("L7 py command string", "greatdane/tools/a.py", 'import os\nos.system("codesign --force @D@ --sign - a.app")\n', r"a\.py:2: @D@"),
        ("L8 $G/@SO@", "greatdane/tools/a.sh", "$G/@SO@ arm64\n", r"legacy sign.only\.sh outside greatdane/tools/: \$G/"),
        ("L9 absolute legacy path", "greatdane/tools/a.sh", "/Volumes/Storage/build/greatdane/@SO@\n", r"outside greatdane/tools/: /Volumes"),
        ("L10 relative legacy path", "greatdane/tools/a.sh", "./@SO@\n", r"outside greatdane/tools/: \./"),
        ("L11 @BU@", "greatdane/tools/a.sh", "bash ../@BU@\n", r"legacy build.universal\.sh"),
        ("L12 @NO@ legacy mode", "greatdane/tools/a.sh", "./@NO@ --dry-run\n", r"legacy notar.ze\.sh mode"),
        ("L13 YAML deep: true", "greatdane/ci/a.yml", "mac-signing:\n  - deep: true\n", r"a\.yml:2: YAML deep: true"),
        ("L14 YAML flow style, quoted key, yes", "taskcluster/config.yml", 'x: {"deep": yes}\n', r"config\.yml:1: YAML deep"),
        ("L15 non-.sh/.py file", "greatdane/macos/notes.conf", "codesign --force @D@ --sign - a\n", r"notes\.conf:1: codesign"),
        ("L16 Markdown fenced block", "greatdane/DOC.md", "Prose.\n```\ncodesign --force @D@ --sign - a\n```\n", r"DOC\.md:3: codesign"),
        ("L17 greatdane/tests is scanned", "greatdane/tests/x.sh", "codesign --force @D@ --sign - a\n", r"tests/x\.sh:1"),
        ("L18 py legacy path in a call", "greatdane/tools/a.py", 'import subprocess\nsubprocess.run(["bash", "/x/greatdane/@SO@"])\n', r"a\.py:2: legacy sign.only"),
        ("L19 blanket entitlements", "greatdane/tools/a.sh", "codesign --force --entitlements @BEP@ --sign - a\n", r"blanket browser"),
        # --- round 4c L2: guard gaps (one case each) ---
        ("L22 eval string", "greatdane/tools/a.sh", 'eval "codesign --force @D@ --sign - a"\n', r"a\.sh:1: codesign"),
        ("L23 bash -c string", "greatdane/tools/a.sh", "bash -c 'codesign --force @D@ -s - a'\n", r"a\.sh:1: codesign"),
        ("L24 sh -c string with its own flag variable", "greatdane/tools/a.sh", "sh -c 'X=--de; codesign -f ${X}ep -s - a'\n",
         r"a\.sh:1: codesign"),
        ("L25 ${F}ep with F assigned in the file", "greatdane/tools/a.sh", "F=--de\ncodesign --force ${F}ep --sign - a\n",
         r"a\.sh:2: codesign"),
        ("L26 ${F}ep with F unknown (env)", "greatdane/tools/a.sh", "codesign --force ${F}ep --sign - a\n", r"a\.sh:1: codesign"),
        ("L27 any deep token in a codesign command", "greatdane/tools/a.sh", "codesign --force -s - a --Deep\n",
         r"a\.sh:1: codesign"),
        ("L28 @V@ anywhere in a signing command", "greatdane/tools/a.sh", "codesign --force --sign - @D@ a.app @V@\n",
         r"a\.sh:1: codesign"),
        ("L29 py D = '@D@'", "greatdane/tools/a.py", 'import subprocess\nD = "@D@"\nsubprocess.run(["codesign", D, "-s", "-", "a"])\n',
         r"a\.py:2: @D@ in a Python string"),
        ("L30 py '-' * 2 + 'deep'", "greatdane/tools/a.py", 'cmd = ["codesign", "-" * 2 + "deep", "-s", "-", "a"]\n',
         r"a\.py:1: @D@ in a Python string"),
        ("L31 py f-string from a known prefix", "greatdane/tools/a.py", 'import os\nP = "--"\nos.system(f"codesign {P}deep -s - a")\n',
         r"a\.py:3: @D@ in a Python string"),
        ("L32 py f-string with an unknown part", "greatdane/tools/a.py", 'import os, sys\nos.system(f"codesign -f --de{sys.argv[1]} -s - a")\n',
         r"a\.py:2: @D@ in a Python string"),
        ("L33 py CS + ' @D@'", "greatdane/tools/a.py", 'import os\nCS = os.environ["CS"]\nos.system(CS + " @D@ -s - a")\n',
         r"a\.py:3: @D@ in a Python string"),
        ("L34 YAML alias to an anchored true", "greatdane/ci/a.yml", "t: &t true\nmac:\n  deep: *t\n", r"a\.yml:3: YAML deep: true"),
        ("L35 YAML anchor on the value", "greatdane/ci/a.yml", "mac:\n  deep: &x yes\n", r"a\.yml:2: YAML deep: true"),
        ("L36 YAML tag", "greatdane/ci/a.yml", "mac:\n  deep: !!bool true\n", r"a\.yml:2: YAML deep: true"),
        ("L37 YAML block-scalar run:", "greatdane/ci/a.yml", "steps:\n  - run: |\n      echo hi\n      codesign --force @D@ --sign - a\n",
         r"a\.yml:4: codesign"),
        ("L38 YAML plain run: value", "greatdane/ci/a.yml", "steps:\n  - run: codesign --force @D@ --sign - a\n", r"a\.yml:2: codesign"),
        ("L39 YAML: a comment with deep: true does not hide a real hit", "greatdane/ci/a.yml",
         "# deep: true (comment)\nv: &v true\nmac:\n  deep: *v\n", r"a\.yml:4: YAML deep: true"),
        ("L40 quoted # does not end the command", "greatdane/ci/a.yml", 'run: echo " #" && codesign --force @D@ -s - a\n',
         r"a\.yml:1: codesign"),
        ("L41 @SO@ through a variable", "greatdane/tools/a.sh", 'S=/x/greatdane/tools/@SO@\nbash "$S"\n',
         r"a\.sh:2: legacy sign.only\.sh outside greatdane/tools/: /x/greatdane/tools/"),
        ("L42 @SO@ name built from a variable", "greatdane/tools/a.sh", 'N=sign-only\n"$G/$N.sh"\n', r"a\.sh:2: legacy sign.only"),
        ("L43 @SO@ through a glob", "greatdane/tools/a.sh", "$TREE/greatdane/tools/@SOG@\n", r"a\.sh:1: legacy sign.only\.sh named through a glob"),
        ("L44 fake path ending in tools/@SO@", "greatdane/tools/a.sh", "/tmp/evil/greatdane/tools/@SO@\n",
         r"a\.sh:1: legacy sign.only\.sh outside greatdane/tools/: /tmp/evil"),
        ("L45 indented Markdown code", "greatdane/DOC.md", "Prose.\n\n    codesign --force @D@ --sign - a\n", r"DOC\.md:3: codesign"),
    ]
    for i, (name, rel, body, must) in enumerate(bad):
        root = guard_tree(os.path.join(tmp, "lg-bad%d" % i), {rel: body})
        run_guard(name + " flagged", root, 1, [must, r"legacy-signing check: FAIL"])
    good = guard_tree(os.path.join(tmp, "lg-good"), {
        "greatdane/tools/ok.sh": "codesign @V@ @D@ --strict a.app\n# codesign @D@ in a comment\necho \"no @D@ here\"\n"
                                 "$TREE/greatdane/tools/@SO@\n./@NO@ --submit-existing x.dmg abc\n",
        "greatdane/tools/ok.py": '"""Doc: never codesign @D@ to sign."""\nimport os, subprocess\nline = ""\nok = "@D@" not in line\n'
                                 'subprocess.run(["codesign", "@V@", "@D@", "a"])\n'
                                 'p = os.path.join("T", "greatdane", "tools", "@SO@")\n',
        "greatdane/README.md": "The old `$G/@SO@` used `@D@` (prose is fine).\n",
        "greatdane/ci/ok.yml": "mac:\n  - deep: false\n  - deep: !!bool false\nf: &f no\nm:\n  deep: *f\n"
                               "steps:\n  - run: |\n      codesign @V@ @D@ --strict a.app\n",
        "greatdane/tools/ok2.sh": "${TREE}/greatdane/tools/@SO@\nbash greatdane/tools/@SO@\nS=$TREE/greatdane/tools/@SO@\n\"$S\"\n"
                                  "rm -rf /volumes/*\n",
        "greatdane/DOC.md": "- item\n\n    - @SO@ deletes only its own stage dir (nested list prose)\n",
    })
    run_guard("L20 allowed forms (verify, comments, docstring, prose, $TREE tools path, YAML false) PASS", good, 0,
              [r"legacy-signing check: PASS \(0 hits"])
    waive = guard_tree(os.path.join(tmp, "lg-waive"), {
        "greatdane/tools/w.sh": "codesign --force @D@ --sign - a  # nolegacy: fixture\n",
        "greatdane/tools/w.py": 'import subprocess\nsubprocess.run(["codesign", "@D@", "-s", "-", "a"])  # nolegacy: x\n'})
    run_guard("L21 a nolegacy comment no longer waives anything", waive, 1,
              [r"w\.sh:1: codesign", r"w\.py:2: @D@", r"legacy-signing check: FAIL \(2 hits"], [r"WAIVED"])


def main():
    tmp = tempfile.mkdtemp(prefix="dane-signtest-")
    try:
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        cs = os.path.join(bindir, "codesign")
        open(cs, "w").write(MOCK)
        os.chmod(cs, 0o755)
        mock = {"PATH": bindir + os.pathsep + os.environ["PATH"], "MOCK_ENTDIR": ENTDIR, "MOCK_TEAM": TEAM}
        good = fake_app(os.path.join(tmp, "good"))

        # --- positive ---
        run("P1 plan OK (framework symlinks, symlinked Mach-O ignored)", ["plan", good], 0, [r"PLAN OK"],
            [r"XUL-link", r"PROBLEM"])
        run("P2 sign --dry-run OK", ["sign", good, "--dry-run"], 0, [r"DRY RUN: nothing signed",
            r"<identity redacted; team %s>" % TEAM], [re.escape(DEEP_FLAG)])
        run("P3 check PASS with mock codesign", ["check", good], 0, [r"CHECK PASS"], env=mock)
        jpath = os.path.join(tmp, "ent.json")
        run("P4 check --json writes report", ["check", good, "--json", jpath], 0, [r"CHECK PASS"], env=mock)
        assert os.path.isfile(jpath)
        run("P5 no-DLV main-app variant plan OK", ["plan", good], 0, [r"dane.browser.no-dlv.xml", r"PLAN OK"],
            env={"DANE_BROWSER_ENTITLEMENTS": "dane.browser.no-dlv.xml"})
        logf = os.path.join(tmp, "cs.log")
        ident = "Developer ID Application: Example Person (%s)" % TEAM
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
            env={"DANE_SIGN_ALLOW_VOLUMES": "/Volumes/Scratch:/Volumes/Other"})
        run("G14 allowlisting the owner volume is refused", ["plan", "/Volumes/Other/Dane.app", "--allow-volume",
            "/Volumes/Dane"], 2, [r"allowlist entry is itself off-limits"])
        run("G15 owner path refused even if allowlisted", ["plan", "/Volumes/Dane 1/Dane.app", "--allow-volume",
            "/Volumes/Dane 1"], 2, [r"off-limits"])
        run("G16 '/Volumes/Danes' prefix is NOT the owner volume (needs allowlist)",
            ["plan", "/Volumes/Danes/Dane.app"], 2, [r"need --allow-volume"], [r"off-limits"])

        # --- round 3: more guard rules ---
        run("G17 /Applications/Dane.app refused", ["check", "/Applications/Dane.app"], 2,
            [r"off-limits \(installed app location"], env=mock)
        run("G18 ~/Applications/Dane.app refused", ["plan", "/Users/someone/Applications/Dane.app"], 2,
            [r"off-limits \(installed app location"])
        run("G19 dangling --allow-volume outside /Volumes refused", ["plan", good, "--allow-volume",
            os.path.join(tmp, "nope")], 2, [r"allowlist entry must be a directory under /Volumes"])
        run("G20 DANE_SIGN_ALLOW_VOLUMES entry outside /Volumes refused", ["plan", good], 2,
            [r"allowlist entry must be a directory under /Volumes"], env={"DANE_SIGN_ALLOW_VOLUMES": "/tmp"})
        run("G21 bare /Volumes as allowlist refused", ["plan", good, "--allow-volume", "/Volumes"], 2,
            [r"allowlist entry must be a directory under /Volumes"])
        # owner bundle IDs outside the tree / work dirs
        for i, bid in enumerate(["surf.dogecoin.dane", "org.mozilla.surf.pepecoin.greatdane"]):
            root = os.path.join(tmp, "bid%d" % i); shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
            ipl = os.path.join(root, "Dane.app", "Contents", "Info.plist")
            d = plistlib.load(open(ipl, "rb")); d["CFBundleIdentifier"] = bid; plistlib.dump(d, open(ipl, "wb"))
            run("G%d owner bundle ID %s outside work dirs refused" % (22 + 2 * i, bid),
                ["plan", os.path.join(root, "Dane.app")], 2, [r"looks like an installed or downloaded owner copy"])
            run("G%d same app inside --work-dir passes" % (23 + 2 * i),
                ["plan", os.path.join(root, "Dane.app"), "--work-dir", root], 0, [r"PLAN OK"])
        run("G26 --work-dir that is itself off-limits refused", ["plan", good, "--work-dir", "/Applications"], 2,
            [r"work-dir entry is itself off-limits"])
        # owner dmg attached at a custom mount point (mock hdiutil)
        mnt = os.path.join(tmp, "custom-mount")
        shutil.copytree(os.path.join(tmp, "good"), mnt, symlinks=True)
        hb = os.path.join(tmp, "hbin"); os.makedirs(hb)
        info = plistlib.dumps({"images": [{"image-path": "/Users/someone/Downloads/Dane-153.7.0esr-mac-universal.dmg",
                                           "system-entities": [{"mount-point": mnt}]},
                                          {"image-path": "/tmp/other.dmg", "system-entities": [{}]}]})
        open(os.path.join(hb, "hdiutil"), "w").write("#!/bin/sh\ncat %s\n" % os.path.join(tmp, "info.plist"))
        open(os.path.join(tmp, "info.plist"), "wb").write(info)
        os.chmod(os.path.join(hb, "hdiutil"), 0o755)
        hpath = {"PATH": hb + os.pathsep + bindir + os.pathsep + os.environ["PATH"]}
        run("G27 Dane.app inside an attached Dane dmg (custom mount point) refused",
            ["check", os.path.join(mnt, "Dane.app")], 2, [r"inside attached disk image Dane-153"], env=dict(mock, **hpath))
        open(os.path.join(tmp, "info.plist"), "wb").write(plistlib.dumps(
            {"images": [{"image-path": "/x/scratch.dmg", "system-entities": [{"mount-point": mnt}]}]}))
        run("G28 same app, image without 'dane' in name but Dane.app at mount root refused",
            ["plan", os.path.join(mnt, "Dane.app")], 2, [r"inside attached disk image scratch.dmg"], env=hpath)
        run("G29 unrelated attached image does not block the work app", ["plan", good], 0, [r"PLAN OK"], env=hpath)
        run("G30 guard-path refuses owner source paths", ["guard-path", "/Volumes/Dane 2/Dane.app",
            "/Applications/Dane.app", os.path.join(tmp, "a", "DaneNotarized", "x")], 2,
            [r"Dane 2", r"/Applications/Dane.app", r"DaneNotarized"])
        run("G31 guard-path accepts a work path", ["guard-path", good, os.path.join(tmp, "out")], 0)
        # --- round 4 L-c: work dirs that are too broad ---
        for i, wd in enumerate(["/", "/Users", "/users/", os.path.expanduser("~"), "/Users/someone", "/Volumes",
                                "/System/Volumes/Data/Users"]):
            run("W%d --work-dir %s refused as too broad" % (i + 1, wd), ["plan", good, "--work-dir", wd], 2,
                [r"work-dir entry is too broad"])
        run("W8 DANE_SIGN_WORK_DIRS=/ refused as too broad", ["plan", good], 2, [r"work-dir entry is too broad"],
            env={"DANE_SIGN_WORK_DIRS": os.path.join(tmp, "ok") + ":/"})
        # --- round 4c L3: a bare volume root is too broad; a subdirectory of one is not ---
        for i, wd in enumerate(["/Volumes/Other", "/Volumes/Other/", "/volumes/storage",
                                "/System/Volumes/Data/Volumes/Other"]):
            run("W%d --work-dir %s (bare volume root) refused" % (9 + i, wd), ["plan", good, "--work-dir", wd], 2,
                [r"work-dir entry is too broad .*bare /Volumes/<name>"])
        run("W13 DANE_SIGN_WORK_DIRS=/Volumes/Other refused", ["plan", good], 2, [r"work-dir entry is too broad"],
            env={"DANE_SIGN_WORK_DIRS": "/Volumes/Other"})
        run("W14 --work-dir /Volumes/Other/build/w is narrow enough", ["plan", good, "--work-dir", "/Volumes/Other/build/w"],
            0, [r"PLAN OK"], [r"too broad"])
        # --- round 4 L-b: /System/Volumes/Data firmlink prefix stripped for every rule ---
        run("G32 /System/Volumes/Data/Applications/Dane.app refused", ["plan", "/System/Volumes/Data/Applications/Dane.app"],
            2, [r"off-limits \(installed app location"])
        run("G33 /System/Volumes/Data/Users/x/Applications/Dane.app refused",
            ["plan", "/System/Volumes/Data/Users/x/Applications/Dane.app"], 2, [r"off-limits \(installed app location"])
        run("G34 guard-path: firmlinked GreatDANE profile refused", ["guard-path",
            "/System/Volumes/Data/Users/x/Library/Application Support/GreatDANE/p"], 2, [r"GreatDANE profile"])
        run("G35 /System/Volumes/Data/Volumes/Other needs the allowlist", ["plan",
            "/System/Volumes/Data/Volumes/Other/Dane.app"], 2, [r"need --allow-volume.*: /Volumes/Other/Dane.app"])

        # --- round 3: symlink escape, framework versions ---
        root = os.path.join(tmp, "s1"); shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
        mk(os.path.join(tmp, "outside", "evil.dylib"))
        os.symlink(os.path.join(tmp, "outside", "evil.dylib"), os.path.join(root, "Dane.app", "Contents", "MacOS", "evil.dylib"))
        run("S1 file symlink resolving outside the bundle refused", ["plan", os.path.join(root, "Dane.app")], 2,
            [r"symlink escapes the bundle: Contents/MacOS/evil.dylib"])
        root = os.path.join(tmp, "s2"); shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
        os.symlink(os.path.join(tmp, "outside"), os.path.join(root, "Dane.app", "Contents", "Resources", "ext"))
        run("S2 directory symlink resolving outside the bundle refused", ["plan", os.path.join(root, "Dane.app")], 2,
            [r"symlink escapes the bundle: Contents/Resources/ext"])
        root = os.path.join(tmp, "s3"); shutil.copytree(os.path.join(tmp, "good"), root, symlinks=True)
        os.symlink("../../../../outside/evil.dylib", os.path.join(root, "Dane.app", "Contents", "Frameworks", "rel.dylib"))
        run("S3 relative ../ symlink escaping the bundle refused", ["plan", os.path.join(root, "Dane.app")], 2,
            [r"symlink escapes the bundle: Contents/Frameworks/rel.dylib"])
        fw = "Contents/Frameworks/ChannelPrefs.framework"
        a = variant("f1", fw + "/Versions/B/ChannelPrefs")
        run("F1 second real framework version (Versions/B) refused", ["plan", a], 2,
            [r"not covered by the map: .*ChannelPrefs.framework/Versions/B/ChannelPrefs"])
        a = variant("f2", fw + "/Versions/B/ChannelPrefs")
        cl = os.path.join(a, fw, "Versions", "Current"); os.remove(cl); os.symlink("B", cl)
        run("F2 Current -> B: the old Versions/A binary is refused", ["plan", a], 2,
            [r"not covered by the map: .*ChannelPrefs.framework/Versions/A/ChannelPrefs"])

        # --- round 3: ad-hoc throwaway runs ---
        logf2 = os.path.join(tmp, "cs-adhoc.log")
        run("A1 ad-hoc sign (identity '-') -> CHECK PASS (AD-HOC)", ["sign", good, "--allow-adhoc"], 0,
            [r"CHECK PASS \(AD-HOC: expected-not-Developer-ID", r"ad-hoc: expected, not Developer ID"],
            [r"CHECK FAIL"], env=dict(mock, DANE_SIGN_IDENTITY="-", MOCK_ADHOC="1", MOCK_LOG=logf2))
        sl = [l.split() for l in open(logf2).read().splitlines() if "--sign" in l]
        ok = bool(sl) and all("--timestamp" not in l and "--deep" not in l and l[l.index("--sign") + 1] == "-"
                              and "runtime" in l for l in sl) and any(
            "--entitlements" in l and l[-1].endswith("media-plugin-helper.app") for l in sl)
        results.append(("A2 ad-hoc calls: '-', runtime, entitlements kept, no --timestamp/--deep", ok, 0, 0))
        print("%s %-62s" % ("PASS" if ok else "FAIL", "A2 ad-hoc calls: '-', runtime, entitlements kept, no --timestamp/--deep"))
        run("A3 ad-hoc + check --strict FAILS (even with --allow-adhoc)", ["check", good, "--strict", "--allow-adhoc"], 1,
            [r"ad-hoc signature \(strict: Developer ID required\)", r"CHECK FAIL"], env=dict(mock, MOCK_ADHOC="1"))
        run("A4 ad-hoc + DANE_SIGN_STRICT=1 FAILS", ["check", good, "--allow-adhoc"], 1, [r"CHECK FAIL"],
            env=dict(mock, MOCK_ADHOC="1", DANE_SIGN_STRICT="1"))
        run("A5 ad-hoc still requires hardened runtime", ["check", good, "--allow-adhoc"], 1, [r"no hardened runtime", r"CHECK FAIL"],
            env=dict(mock, MOCK_ADHOC="1", MOCK_NO_RUNTIME="1"))
        run("A6 ad-hoc still requires the mapped entitlements", ["check", good, "--allow-adhoc"], 1,
            [r"FAIL Contents/MacOS/gpu-helper.app"], env=dict(mock, MOCK_ADHOC="1", MOCK_BAD_GPU="1"))
        run("A7 mixed ad-hoc / Developer ID fails", ["check", good, "--allow-adhoc"], 1, [r"mixed ad-hoc and Developer ID"],
            env=dict(mock, MOCK_ADHOC_ONLY="gpu-helper.app"))
        run("A8 Developer ID check --strict still PASSES", ["check", good, "--strict"], 0, [r"(?m)^CHECK PASS$"],
            [r"AD-HOC"], env=mock)
        # --- round 4 L-f: ad-hoc only with the explicit opt-in ---
        run("A9 check rejects ad-hoc by default (no --allow-adhoc)", ["check", good], 1,
            [r"default rejects ad-hoc", r"CHECK FAIL"], [r"CHECK PASS"], env=dict(mock, MOCK_ADHOC="1"))
        run("A10 sign with identity '-' without --allow-adhoc refused", ["sign", good], 2,
            [r"needs the explicit --allow-adhoc"], env=dict(mock, DANE_SIGN_IDENTITY="-", MOCK_ADHOC="1"))
        run("A11 sign --dry-run with '-' without --allow-adhoc refused", ["sign", good, "--dry-run"], 2,
            [r"needs the explicit --allow-adhoc"], env={"DANE_SIGN_IDENTITY": "-"})

        # --- L5: failing mocks for check ---
        run("C1 check FAIL: no hardened runtime", ["check", good], 1, [r"no hardened runtime", r"CHECK FAIL"],
            env=dict(mock, MOCK_NO_RUNTIME="1"))
        run("C2 check FAIL: wrong team", ["check", good], 1, [r"team ABCDE12345 != " + TEAM, r"CHECK FAIL"],
            env=dict(mock, MOCK_TEAM="ABCDE12345"))
        run("C3 check FAIL: no secure timestamp", ["check", good], 1, [r"no secure timestamp", r"CHECK FAIL"],
            env=dict(mock, MOCK_NO_TS="1"))
        run("C4 check FAIL: helper with browser entitlements", ["check", good], 1,
            [r"FAIL Contents/MacOS/gpu-helper.app"], env=dict(mock, MOCK_BAD_GPU="1"))

        # --- L3: team ID from one config file ---
        other = "ABCDE12345" if TEAM != "ABCDE12345" else "ZYXWV98765"
        conf = os.path.join(tmp, "signing-mismatch.conf")
        open(conf, "w").write("TEAM_ID=%s\n" % other)
        run("T1 signing.conf team mismatch fails check", ["check", good], 1,
            [r"team %s != %s" % (TEAM, other), r"CHECK FAIL"], env=dict(mock, DANE_SIGNING_CONF=conf))
        bad = os.path.join(tmp, "signing-bad.conf")
        open(bad, "w").write("TEAM_ID=nope\n")
        run("T2 malformed signing.conf refused", ["plan", good], 2, [r"TEAM_ID .* must be"],
            env={"DANE_SIGNING_CONF": bad})
        cfg = os.path.join(TREE, "build", "moz.configure", "update-programs.configure")
        team = TEAM
        if os.path.isfile(cfg):
            ous = re.findall(r'subject\.OU\]\s*=\s*\\?"([A-Z0-9]{10})', open(cfg).read())
            ok = bool(ous) and all(o == team for o in ous)
            results.append(("T3 update-programs.configure OU == signing.conf", ok, 0, 0))
            print("%s %-62s %s" % ("PASS" if ok else "FAIL", "T3 update-programs.configure OU == signing.conf", ous))
        else:
            print("SKIP T3 update-programs.configure not in this tree")
        # --- round 4 L-a: the legacy-signing guard, on this tree and on fixtures ---
        legacy_guard_cases(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in results if not r[1]]
    print("\n%d cases, %d passed, %d failed" % (len(results), len(results) - len(failed), len(failed)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
