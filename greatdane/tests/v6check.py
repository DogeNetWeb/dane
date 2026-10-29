# v6check: Dane launches its pep/doge nodes; check dual-stack inbound on ::1 + 127.0.0.1, listen=false, advertise-v6 off.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import os, sys, subprocess, tempfile, time, socket, json
from marionette_driver.marionette import Marionette
APP, LISTEN, DD = sys.argv[1], sys.argv[2] == "on", gd_guard.ND
PP, DP, MP = 34874, 23556, 2838
prof = gd_guard.profile("gd-v6-")
up = ['user_pref("marionette.port", %d);' % MP, 'user_pref("greatdane.legacy.certCleanup", false);', 'user_pref("greatdane.legacy.import", false);',
      'user_pref("browser.shell.checkDefaultBrowser", false);', 'user_pref("greatdane.node.dataDir", "%s");' % DD,
      'user_pref("greatdane.pep.listen_port", %d);' % PP, 'user_pref("greatdane.doge.listen_port", %d);' % DP]
if not LISTEN: up += ['user_pref("greatdane.pep.listen", false);', 'user_pref("greatdane.doge.listen", false);']
open(prof + "/user.js", "w").write("\n".join(up) + "\n")
env = dict(os.environ); env.pop("IDX_ADVERTISE_V6", None)
p = subprocess.Popen(["arch", "-arm64", APP, "-marionette", "-remote-allow-system-access", "-no-remote", "-profile", prof], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
m = Marionette(host="127.0.0.1", port=MP); m.start_session()
fails = 0
def chk(ok, msg):
    global fails; print(("PASS " if ok else "FAIL ") + msg); fails += (not ok)
st = None
for i in range(150):
    with m.using_context("chrome"):
        st = m.execute_script("""const {GreatDANE}=ChromeUtils.importESModule('resource:///modules/GreatDANE.sys.mjs');
          return [...GreatDANE._chains.values()].map(c=>({coin:c.coin,state:c.state,s:c.status}))""")
    if st and all(c["s"] and c["s"].get("listen") not in (None, "pending") for c in st): break
    time.sleep(2)
for c in st: print(c["coin"], json.dumps({k: (c["s"] or {}).get(k) for k in ("state","listen","listen_port","listen_error","peers_in","peers_out","data_dir")}))
def conn(host, port):
    s = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM); s.settimeout(3)
    try: s.connect((host, port)); s.close(); return True
    except Exception: return False
time.sleep(2)
mine = [l for l in subprocess.run(["pgrep", "-fl", "greatdane-node"], capture_output=True, text=True).stdout.splitlines() if DD in l]
print("node procs:", mine)
chk(len(mine) == 2, "two embedded nodes using the throwaway data dir")
chk(not any("--advertise-v6" in l for l in mine), "no --advertise-v6 on node command lines")
for l in mine:
    pid = l.split()[0]
    e = subprocess.run(["ps", "eww", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout
    chk("IDX_ADVERTISE_V6" not in e, "pid %s env has no IDX_ADVERTISE_V6" % pid)
S = {c["coin"]: (c["s"] or {}) for c in st}
if LISTEN:
    chk(S["pep"].get("listen") == "ok" and S["pep"].get("listen_port") == PP, "pep listen ok on %d" % PP)
    chk(conn("127.0.0.1", PP), "pep inbound 127.0.0.1:%d" % PP)
    chk(conn("::1", PP), "pep inbound [::1]:%d" % PP)
    ls = subprocess.run(["lsof", "-nP", "-iTCP:%d" % PP, "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    print(ls.strip()); chk("IPv6" in ls, "pep listener socket is IPv6 (dual-stack)")
    if S["doge"].get("listen") == "ok":
        chk(conn("127.0.0.1", DP), "doge inbound 127.0.0.1:%d" % DP); chk(conn("::1", DP), "doge inbound [::1]:%d" % DP)
    else: print("NOTE doge listen =", S["doge"].get("listen"))
else:
    for c, s in S.items(): print(c, "listen status:", s.get("listen"))
    for port in (PP, DP):
        chk(not conn("127.0.0.1", port), "no inbound 127.0.0.1:%d" % port)
        chk(not conn("::1", port), "no inbound [::1]:%d" % port)
    for l in mine: chk("--no-listen" in l, "node started with --no-listen: pid " + l.split()[0])
with m.using_context("chrome"):
    try: m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
    except Exception: pass
p.wait(30); time.sleep(5)
left = [l for l in subprocess.run(["pgrep", "-fl", "greatdane-node"], capture_output=True, text=True).stdout.splitlines() if DD in l]
chk(not left, "no stray nodes after quit")
print("RESULT", "PASS" if not fails else "FAIL", "fails=%d" % fails)
