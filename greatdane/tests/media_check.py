# Media check on a build: real Widevine DASH playback (Shaka angel-one-widevine + Shaka no_auth license proxy)
# and clear H.264 playback; reports decoder via mozRequestDebugInfo + MOZ_LOG PlatformDecoderModule.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first
import sys, subprocess, time, json, os
from marionette_driver.marionette import Marionette
APP, ARCH = sys.argv[1], sys.argv[2]
prof = gd_guard.profile("gd-test-")
open(prof+"/user.js","w").write('user_pref("marionette.port", 2839);\nuser_pref("greatdane.node.dataDir", "%s");\nuser_pref("greatdane.pep.listen_port", 34875);\nuser_pref("greatdane.doge.listen_port", 23557);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("media.autoplay.default", 0);\n' % gd_guard.ND)
logf = os.path.join(gd_guard.ND, "moz.log")
env = dict(os.environ, MOZ_LOG="PlatformDecoderModule:5,EME:3,sync", MOZ_LOG_FILE=logf)
p = subprocess.Popen(["arch","-"+ARCH,APP,"-marionette","-remote-allow-system-access","-no-remote","-profile",prof],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
m = Marionette(host="127.0.0.1", port=2839); m.start_session(); m.timeout.script = 240
res = {"arch": ARCH}
with m.using_context("chrome"):
    res["install"] = m.execute_async_script("""const done=arguments[arguments.length-1];
      const {GMPInstallManager}=ChromeUtils.importESModule("resource://gre/modules/GMPInstallManager.sys.mjs");
      new GMPInstallManager().simpleCheckAndInstall().then(r=>done(JSON.stringify(r).slice(0,200)),e=>done('ERR '+e));""")
    for _ in range(40):
        v = m.execute_script("const g=n=>Services.prefs.getStringPref('media.'+n+'.version','');return {widevine:g('gmp-widevinecdm'),openh264:g('gmp-gmpopenh264')}")
        if v["widevine"]: break
        time.sleep(3)
    res["versions"] = v
PAGE = r"""(async()=>{const mpd=%s, lic=%s; const out=o=>document.body.setAttribute('data-res',JSON.stringify(o));
 try{ await new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://cdnjs.cloudflare.com/ajax/libs/shaka-player/4.11.7/shaka-player.compiled.js';s.onload=ok;s.onerror=()=>no(new Error('shaka load failed'));document.head.appendChild(s);});
   shaka.polyfill.installAll(); const v=document.createElement('video'); v.muted=true; v.width=640; document.body.appendChild(v);
   const pl=new shaka.Player(); await pl.attach(v); if(lic) pl.configure({drm:{servers:{'com.widevine.alpha':lic}}});
   await pl.load(mpd); await v.play(); await new Promise(r=>setTimeout(r,12000));
   const q=v.getVideoPlaybackQuality(); const vt=pl.getVariantTracks().find(t=>t.active)||{};
   out({ok:v.currentTime>5&&q.totalVideoFrames>0,currentTime:v.currentTime,frames:q.totalVideoFrames,dropped:q.droppedVideoFrames,codecs:vt.videoCodec,height:vt.height,keySystem:pl.keySystem()});
 }catch(e){out({ok:false,err:String(e&&e.code||'')+' '+String(e&&e.message||e)});}})();"""
def play(mpd, lic):
    m.navigate("https://example.com/")
    m.execute_script("const s=document.createElement('script');s.textContent=arguments[0];document.body.appendChild(s);", script_args=[PAGE % (json.dumps(mpd), json.dumps(lic))])
    for _ in range(60):
        r = m.execute_script("return document.body.getAttribute('data-res')")
        if r: break
        time.sleep(2)
    r = json.loads(r) if r else {"ok": False, "err": "timeout"}
    try:
        with m.using_context("chrome"):
            r["debug"] = m.execute_async_script("""const done=arguments[arguments.length-1];
              const b=gBrowser.selectedBrowser; done(null);""")
    except Exception as e: pass
    return r
res["widevine_play"] = play("https://storage.googleapis.com/shaka-demo-assets/angel-one-widevine/dash.mpd","https://cwip-shaka-proxy.appspot.com/no_auth")
res["h264_clear_play"] = play("https://storage.googleapis.com/shaka-demo-assets/angel-one/dash.mpd", None)
print(json.dumps(res, indent=1))
try:
    with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
except Exception: pass
p.wait(30)
import glob, re
lines=[l for f in glob.glob(logf+"*") for l in open(f,errors="replace")]
keys=re.compile(r"(VideoToolbox|AppleVT|FFmpeg|FFVPX|ffvpx|OpenH264|ChromiumCDM|Widevine|GMP|AgnosticDecoder|Create.*Decoder|decoder description)",re.I)
hits=[l.strip()[:220] for l in lines if keys.search(l)]
print("MOZ_LOG lines:",len(lines),"matching:",len(hits))
seen=set()
for h in hits:
    k=re.sub(r"^\S+ \S+ - ","",h)[:120]
    if k not in seen: seen.add(k); print("  ",h)
    if len(seen)>40: break
