# Hardened-runtime check: JS JIT, wasm, video encode+decode+play, on given arch.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import sys, subprocess, tempfile, time
from marionette_driver.marionette import Marionette
APP, ARCH = sys.argv[1], sys.argv[2]
prof = gd_guard.profile("gd-test-")
open(prof+"/user.js","w").write('user_pref("marionette.port", 2838);\nuser_pref("greatdane.node.dataDir", "' + gd_guard.safe(gd_guard.ND) + '");\nuser_pref("greatdane.pep.listen_port", 34874);\nuser_pref("greatdane.doge.listen_port", 23556);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("media.autoplay.default", 0);\n')
p = subprocess.Popen(["arch","-"+ARCH,APP,"-marionette","-remote-allow-system-access","-no-remote","-profile",prof],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
m = Marionette(host="127.0.0.1", port=2838); m.start_session()
m.navigate("data:text/html,<title>hr</title><canvas id=c width=64 height=64></canvas>")
m.timeout.script = 60
r = m.execute_async_script(r"""
const done = arguments[arguments.length-1]; const out = {};
let t=performance.now(), s=0; for (let i=0;i<5e7;i++) s=(s+i*7)|0; out.js_ms=Math.round(performance.now()-t); out.js_sum=s;
const w=new Uint8Array([0,97,115,109,1,0,0,0,1,7,1,96,2,127,127,1,127,3,2,1,0,7,7,1,3,97,100,100,0,0,10,9,1,7,0,32,0,32,1,106,11]);
WebAssembly.instantiate(w).then(({instance})=>{ out.wasm_add=instance.exports.add(40,2);
 const c=document.getElementById('c'), g=c.getContext('2d'); const st=c.captureStream(30);
 const rec=new MediaRecorder(st,{mimeType:'video/webm'}); const ch=[]; rec.ondataavailable=e=>ch.push(e.data);
 let f=0; const iv=setInterval(()=>{g.fillStyle='hsl('+(f++*20)+',80%,50%)';g.fillRect(0,0,64,64);},33);
 rec.onstop=()=>{clearInterval(iv); const v=document.createElement('video'); v.muted=true; document.body.append(v);
   v.src=URL.createObjectURL(new Blob(ch,{type:'video/webm'}));
   v.onerror=()=>{out.video_err=v.error&&v.error.message; done(out);};
   v.play().then(()=>setTimeout(()=>{out.video_time=v.currentTime; out.decoded=v.getVideoPlaybackQuality().totalVideoFrames; done(out);},1500)).catch(e=>{out.video_err=String(e);done(out);});};
 rec.start(); setTimeout(()=>rec.stop(),2000);
}).catch(e=>{out.wasm_err=String(e);done(out);});
""")
with m.using_context("chrome"):
    jit = m.execute_script("return [Services.prefs.getBoolPref('javascript.options.baselinejit'), Services.prefs.getBoolPref('javascript.options.ion'), Services.prefs.getBoolPref('javascript.options.wasm'), Services.appinfo.XPCOMABI]")
print(ARCH, "prefs(baseline,ion,wasm,abi):", jit, "result:", r)
try:
    with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
except Exception: pass
p.wait(30); print(ARCH, "exit", p.returncode)
