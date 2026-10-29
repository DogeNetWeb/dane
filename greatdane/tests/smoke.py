# Smoke: launch Dane (given arch), load about:dane, check #discover link, read node status, time clean quit.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import os, sys, subprocess, tempfile, time, base64
from marionette_driver.marionette import Marionette
APP, ARCH = sys.argv[1], sys.argv[2]
SHOT = sys.argv[3] if len(sys.argv) > 3 else None
prof = gd_guard.profile("gd-test-")
open(prof + "/user.js", "w").write('user_pref("marionette.port", 2838);\nuser_pref("greatdane.node.dataDir", "' + gd_guard.ND + '");\nuser_pref("greatdane.pep.listen_port", 34874);\nuser_pref("greatdane.doge.listen_port", 23556);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\n')
cmd = ["arch", "-" + ARCH, APP, "-marionette", "-remote-allow-system-access", "-no-remote", "-profile", prof]
p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
m = Marionette(host="127.0.0.1", port=2838); m.start_session()
with m.using_context("chrome"):
    real = m.execute_script("return Services.appinfo.XPCOMABI + ' ' + Services.appinfo.name + ' ' + Services.appinfo.version + ' ' + Services.appinfo.appBuildID")
print(ARCH, "appinfo:", real)
m.navigate("about:dane")
t = m.execute_script("return [document.title, !!document.getElementById('discover'), document.body.innerText.slice(0,200)]")
print(ARCH, "about:dane title=%r discover_link=%s" % (t[0], t[1]))
st = None
for i in range(60):
    with m.using_context("chrome"):
        st = m.execute_script("""const {GreatDANE}=ChromeUtils.importESModule('resource:///modules/GreatDANE.sys.mjs');
          return [...GreatDANE._chains.values()].map(c=>({coin:c.coin,state:c.state,s:c.status&&{state:c.status.state,listen:c.status.listen,port:c.status.listen_port,pin:c.status.peers_in,pout:c.status.peers_out,sync:c.status.sync_pct,dir:c.status.data_dir}}))""")
    if all(c["s"] and (c["s"]["pout"] or 0) > 0 for c in st): break
    time.sleep(2)
print(ARCH, "nodes:", st)
if SHOT:
    m.navigate("about:preferences#greatdane"); time.sleep(4)
    open(SHOT, "wb").write(base64.b64decode(m.screenshot(full=True)))
    print("shot", SHOT)
t0 = time.time()
try:
    with m.using_context("chrome"):
        m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
except Exception as e: pass
p.wait(30); print(ARCH, "exit rc=%s in %.1fs" % (p.returncode, time.time() - t0))
nodes = subprocess.run(["pgrep", "-f", "stage-universal/Dane.app/Contents/MacOS/greatdane-node"], capture_output=True, text=True).stdout.split()
print(ARCH, "stray nodes after quit:", nodes)
