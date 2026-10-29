"""Wire test: does the 170846 Dane node self-advertise an IPv6 addr? Fake pep peer on [::1].
Usage: wire_v6adv.py NODEBIN [adv]   (adv => IDX_ADVERTISE_V6=1). Throwaway dirs via gd_guard."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "tools"))
import gd_guard, os, sys, socket, struct, hashlib, time, subprocess, ipaddress, threading
MAGIC=bytes([0xC0,0xA0,0xF0,0xE0]); FAKE_SELF="2a01:4f8:dead::5"
def msg(cmd,pl=b""):
    return MAGIC+cmd.encode().ljust(12,b"\0")+struct.pack("<I",len(pl))+hashlib.sha256(hashlib.sha256(pl).digest()).digest()[:4]+pl
def na(ip,port): return struct.pack("<Q",1)+ipaddress.ip_address(ip).packed.rjust(16,b"\0") if False else struct.pack("<Q",1)+ipaddress.IPv6Address(ip).packed+struct.pack(">H",port)
def version():
    ua=b"/pepenet-wiretest:0.1/"
    return struct.pack("<iQq",70015,1,int(time.time()))+na(FAKE_SELF,33874)+na("::",0)+struct.pack("<Q",12345)+bytes([len(ua)])+ua+struct.pack("<i",1300000)+b"\1"
def rv(b,o):
    v=b[o]; o+=1
    if v==0xfd: v=struct.unpack_from("<H",b,o)[0]; o+=2
    elif v==0xfe: v=struct.unpack_from("<I",b,o)[0]; o+=4
    return v,o
def addrs(pl):
    n,o=rv(pl,0); out=[]
    for _ in range(n):
        ip=ipaddress.IPv6Address(pl[o+12:o+28]); port=struct.unpack(">H",pl[o+28:o+30])[0]; o+=30
        out.append(str(ip.ipv4_mapped or ip)+":%d"%port)
    return out
adv=len(sys.argv)>2
ls=socket.socket(socket.AF_INET6); ls.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); ls.bind(("::1",0)); ls.listen(4)
P=ls.getsockname()[1]
env={k:v for k,v in os.environ.items() if k!="IDX_ADVERTISE_V6"}
if adv: env["IDX_ADVERTISE_V6"]="1"
log=open(os.path.join(gd_guard.ND,"node.stderr"),"w")
cmd=[sys.argv[1],"--data",gd_guard.ND,"--only","pep","--no-snapshot-fetch","--listen-port","47391","--seeds","[::1]:%d"%P]
print("cmd:"," ".join(cmd),"IDX_ADVERTISE_V6=%s"%("1" if adv else "unset"))
p=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
seen=[]; ls.settimeout(30); end=time.time()+40
def handle(c):
    c.settimeout(2); buf=b""; sent=False
    while time.time()<end:
        try: d=c.recv(65536)
        except socket.timeout: continue
        except OSError: break
        if not d: break
        buf+=d
        while len(buf)>=24:
            ln=struct.unpack_from("<I",buf,16)[0]
            if len(buf)<24+ln: break
            cm=buf[4:16].rstrip(b"\0").decode(); pl=buf[24:24+ln]; buf=buf[24+ln:]
            e=(cm,addrs(pl) if cm in("addr","dnaddr") else len(pl)); seen.append(e); print("recv",e,flush=True)
            if cm=="version":
                fr=ipaddress.IPv6Address(pl[20+8+12-12+8:20+8+16+8][:16]) if False else None
                print("  node version addr_from:",ipaddress.IPv6Address(pl[54:70]),flush=True)
                if not sent: c.sendall(msg("version",version())); sent=True
                c.sendall(msg("verack")); c.sendall(msg("dngetaddr")); c.sendall(msg("getaddr")); print("  sent version+verack",flush=True)
try:
    while time.time()<end:
        try: c,a=ls.accept()
        except socket.timeout: break
        print("accepted from",a,flush=True); threading.Thread(target=handle,args=(c,),daemon=True).start()
    time.sleep(max(0,end-time.time()))
finally:
    p.terminate(); p.wait(10); log.close()
print("--- node log (self/announce/listen lines):")
for l in open(os.path.join(gd_guard.ND,"node.stderr")):
    print(" ",l.rstrip())
v6=[a for c_,x in seen if c_ in("addr","dnaddr") for a in x if a.startswith(FAKE_SELF)]
print("RESULT: own IPv6 (FAKE_SELF) self-advertised:",bool(v6),v6)
