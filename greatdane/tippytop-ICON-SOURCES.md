# Bundled tippytop icons for the Dane default top-site tiles

`browser.newtabpage.activity-stream.default.sites` (browser/app/profile/firefox.js) ships seven tiles.
youtube.com, amazon.com and x.com already had upstream tippytop entries. The four entries below are
added to `browser/components/topsites/content/tippytop/top_sites.json`. jar.mn needs no change:
`content/activity-stream/data/content/tippytop/ (./content/tippytop/*)` already packages `images/` and `favicons/`.
With a bundled icon, the new-tab page shows the local image instead of rendering a screenshot of the
tile. Nothing else changes: the screenshot feature, prefs and identifiers are untouched.
TippyTopProvider matches the exact host after stripping `www.`.

| Host (exact) | Files | Source | Processing | Rights |
|---|---|---|---|---|
| pepecoin.surf | images/pepecoin-surf@2x.png (192px), favicons/pepecoin-surf.png (32px) | pepecoin.surf site source `pepeweb/src/static/img/pepenet-logo.png` (1024px; the raster of the site's favicon `pepenet-logo.svg`) | Lanczos resize | Owner's own site artwork (same owner as Dane) |
| dogecoin.surf | images/dogecoin-surf@2x.png, favicons/dogecoin-surf.png | dogecoin.surf site source `dogesurf/dogeweb/static/img/icon-192.png` and `icon-32.png` (the icons named in the site's manifest and favicon links) | byte copy | Owner's own site artwork |
| greatdane.doge | images/greatdane-doge@2x.png, favicons/greatdane-doge.png | in-tree branding `browser/branding/greatdane/default256.png` and `default32.png` | 256 to 192 Lanczos resize; 32px byte copy | Dane branding (owner) |
| grokipedia.com | images/grokipedia-com@2x.png, favicons/grokipedia-com.png | no local asset existed, so it was fetched from the live site `https://grokipedia.com/` favicon (SVG, sha256 f359ab66de8d527054110fd61fe5acc53413bc4399f95cd42127a9345cb042d3) on 2026-11-10 at 4:00 PM CT | rsvg-convert on white, 144px glyph padded into a 192px tile; 32px favicon; `background_color` `#fff` | Third-party mark (xAI). No license grant. Used only as the site's own icon on a tile that points at that site, the same nominative use as the upstream tippytop third-party logos. Owner to confirm. |
