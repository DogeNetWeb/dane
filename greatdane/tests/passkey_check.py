# Passkey readiness check (PASSKEYS-PLAN.md section 5), read-only on the app bundle.
# Usage: passkey_check.py <Dane.app> <arm64|x86_64> [--static-only]
# Static (no launch): if Contents/embedded.provisionprofile is ABSENT, no Mach-O in the bundle may carry
#   com.apple.developer.web-browser.public-key-credential or com.apple.application-identifier (expected today).
#   If PRESENT: the main app must carry both (application-identifier == MNL79V994R.surf.dogecoin.dane),
#   the profile must grant the same, and no nested code (node, helpers, updater, dylibs) may carry the passkey key.
# Runtime (throwaway profile under gd_guard, ABI gate): pref security.webauthn.enable_macos_passkeys is true
#   and PublicKeyCredential / navigator.credentials exist. Never touches signing inputs or Apple accounts.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import os, sys, subprocess, plistlib
PK = "com.apple.developer.web-browser.public-key-credential"
AI = "com.apple.application-identifier"
WANT_AI = "MNL79V994R.surf.dogecoin.dane"
APP, ARCH = os.path.realpath(sys.argv[1]), sys.argv[2]
STATIC_ONLY = "--static-only" in sys.argv
fails = []

def ents(path):
    r = subprocess.run(["codesign", "-d", "--entitlements", "-", "--xml", path], capture_output=True)
    if r.returncode != 0 or not r.stdout.strip(): return {}
    try: return plistlib.loads(r.stdout)
    except Exception: return {}

def macho(path):
    r = subprocess.run(["file", "-b", path], capture_output=True, text=True)
    return "Mach-O" in r.stdout

code = []
for root, dirs, files in os.walk(APP):
    for f in files:
        p = os.path.join(root, f)
        if not os.path.islink(p) and os.access(p, os.X_OK) and macho(p): code.append(p)
main = os.path.join(APP, "Contents/MacOS/greatdane")
prof = os.path.join(APP, "Contents/embedded.provisionprofile")
has_prof = os.path.exists(prof)
print("app:", APP); print("mach-o files:", len(code)); print("embedded.provisionprofile:", "present" if has_prof else "absent")
for p in code:
    e = ents(p); rel = os.path.relpath(p, APP); is_main = (p == main)
    hit = [k for k in (PK, AI) if k in e]
    if not has_prof:
        if hit: fails.append("%s carries %s without an embedded profile" % (rel, hit))
    elif is_main:
        if e.get(PK) is not True: fails.append("main app lacks %s" % PK)
        if e.get(AI) != WANT_AI: fails.append("main app %s=%r, want %s" % (AI, e.get(AI), WANT_AI))
    elif PK in e:
        fails.append("nested %s carries %s" % (rel, PK))
    if is_main: print("main entitlements:", sorted(e.keys()))
if has_prof:
    r = subprocess.run(["security", "cms", "-D", "-i", prof], capture_output=True)
    try:
        pe = plistlib.loads(r.stdout).get("Entitlements", {})
        if pe.get(AI) != WANT_AI: fails.append("profile %s=%r" % (AI, pe.get(AI)))
        if pe.get(PK) is not True: fails.append("profile does not grant %s" % PK)
    except Exception as ex: fails.append("profile unreadable: %s" % ex)
print("STATIC", "OK" if not fails else "FAIL", fails, flush=True)

if not STATIC_ONLY:
    from marionette_driver.marionette import Marionette
    pd = gd_guard.profile("gd-test-")
    open(pd + "/user.js", "w").write('user_pref("marionette.port", 2839);\nuser_pref("greatdane.node.dataDir", "' + gd_guard.safe(gd_guard.ND) + '");\nuser_pref("greatdane.pep.listen_port", 34875);\nuser_pref("greatdane.doge.listen_port", 23557);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\n')
    p = subprocess.Popen(["arch", "-" + ARCH, main, "-marionette", "-remote-allow-system-access", "-no-remote", "-profile", pd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    m = Marionette(host="127.0.0.1", port=2839); m.start_session()
    want_abi = {"arm64": "aarch64-gcc3", "x86_64": "x86_64-gcc3"}[ARCH]
    with m.using_context("chrome"):
        abi = m.execute_script("return Services.appinfo.XPCOMABI")
        pref = m.execute_script("return Services.prefs.getBoolPref('security.webauthn.enable_macos_passkeys', false)")
    print("ABI-MARKER requested=%s XPCOMABI=%s %s" % (ARCH, abi, "OK" if abi == want_abi else "MISMATCH"), flush=True)
    if abi != want_abi: fails.append("ABI mismatch")
    m.navigate("https://example.com/")
    api = m.execute_script("return [typeof PublicKeyCredential, typeof navigator.credentials, isSecureContext]")
    print("runtime: enable_macos_passkeys=%s api=%s" % (pref, api))
    if pref is not True: fails.append("pref security.webauthn.enable_macos_passkeys is not true")
    if api[0] != "function" or api[1] != "object": fails.append("WebAuthn API missing: %s" % api)
    try:
        with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
    except Exception: pass
    p.wait(30); print(ARCH, "exit", p.returncode)
print("RESULT", "PASS" if not fails else "FAIL", fails)
sys.exit(1 if fails else 0)
