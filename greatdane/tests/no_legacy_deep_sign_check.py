#!/usr/bin/env python3
"""Guard: no in-tree signing path may use the retired legacy mode (codesign --deep to SIGN, or the blanket
browser.entitlements.plist), or call the out-of-tree $G/sign-only.sh / build-universal.sh / notarize.sh.

Scans greatdane/**/*.sh and *.py (except greatdane/tests) plus taskcluster/config.yml (no `deep: true`).
`codesign --verify --deep` is allowed (verifying is fine). Run from the tree root; exit 1 on any hit.
"""
import os, re, sys

hits = []
for dp, dns, fns in os.walk("greatdane"):
    if os.path.normpath(dp).startswith(os.path.join("greatdane", "tests")):
        continue
    for fn in fns:
        if not fn.endswith((".sh", ".py")):
            continue
        p = os.path.join(dp, fn)
        for n, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            code = line.split("#", 1)[0] if fn.endswith(".sh") else line
            if fn.endswith(".py") and code.lstrip().startswith("#"):
                continue
            if fn.endswith(".sh"):
                deep = "codesign" in code and "--deep" in code
            else:  # Python: only an actual "--deep" argument literal, not prose in docstrings
                deep = bool(re.search(r"""["']--deep["']""", code))
            if deep and "--verify" not in code:
                hits.append("%s:%d: codesign --deep used to sign" % (p, n))
            if "browser.entitlements.plist" in code:
                hits.append("%s:%d: blanket browser.entitlements.plist" % (p, n))
            if re.search(r"\$\{?G\}?/(sign-only|build-universal|notarize)\.sh", code):
                hits.append("%s:%d: calls a legacy out-of-tree script" % (p, n))
cfg = os.path.join("taskcluster", "config.yml")
if os.path.isfile(cfg):
    for n, line in enumerate(open(cfg, encoding="utf-8"), 1):
        if re.match(r"\s*-?\s*deep:\s*true\b", line):
            hits.append("%s:%d: mac-signing group with deep: true" % (cfg, n))
for h in hits:
    print("FAIL " + h)
print("legacy-signing check: %s (%d hit%s)" % ("FAIL" if hits else "PASS", len(hits), "" if len(hits) == 1 else "s"))
sys.exit(1 if hits else 0)
