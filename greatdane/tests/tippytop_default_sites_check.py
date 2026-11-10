#!/usr/bin/env python3
"""Every Dane default top-site host must have a bundled tippytop icon whose files exist.
Run from the source tree root: python3 greatdane/tests/tippytop_default_sites_check.py"""
import json, os, re, sys
from urllib.parse import urlparse
TT = "browser/components/topsites/content/tippytop"
sites = json.load(open(os.path.join(TT, "top_sites.json")))
by = {d: s for s in sites for d in s["domains"]}
fx = "browser/app/profile/firefox.js"
hosts = ["youtube.com", "pepecoin.surf", "amazon.com", "dogecoin.surf", "grokipedia.com", "x.com", "greatdane.doge"]
if os.path.exists(fx):
    m = re.search(r'pref\("browser\.newtabpage\.activity-stream\.default\.sites",\s*"([^"]*)"', open(fx).read())
    if m:
        hosts = [re.sub(r"^www\.", "", urlparse(u).hostname) for u in m.group(1).split(",") if u]
bad = 0
for h in hosts:
    s = by.get(h)
    files = [s["image_url"], s["favicon_url"]] if s else []
    ok = bool(s) and all(os.path.exists(os.path.join(TT, f)) for f in files)
    print(("PASS " if ok else "FAIL ") + h + (" -> " + ", ".join(files) if s else " -> no tippytop entry"))
    bad += not ok
sys.exit(1 if bad else 0)
