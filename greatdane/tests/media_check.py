# Media check on a build: real Widevine DASH playback (Shaka angel-one-widevine + Shaka no_auth license proxy)
# and clear H.264 playback; reports decoder via mozRequestDebugInfo + MOZ_LOG PlatformDecoderModule.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first
import sys, subprocess, time, json, os
from marionette_driver.marionette import Marionette
APP, ARCH = sys.argv[1], sys.argv[2]
ONLY = sys.argv[3].split(",") if len(sys.argv) > 3 else None
prof = gd_guard.profile("gd-test-")
open(prof+"/user.js","w").write('user_pref("marionette.port", 2839);\nuser_pref("greatdane.node.dataDir", "%s");\nuser_pref("greatdane.pep.listen_port", 34875);\nuser_pref("greatdane.doge.listen_port", 23557);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\nuser_pref("media.autoplay.default", 0);\nuser_pref("media.block-autoplay-until-in-foreground", false);\nuser_pref("media.suspend-background-video.enabled", false);\nuser_pref("widget.macos.occlusion-tracking.enabled", false);\nuser_pref("dom.min_background_timeout_value", 4);\n' % gd_guard.safe(gd_guard.ND))
logf = os.path.join(gd_guard.ND, "moz.log")
env = dict(os.environ, MOZ_LOG=os.environ.get("GD_MOZ_LOG","PlatformDecoderModule:5,EME:5,GMP:4,sync"), MOZ_LOG_FILE=logf)
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
 const ser=e=>{if(!e||typeof e!=='object')return e; if(e.code!==undefined)return {code:e.code,cat:e.category,data:(e.data||[]).map(ser)}; if(e instanceof ArrayBuffer)return 'buf'+e.byteLength; try{return JSON.parse(JSON.stringify(e))}catch(_){return String(e)}};
 const prog=o=>document.body.setAttribute('data-prog',JSON.stringify(o));
 prog({stage:'start'}); try{ await new Promise((ok,no)=>{const s=document.createElement('script');s.src='https://cdnjs.cloudflare.com/ajax/libs/shaka-player/4.11.7/shaka-player.compiled.js';s.onload=ok;s.onerror=()=>no(new Error('shaka load failed'));document.head.appendChild(s);});
   prog({stage:'shaka-loaded'}); shaka.polyfill.installAll(); const v=document.createElement('video'); v.muted=true; v.width=640; document.body.appendChild(v);
   const pl=new shaka.Player(); await pl.attach(v); pl.configure({preferredVideoCodecs:['avc1'],restrictions:{maxHeight:720}}); if(lic) pl.configure({drm:{servers:{'com.widevine.alpha':lic}}});
   const lics=[],reqs=[]; pl.getNetworkingEngine().registerRequestFilter((t,r)=>{if(t==shaka.net.NetworkingEngine.RequestType.LICENSE)reqs.push({uri:r.uris[0],body:r.body&&r.body.byteLength});}); pl.getNetworkingEngine().registerResponseFilter((t,r)=>{if(t==shaka.net.NetworkingEngine.RequestType.LICENSE)lics.push({status:r.status,bytes:r.data.byteLength});});
   pl.addEventListener('error',e=>prog({err:JSON.stringify(ser(e.detail)).slice(0,600)}));
   prog({stage:'loading'}); await pl.load(mpd); prog({stage:'loaded',rs:v.readyState}); await Promise.race([v.play(),new Promise(r=>setTimeout(r,8000))]); prog({stage:'playing',ct:v.currentTime,paused:v.paused}); const t0=v.currentTime; const s=[];
   for(let i=0;i<12;i++){await new Promise(r=>setTimeout(r,1000)); const q=v.getVideoPlaybackQuality(); s.push([+v.currentTime.toFixed(2),q.totalVideoFrames,v.readyState,v.paused?1:0,v.buffered.length?+v.buffered.end(0).toFixed(1):-1]); prog({samples:s});}
   const q=v.getVideoPlaybackQuality(); const vt=pl.getVariantTracks().find(t=>t.active)||{};
   out({ok:v.currentTime-t0>5&&q.totalVideoFrames>0,t0,currentTime:v.currentTime,frames:q.totalVideoFrames,dropped:q.droppedVideoFrames,samples:s,codecs:vt.videoCodec,height:vt.height,keySystem:pl.keySystem(),licenses:lics,mediaKeys:!!v.mediaKeys,vis:document.visibilityState,err:v.error&&v.error.message});
 }catch(e){out({ok:false,err:JSON.stringify(ser(e)).slice(0,700)||String(e),lics:lics,reqs:reqs});}})();"""
WARM = r"""const done=arguments[arguments.length-1]; (async()=>{const out=[];
 for(let i=0;i<4;i++){ try{ const a=await navigator.requestMediaKeySystemAccess('com.widevine.alpha',[{initDataTypes:['cenc'],videoCapabilities:[{contentType:'video/mp4; codecs="avc1.42E01E"'}]}]);
   const k=await a.createMediaKeys(); const s=k.createSession(); const msg=new Promise((ok,no)=>{s.onmessage=e=>ok(e.messageType+':'+e.message.byteLength); setTimeout(()=>no(new Error('no message')),15000);});
   const pssh=new Uint8Array([0,0,0,0x34,0x70,0x73,0x73,0x68,0,0,0,0,0xed,0xef,0x8b,0xa9,0x79,0xd6,0x4a,0xce,0xa3,0xc8,0x27,0xdc,0xd5,0x1d,0x21,0xed,0,0,0,0x14,0x08,0x01,0x12,0x10,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]);
   await s.generateRequest('cenc',pssh); out.push('ok '+await msg); break; }catch(e){ out.push('try'+i+' '+e); await new Promise(r=>setTimeout(r,5000)); } }
 done(out);})();"""
def play(mpd, lic):
    m.navigate("https://example.com/")
    m.execute_script("const s=document.createElement('script');s.textContent=arguments[0];document.body.appendChild(s);", script_args=[PAGE % (json.dumps(mpd), json.dumps(lic))])
    r=None
    for _ in range(120):
        r = m.execute_script("return document.body.getAttribute('data-res')")
        if r: break
        time.sleep(2)
    if r: return json.loads(r)
    try: diag = m.execute_script("return [location.href, document.readyState, document.body ? document.body.getAttribute('data-prog') : 'nobody', document.querySelectorAll('script').length, typeof shaka]")
    except Exception as e: diag = "diag-failed: %r" % e
    return {"ok": False, "err": "timeout", "diag": diag}
WV = [
 ("google-tears-uat", "https://storage.googleapis.com/wvmedia/cenc/h264/tears/tears.mpd", "https://proxy.uat.widevine.com/proxy?provider=widevine_test"),
 ("unified-tears-widevine-proxy", "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel-dash-widevine.ism/.mpd", "https://widevine-proxy.appspot.com/proxy"),
 ("bitmovin-art-of-motion", "https://bitmovin-a.akamaihd.net/content/art-of-motion_drm/mpds/11331.mpd", "https://cwip-shaka-proxy.appspot.com/no_auth"),
 ("shaka-angel-one", "https://storage.googleapis.com/shaka-demo-assets/angel-one-widevine/dash.mpd", "https://cwip-shaka-proxy.appspot.com/no_auth"),
]
FILEPAGE = r"""(async()=>{const out=o=>document.body.setAttribute('data-res',JSON.stringify(o));
 try{const v=document.createElement('video'); v.muted=true; v.src=%s; document.body.appendChild(v);
  await Promise.race([v.play(),new Promise(r=>setTimeout(r,8000))]); const t0=v.currentTime,s=[];
  for(let i=0;i<8;i++){await new Promise(r=>setTimeout(r,1000)); const q=v.getVideoPlaybackQuality(); s.push([+v.currentTime.toFixed(2),q.totalVideoFrames,v.readyState]);}
  const q=v.getVideoPlaybackQuality(); out({ok:v.currentTime-t0>4&&q.totalVideoFrames>0,t0,currentTime:v.currentTime,frames:q.totalVideoFrames,samples:s,err:v.error&&v.error.message});
 }catch(e){out({ok:false,err:String(e)});}})();"""
def playfile(url):
    m.navigate("https://example.com/")
    m.execute_script("const s=document.createElement('script');s.textContent=arguments[0];document.body.appendChild(s);", script_args=[FILEPAGE % json.dumps(url)])
    for _ in range(40):
        r = m.execute_script("return document.body.getAttribute('data-res')")
        if r: return json.loads(r)
        time.sleep(1)
    return {"ok": False, "err": "timeout"}
if not ONLY or "h264file" in ONLY: res["h264_file_play"] = playfile("https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4")
if not ONLY or "h264" in ONLY: res["h264_clear_play"] = play("https://storage.googleapis.com/shaka-demo-assets/angel-one/dash.mpd", None)
if not ONLY or "cleartears" in ONLY: res["h264_clear_tears_mse"] = play("https://storage.googleapis.com/wvmedia/clear/h264/tears/tears.mpd", None)
res["widevine_play"] = {}
if not ONLY or any(n in ONLY for n,_,_ in WV):
    m.navigate("https://example.com/"); res["widevine_warmup"] = m.execute_async_script(WARM)
for name, mpd, lic in WV:
    if ONLY and name not in ONLY: continue
    res["widevine_play"][name] = play(mpd, lic)
print(json.dumps(res, indent=1))
try:
    with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
except Exception: pass
p.wait(30)
import glob, re
lines=[l for f in glob.glob(logf+"*") for l in open(f,errors="replace")]
keys=re.compile(r"(EME|MediaKey|CDM|Decrypt|license|VideoToolbox|AppleVT|FFmpeg|FFVPX|ffvpx|OpenH264|ChromiumCDM|Widevine|GMP|AgnosticDecoder|Create.*Decoder|decoder description)",re.I)
hits=[l.strip()[:220] for l in lines if keys.search(l)]
print("MOZ_LOG lines:",len(lines),"matching:",len(hits))
seen=set()
for h in hits:
    k=re.sub(r"^\S+ \S+ - ","",h)[:120]
    if k not in seen: seen.add(k); print("  ",h)
    if len(seen)>80: break
