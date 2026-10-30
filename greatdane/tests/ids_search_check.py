# IDs + search: app name/vendor/basename/remoting name/ID, bundle ID, update channel, stock search engines and
# suggestions on, .pepe/.doge urlbar name provider registered and enabled.
# BuildID: the EXPECTED value comes from the caller (never from the app under test):
#   ids_search_check.py <greatdane> <arm64|x86_64> --expected 20261030090840
#   ids_search_check.py <greatdane> <arm64|x86_64> --buildinfo .../BUILDINFO-<id>.txt
# Asserts application.ini == platform.ini == appinfo.appBuildID == expected, and that every child
# process launched during the run carries -parentBuildID == expected (ps polled every 0.1s, keyed
# by pid, cross-checked against ChromeUtils.requestProcInfo so no live child is missed).
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import os, sys, subprocess, plistlib, json, re, threading, time
from marionette_driver.marionette import Marionette
APP, ARCH = sys.argv[1], sys.argv[2]
_a = sys.argv[3:]
if len(_a) == 2 and _a[0] == "--expected": EXPECTED = _a[1]
elif len(_a) == 2 and _a[0] == "--buildinfo":
    EXPECTED = [l.split(":", 1)[1].strip() for l in open(_a[1]) if l.startswith("build_id:")][0]
else: sys.exit("usage: ids_search_check.py <greatdane> <arm64|x86_64> (--expected BUILDID | --buildinfo BUILDINFO.txt)")
if not re.fullmatch(r"\d{14}", EXPECTED): sys.exit("bad expected BuildID %r" % EXPECTED)
print(ARCH, "expected BuildID", EXPECTED, "from", _a[0])
BUNDLE = os.path.realpath(os.path.join(os.path.dirname(APP), "..", ".."))
CHILD = {}  # pid -> (parentBuildID, args)
_stop = threading.Event()
def _poll():
    while not _stop.is_set():
        try: out = subprocess.run(["ps", "-axww", "-o", "pid=,args="], capture_output=True, text=True, timeout=10).stdout
        except Exception: out = ""
        for line in out.splitlines():
            pid, _, args = line.strip().partition(" ")
            if BUNDLE in args and "-parentBuildID" in args and pid not in CHILD:
                mm = re.search(r"-parentBuildID (\S+)", args)
                CHILD[pid] = (mm.group(1) if mm else "?", args)
        _stop.wait(0.1)
_pt = threading.Thread(target=_poll, daemon=True); _pt.start()
prof = gd_guard.profile("gd-ids-")
open(prof + "/user.js", "w").write('user_pref("marionette.port", 2840);\nuser_pref("greatdane.node.dataDir", "' + gd_guard.safe(gd_guard.ND) + '");\nuser_pref("greatdane.pep.listen_port", 34876);\nuser_pref("greatdane.doge.listen_port", 23558);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("browser.aboutwelcome.enabled", false);\n')
fails = 0
def check(name, ok, info=""):
    global fails; fails += 0 if ok else 1
    print(ARCH, "PASS" if ok else "FAIL", name, info)
plist = plistlib.load(open(os.path.join(os.path.dirname(APP), "..", "Info.plist"), "rb"))
check("bundle ID surf.dogecoin.dane", plist.get("CFBundleIdentifier") == "surf.dogecoin.dane", plist.get("CFBundleIdentifier"))
check("bundle name Dane", plist.get("CFBundleName") == "Dane", plist.get("CFBundleName"))
p = subprocess.Popen(["arch", "-" + ARCH, APP, "-marionette", "-remote-allow-system-access", "-no-remote", "-profile", prof], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
m = Marionette(host="127.0.0.1", port=2840); m.start_session()

# ABI gate: the running app must be the requested arch (arch -x86_64 => x86_64-gcc3, arm64 => aarch64-gcc3).
_WANT_ABI = {"arm64": "aarch64-gcc3", "x86_64": "x86_64-gcc3"}[ARCH]
with m.using_context("chrome"): _ABI = m.execute_script("return Services.appinfo.XPCOMABI")
print("ABI-MARKER requested=%s XPCOMABI=%s %s" % (ARCH, _ABI, "OK" if _ABI == _WANT_ABI else "MISMATCH"), flush=True)
if _ABI != _WANT_ABI:
    try:
        with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
    except Exception: pass
    p.wait(30); sys.exit("FAIL: requested %s but app runs %s" % (ARCH, _ABI))
try:
    with m.using_context("chrome"):
        r = m.execute_async_script("""const [resolve]=arguments;(async()=>{
          const {AppConstants}=ChromeUtils.importESModule('resource://gre/modules/AppConstants.sys.mjs');
          const SS=ChromeUtils.importESModule('moz-src:///toolkit/components/search/SearchService.sys.mjs').SearchService;
          const T=(pr,ms,tag)=>Promise.race([pr,new Promise((_,j)=>setTimeout(()=>j(new Error(tag+' timeout')),ms))]);
          const {setTimeout}=ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
          await T(SS.init(),40000,'search.init');
          const engines=(await T(SS.getEngines(),10000,'getEngines')).map(e=>e.name);
          const def=(await T(SS.getDefault(),10000,'getDefault')).name;
          let prov=null; try{const mod=ChromeUtils.importESModule('moz-src:///browser/components/urlbar/UrlbarProviderGreatDANENames.sys.mjs');
            const src=await (await fetch('moz-src:///browser/components/urlbar/UrlbarProvidersManager.sys.mjs')).text();
            prov=Object.keys(mod).concat(src.includes('UrlbarProviderGreatDANENames.sys.mjs')?['registered-in-ProvidersManager']:[]);}catch(e){prov=String(e);}
          const pi=await ChromeUtils.requestProcInfo();
          const kids=pi.children.map(c=>String(c.pid));
          const P=Services.prefs;
          resolve({name:Services.appinfo.name,vendor:Services.appinfo.vendor,id:Services.appinfo.ID,abi:Services.appinfo.XPCOMABI,
            basename:AppConstants.MOZ_APP_BASENAME,remoting:AppConstants.MOZ_APP_REMOTINGNAME||Services.appinfo.remotingName,
            channel:AppConstants.MOZ_UPDATE_CHANNEL,build:Services.appinfo.appBuildID,
            engines,def,suggest:P.getBoolPref('browser.search.suggest.enabled'),
            urlbarSuggest:P.getBoolPref('browser.urlbar.suggest.searches'),urlbarSuggestDefault:P.getDefaultBranch('').getBoolPref('browser.urlbar.suggest.searches'),urlbarSuggestUser:P.prefHasUserValue('browser.urlbar.suggest.searches'),
            names:P.getBoolPref('greatdane.urlbar.names',false),prov,
            kids,profDir:Services.dirsvc.get('ProfD',Ci.nsIFile).path});})().catch(e=>resolve({err:String(e)}))""", script_timeout=60000)
    print(ARCH, json.dumps(r))
    if "err" in r: check("chrome script ran", False, r["err"]); raise SystemExit(1)
    check("appinfo name GreatDANE", r["name"] == "GreatDANE", r["name"])
    check("app basename GreatDANE", r["basename"] == "GreatDANE", r["basename"])
    check("app ID stock Firefox ID", r["id"] == "{ec8030f7-c20a-464f-9b0e-13a3a9e97384}", r["id"])
    check("update channel esr", r["channel"] == "esr", r["channel"])
    _res = os.path.join(BUNDLE, "Contents", "Resources")
    def _ini(n): return [l.split("=", 1)[1].strip() for l in open(os.path.join(_res, n)) if l.startswith("BuildID=")][0]
    ai, pl = _ini("application.ini"), _ini("platform.ini")
    check("application.ini BuildID == expected", ai == EXPECTED, ai)
    check("platform.ini BuildID == expected", pl == EXPECTED, pl)
    check("appinfo.appBuildID == expected", r["build"] == EXPECTED, r["build"])
    time.sleep(0.5)
    missed = [k for k in r["kids"] if k not in CHILD]
    check("every live child (requestProcInfo) was captured", not missed, missed)
    check("XPCOMABI == " + _WANT_ABI, r["abi"] == _WANT_ABI, r["abi"])
    check("stock engines present (>=4, incl. Google)", len(r["engines"]) >= 4 and any(e.startswith("Google") for e in r["engines"]), r["engines"])
    check("search suggestions on (shipped default; marionette forces urlbar.suggest.searches=false as a user value)", r["suggest"] and r["urlbarSuggestDefault"], r)
    check(".pepe/.doge name suggestions on", r["names"] and isinstance(r["prov"], list) and "registered-in-ProvidersManager" in r["prov"], r["prov"])
    check("profile is throwaway", gd_guard.safe(r["profDir"]) is not None, r["profDir"])
finally:
    try:
        with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
    except Exception: pass
    p.wait(30)
    _stop.set(); _pt.join(5)
cnt = {}
for pid, (b, a) in sorted(CHILD.items()):
    t = re.search(r"-(?:contentproc|childID).*?\s(tab|gpu|rdd|socket|utility|gmplugin|web|file|extension|privilegedabout|forkserver|\S+)$", a)
    print(ARCH, "child", pid, "parentBuildID", b, (t.group(1) if t else ""))
    cnt[b] = cnt.get(b, 0) + 1
print(ARCH, "parentBuildID counts", json.dumps(cnt), "children", len(CHILD))
check("child launches captured (>0)", len(CHILD) > 0, len(CHILD))
check("every child parentBuildID == expected", set(cnt) == {EXPECTED}, cnt)
print(ARCH, "RESULT", "PASS" if fails == 0 else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
