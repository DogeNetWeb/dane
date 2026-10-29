# Dane settings tests in the built Dane (chrome context via Marionette):
# the Dane pane loads, its toggles write prefs, Mozilla promo/data-collection
# sections are hidden, Sync is visible by default and hidden by
# greatdane.prefs.hideSync, and the first-run update window logic.
#   python3 run_gd_prefs.py [path/to/greatdane] [screens_dir]
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import os, shutil, subprocess, sys, tempfile, time
from marionette_driver.marionette import Marionette
HERE = os.path.dirname(os.path.abspath(__file__))
TREE = os.path.abspath(os.path.join(HERE, "../.."))
APP = sys.argv[1] if len(sys.argv) > 1 else TREE + "/obj-gd/dist/Dane.app/Contents/MacOS/greatdane"
SHOTS = sys.argv[2] if len(sys.argv) > 2 else None
prof = gd_guard.profile("gd-prefs-")
open(prof + "/user.js", "w").write('user_pref("marionette.port", 2833);\nuser_pref("greatdane.node.dataDir", "' + gd_guard.ND + '");\nuser_pref("greatdane.pep.listen_port", 34874);\nuser_pref("greatdane.doge.listen_port", 23556);\nuser_pref("browser.aboutwelcome.enabled", false);\n')
p = subprocess.Popen([APP, "--headless", "--marionette", "-remote-allow-system-access", "--no-remote", "--profile", prof,
                      "--width", "1280", "--height", "900"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
fails = 0
def check(name, ok, info=""):
    global fails
    print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info and not ok else ""))
    fails += 0 if ok else 1

OPEN = '''let [pane, done] = arguments;
let w = Services.wm.getMostRecentWindow("navigator:browser");
w.openPreferences(pane);
let t0 = Date.now();
(function poll() {
  let d = w.gBrowser.selectedBrowser.contentDocument;
  let ok = d && d.readyState == "complete" && d.documentElement.getAttribute("data-gd-ready") != null;
  if (d && d.readyState == "complete" && d.getElementById("gd-hide-style") && (Date.now() - t0) > 1500) return done(true);
  if (Date.now() - t0 > 30000) return done(false);
  w.setTimeout(poll, 200);
})();'''
JS = '''let d = Services.wm.getMostRecentWindow("navigator:browser").gBrowser.selectedBrowser.contentDocument;
let vis = el => !!el && d.defaultView.getComputedStyle(el).display != "none" && el.getClientRects().length > 0;
let shown = sel => [...d.querySelectorAll(sel)].some(e => d.defaultView.getComputedStyle(e).display != "none");
'''
def js(m, body, args=None): return m.execute_script(JS + body, script_args=args or [], sandbox=None)
def shot(m, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        open(os.path.join(SHOTS, name), "wb").write(m.screenshot(format="binary"))
rc = 1
try:
    for _ in range(60):
        try:
            m = Marionette(host="127.0.0.1", port=2833); m.start_session(); break
        except Exception: time.sleep(1)
    m.set_context("chrome"); m.timeout.script = 60
    # Pane loads
    check("dane pane loads", m.execute_async_script(OPEN, script_args=["greatdane"], sandbox=None))
    time.sleep(2)
    r = js(m, '''return { nav: vis(d.getElementById("category-greatdane")),
      pep: vis(d.getElementById("gd-pep-enabled")), doge: vis(d.getElementById("gd-doge-enabled")),
      st: d.getElementById("gd-pep-status")?.getAttribute("label") || "",
      dir: d.getElementById("gd-data-dir")?.getAttribute("description") || "",
      pat: !!d.getElementById("gd-chain-host-pattern"), chan: d.getElementById("gd-update-channel")?.getAttribute("description") || "",
      icon: d.getElementById("category-greatdane")?.getAttribute("iconsrc") };''')
    check("dane nav button visible", r["nav"], r)
    check("per-chain toggles shown", r["pep"] and r["doge"], r)
    check("status row localized", r["st"].startswith("Status:"), r)
    check("data dir shown read-only", bool(r["dir"]) and r["dir"] != "-", r)
    check("chain host pattern field", r["pat"], r)
    check("update channel shown", bool(r["chan"]), r)
    check("dane icon", r["icon"] == "chrome://branding/content/about-logo.svg", r)
    shot(m, "dane.png")
    # Toggles write prefs
    r = m.execute_async_script(JS + '''let done = arguments[arguments.length - 1];
      let tick = () => new Promise(r => d.defaultView.setTimeout(r, 400));
      let press = id => { let t = d.getElementById(id); (t.buttonEl || t.shadowRoot.querySelector("button")).click(); };
      (async () => { let out = {};
        for (let [id, pref] of [["gd-pep-enabled", "greatdane.pep.enabled"], ["gd-doge-enabled", "greatdane.doge.enabled"]]) {
          out[id] = [Services.prefs.getBoolPref(pref)]; press(id); await tick();
          out[id].push(Services.prefs.getBoolPref(pref)); press(id); await tick(); out[id].push(Services.prefs.getBoolPref(pref));
        }
        let W = "greatdane.update.skipFirstRunWindowSec";
        out.upd = [Services.prefs.getIntPref(W)]; press("gd-update-firstrun-skip"); await tick();
        out.upd.push(Services.prefs.getIntPref(W)); press("gd-update-firstrun-skip"); await tick(); out.upd.push(Services.prefs.getIntPref(W));
        done(out); })();''', sandbox=None)
    check("pep toggle writes pref", r["gd-pep-enabled"] == [True, False, True], r)
    check("doge toggle writes pref", r["gd-doge-enabled"] == [True, False, True], r)
    check("first-run toggle writes window pref", r["upd"] == [3600, 0, 3600], r)
    # Default top-site tiles (region-independent; sponsored off)
    r = m.execute_script("""return {
      sites: Services.prefs.getStringPref("browser.newtabpage.activity-stream.default.sites", ""),
      remote: Services.prefs.getBoolPref("browser.topsites.useRemoteSetting", true),
      sponsored: Services.prefs.getBoolPref("browser.newtabpage.activity-stream.showSponsoredTopSites", true),
      contile: Services.prefs.getBoolPref("browser.topsites.contile.enabled", true),
    };""", sandbox=None)
    expect = "https://www.youtube.com/,https://pepecoin.surf/,https://www.amazon.com/,https://dogecoin.surf/,https://grokipedia.com/,https://x.com/,https://greatdane.doge/"
    check("default top-site tiles", r["sites"] == expect, r)
    check("remote/region default sites off", r["remote"] is False, r)
    check("sponsored top sites off", r["sponsored"] is False and r["contile"] is False, r)
    # Startup + Home open the new-tab page with the tiles (no forced site homepage)
    r = m.execute_script("""return {
      home: Services.prefs.getStringPref("browser.startup.homepage", ""),
      homeDefault: Services.prefs.getDefaultBranch("").getStringPref("browser.startup.homepage", ""),
      page: Services.prefs.getIntPref("browser.startup.page", -1),
      newtab: Services.prefs.getBoolPref("browser.newtabpage.enabled", false),
      welcome: Services.prefs.getStringPref("startup.homepage_welcome_url", "x"),
      override: Services.prefs.getStringPref("startup.homepage_override_url", "x"),
    };""", sandbox=None)
    check("startup/home = about:home tiles", r["home"] == "about:home" and r["homeDefault"] == "about:home" and r["page"] == 1 and r["newtab"] is True, r)
    check("no forced welcome/override homepage", r["welcome"] == "" and r["override"] == "", r)
    # Hidden sections (Privacy)
    m.execute_async_script(OPEN, script_args=["privacy"], sandbox=None); time.sleep(2)
    # Settings redesign: data collection lives in the "Permissions and data" pane.
    m.execute_async_script(OPEN, script_args=["permissionsData"], sandbox=None); time.sleep(2)
    dc = js(m, '''let g = d.querySelector('setting-group[groupid="dataCollection"]');
      return !!g && g.checkVisibility() && g.getBoundingClientRect().height > 0;''')
    m.execute_async_script(OPEN, script_args=["privacy"], sandbox=None); time.sleep(2)
    r = js(m, '''return { dc: arguments[0],
      vpn: shown('[groupid="ipprotection"]'), relay: [...d.querySelectorAll("#relayIntegrationBox, #setting-control-relayIntegration, #relayIntegration")].some(vis),
      relayPresent: d.querySelectorAll("#setting-control-relayIntegration, #relayIntegration").length > 0,
      mfm: vis(d.getElementById("category-more-from-mozilla")),
      sync: vis(d.getElementById("category-sync")) };''', [dc])
    check("data collection opt-outs visible", r["dc"], r)
    check("VPN hidden", not r["vpn"], r)
    check("Relay hidden (incl. 'Suggest Firefox Relay email masks')", r["relayPresent"] and not r["relay"], r)
    check("More from Mozilla hidden", not r["mfm"], r)
    check("Sync visible by default", r["sync"], r)
    shot(m, "privacy-security.png")
    m.execute_async_script(OPEN, script_args=["general"], sandbox=None); time.sleep(2); shot(m, "general.png")
    m.execute_async_script(OPEN, script_args=["sync"], sandbox=None); time.sleep(2); shot(m, "sync.png")
    r = js(m, '''Services.prefs.setBoolPref("greatdane.prefs.hideSync", true);
      let a = vis(d.getElementById("category-sync"));
      Services.prefs.setBoolPref("greatdane.prefs.hideSync", false);
      return [a, vis(d.getElementById("category-sync"))];''')
    check("Sync hidden when hideSync=true, back when false", r == [False, True], r)
    # First-run update window (fail open)
    r = js(m, '''let us = Cc["@mozilla.org/updates/update-service;1"].getService().wrappedJSObject;
      let P = "greatdane.update.firstRunTime", W = "greatdane.update.skipFirstRunWindowSec", now = Math.floor(Date.now()/1000);
      let o = {};
      Services.prefs.clearUserPref(P); o.first = us._greatdaneSkipFirstSession(); o.recorded = Services.prefs.prefHasUserValue(P);
      Services.prefs.setStringPref(P, String(now - 10)); o.inside = us._greatdaneSkipFirstSession();
      Services.prefs.setStringPref(P, String(now - 4000)); o.after = us._greatdaneSkipFirstSession();
      Services.prefs.setStringPref(P, "garbage"); o.garbage = us._greatdaneSkipFirstSession();
      Services.prefs.setStringPref(P, String(now - 10)); Services.prefs.setIntPref(W, 0); o.off = us._greatdaneSkipFirstSession();
      Services.prefs.clearUserPref(W); Services.prefs.clearUserPref(P);
      Services.prefs.setIntPref(P, 5); o.wrongType = us._greatdaneSkipFirstSession(); Services.prefs.clearUserPref(P);
      return o;''')
    check("update window: first check records time and skips", r["first"] and r["recorded"], r)
    check("update window: inside window skips", r["inside"], r)
    check("update window: after window checks", not r["after"], r)
    check("update window: garbage fails open", not r["garbage"], r)
    check("update window: 0 disables", not r["off"], r)
    check("update window: wrong pref type fails open", not r["wrongType"], r)
    m.delete_session(); rc = 0 if fails == 0 else 1
finally:
    p.terminate(); p.wait(20); shutil.rmtree(prof, ignore_errors=True)
print(f"failed={fails}")
sys.exit(rc)
