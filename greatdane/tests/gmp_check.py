# GMP check: download/activate Widevine + OpenH264 via the GMP manager, then
# Widevine: MediaKeys + license-request message from the CDM; ClearKey: full EME session (license accepted);
# OpenH264: H.264-only WebRTC loopback, frames decoded.
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import sys, subprocess, tempfile, time, json, os
from marionette_driver.marionette import Marionette
APP, ARCH = sys.argv[1], sys.argv[2]
prof = gd_guard.profile("gd-test-")
open(prof+"/user.js","w").write('''user_pref("marionette.port", 2838);
user_pref("greatdane.node.dataDir", "%s");\nuser_pref("greatdane.pep.listen_port", 34874);\nuser_pref("greatdane.doge.listen_port", 23556);\nuser_pref("greatdane.legacy.certCleanup", false);
user_pref("greatdane.legacy.import", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("media.eme.enabled", true);
user_pref("media.navigator.permission.disabled", true);
user_pref("media.peerconnection.ice.loopback", true);
user_pref("media.peerconnection.ice.obfuscate_host_addresses", false);
''' % gd_guard.safe(gd_guard.ND))
p = subprocess.Popen(["arch","-"+ARCH,APP,"-marionette","-remote-allow-system-access","-no-remote","-profile",prof],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
m = Marionette(host="127.0.0.1", port=2838); m.start_session(); m.timeout.script = 240

# ABI gate: the running app must be the requested arch (arch -x86_64 => x86_64-gcc3, arm64 => aarch64-gcc3).
_WANT_ABI = {"arm64": "aarch64-gcc3", "x86_64": "x86_64-gcc3"}[ARCH]
with m.using_context("chrome"): _ABI = m.execute_script("return Services.appinfo.XPCOMABI")
print("ABI-MARKER requested=%s XPCOMABI=%s %s" % (ARCH, _ABI, "OK" if _ABI == _WANT_ABI else "MISMATCH"), flush=True)
if _ABI != _WANT_ABI:
    try:
        with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
    except Exception: pass
    p.wait(30); sys.exit("FAIL: requested %s but app runs %s" % (ARCH, _ABI))
res = {"arch": ARCH}
with m.using_context("chrome"):
    res["install"] = m.execute_async_script("""const done=arguments[arguments.length-1];
      const {GMPInstallManager}=ChromeUtils.importESModule("resource://gre/modules/GMPInstallManager.sys.mjs");
      new GMPInstallManager().simpleCheckAndInstall().then(r=>done({ok:true,r:JSON.stringify(r).slice(0,200)}),e=>done({ok:false,err:String(e&&e.message||e)}));""")
    t0=time.time()
    while time.time()-t0 < 120:
        v = m.execute_script("const g=n=>Services.prefs.getStringPref('media.'+n+'.version','');return {widevine:g('gmp-widevinecdm'),openh264:g('gmp-gmpopenh264'),abi:Services.appinfo.XPCOMABI}")
        if v["widevine"] and v["openh264"]: break
        time.sleep(3)
    res["versions"] = v
m.navigate("file://"+os.path.expanduser("~/gd-pending/gmp_test.html"))
res["widevine"] = m.execute_async_script(r"""const done=arguments[arguments.length-1];
 const pssh=Uint8Array.from(atob('AAAAW3Bzc2gAAAAA7e+LqXnWSs6jyCfc1R0h7QAAADsIARIQ62dqu8s0Xpa7z2FmMPGj2hoNd2lkZXZpbmVfdGVzdCIQZmtqM2xqYVNkZmFsa3IzaioCSEQyAA=='),c=>c.charCodeAt(0));
 navigator.requestMediaKeySystemAccess('com.widevine.alpha',[{initDataTypes:['cenc'],videoCapabilities:[{contentType:'video/mp4; codecs="avc1.42E01E"'}]}])
 .then(a=>a.createMediaKeys()).then(k=>{const s=k.createSession(); const to=setTimeout(()=>done({ok:false,err:'no message in 30s'}),30000);
   s.addEventListener('message',e=>{clearTimeout(to);done({ok:true,messageType:e.messageType,bytes:e.message.byteLength});});
   return s.generateRequest('cenc',pssh);}).catch(e=>done({ok:false,err:String(e)}));""")
res["clearkey"] = m.execute_async_script(r"""const done=arguments[arguments.length-1];
 const b64u=a=>btoa(String.fromCharCode(...a)).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
 const kid=new Uint8Array(16).fill(1), key=new Uint8Array(16).fill(2);
 const init=new TextEncoder().encode(JSON.stringify({kids:[b64u(kid)]}));
 navigator.requestMediaKeySystemAccess('org.w3.clearkey',[{initDataTypes:['keyids'],videoCapabilities:[{contentType:'video/mp4; codecs="avc1.42E01E"'}]}])
 .then(a=>a.createMediaKeys()).then(k=>{const s=k.createSession();
   s.addEventListener('message',e=>{const lic=new TextEncoder().encode(JSON.stringify({keys:[{kty:'oct',kid:b64u(kid),k:b64u(key)}]}));
     s.update(lic).then(()=>{const st=[];s.keyStatuses.forEach(v=>st.push(v));done({ok:st[0]==='usable',keyStatuses:st});}).catch(e=>done({ok:false,err:String(e)}));});
   return s.generateRequest('keyids',init);}).catch(e=>done({ok:false,err:String(e)}));""")
res["openh264"] = m.execute_async_script(r"""const done=arguments[arguments.length-1];
 const c=document.getElementById('c'),g=c.getContext('2d');let f=0;setInterval(()=>{g.fillStyle='hsl('+(f++*15)+',80%,50%)';g.fillRect(0,0,320,240);g.fillStyle='#000';g.fillText(f,10,20);},33);
 const st=c.captureStream(30), a=new RTCPeerConnection(), b=new RTCPeerConnection();
 const gw=pc=>pc.iceGatheringState==='complete'?Promise.resolve():new Promise(r=>pc.addEventListener('icegatheringstatechange',()=>pc.iceGatheringState==='complete'&&r()));
 const tr=a.addTransceiver(st.getVideoTracks()[0],{direction:'sendonly',streams:[st]});
 const h=RTCRtpSender.getCapabilities('video').codecs.filter(x=>x.mimeType==='video/H264');
 if(!h.length) return done({ok:false,err:'no H264 in sender capabilities'});
 tr.setCodecPreferences(h);
 (async()=>{await a.setLocalDescription(); await gw(a); await b.setRemoteDescription(a.localDescription); await b.setLocalDescription(); await gw(b); await a.setRemoteDescription(b.localDescription);
  await new Promise(r=>setTimeout(r,8000)); const s=await b.getStats(); let fd=0,codec='';
  window.__types=[];s.forEach(r=>window.__types.push(r.type+':'+(r.kind||'')));s.forEach(r=>{if(r.type==='inbound-rtp'&&r.kind==='video'){fd=r.framesDecoded;window.__dec=r.decoderImplementation;const cc=s.get(r.codecId);codec=cc&&cc.mimeType;}});
  const os=await a.getStats();let enc='';os.forEach(r=>{if(r.type==='outbound-rtp')enc=r.encoderImplementation;});done({ok:fd>0&&codec==='video/H264',framesDecoded:fd,codec,decoder:window.__dec,encoder:enc,ice:a.iceConnectionState+'/'+b.iceConnectionState,types:window.__types.join(',')});})().catch(e=>done({ok:false,err:String(e)}));""")
print(json.dumps(res))
try:
    with m.using_context("chrome"): m.execute_script("Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit)")
except Exception: pass
p.wait(30)
