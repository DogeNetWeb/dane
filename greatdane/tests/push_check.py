import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard  # must be first: real-profile guard + throwaway dirs
import sys, subprocess, tempfile, time, json
from marionette_driver.marionette import Marionette
A,ARCH=sys.argv[1],sys.argv[2]; prof=gd_guard.profile("gd-push-")
open(prof+"/user.js","w").write('user_pref("marionette.port", 2838);\nuser_pref("greatdane.node.dataDir", "' + gd_guard.safe(gd_guard.ND) + '");\nuser_pref("greatdane.pep.listen_port", 34874);\nuser_pref("greatdane.doge.listen_port", 23556);\nuser_pref("greatdane.legacy.certCleanup", false);\nuser_pref("greatdane.legacy.import", false);\nuser_pref("browser.shell.checkDefaultBrowser", false);\n')
p=subprocess.Popen(["arch","-"+ARCH,A,"-marionette","-remote-allow-system-access","-no-remote","-profile",prof],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
m=Marionette(host="127.0.0.1",port=2838); m.start_session(); m.timeout.script=90
with m.using_context("chrome"):
  pre=m.execute_script("""let g=n=>{try{return Services.prefs.getBoolPref(n)}catch(e){return 'unset'}};
   return {enabled:g('dom.push.enabled'),conn:g('dom.push.connection.enabled'),server:Services.prefs.getStringPref('dom.push.serverURL','')}""")
  if pre["conn"] is False: m.execute_script("Services.prefs.setBoolPref('dom.push.connection.enabled', true)")
  r=m.execute_async_script("""const done=arguments[arguments.length-1]; const out={};
   const ps=Cc['@mozilla.org/push/Service;1'].getService(Ci.nsIPushService);
   const pr=Services.scriptSecurityManager.createContentPrincipal(Services.io.newURI('https://greatdane.example/'),{});
   Services.perms.addFromPrincipal(pr,'desktop-notification',Services.perms.ALLOW_ACTION);
   const go=()=>ps.subscribe('https://greatdane.example/sw', pr, (st, sub)=>{out.status='0x'+(st>>>0).toString(16); out.ok=Components.isSuccessCode(st)&&!!sub;
        out.endpointHost=sub? new URL(sub.endpoint).host : null;
        if(sub) ps.unsubscribe('https://greatdane.example/sw', pr, (s2,ok)=>{out.unsub=ok; done(out)}); else done(out);});
   setTimeout(go,5000); setTimeout(()=>done(Object.assign(out,{timeout:true})),80000);""")
print(json.dumps({"arch":ARCH,"pre":pre,"sub":r}))
print("RESULT","PASS" if pre["enabled"] is True and r.get("ok") else "FAIL")
m.delete_session(); p.terminate(); p.wait(30)
