# Lazy-node contract (Dane side)

Dane wiring for Keeper's on-demand zone fetch (`keeper/lazy-node`).
The launch pref `greatdane.node.lazy` is still off by default. This
directory is a localhost-only stub and a policy test; it does not start
a real mesh node.

## Confirmed contract

- Flag/env: `--lazy` and `GREATDANE_NODE_LAZY=1`, plus
  `--lazy-cache-dir <node data dir>` / `GREATDANE_NODE_LAZY_CACHE_DIR`,
  passed only when the pref is on. Other tunables (`--lazy-wait-ms`,
  cache caps, TTLs) keep the node's defaults.
- EDE 14 (Not Ready, still fetching) and EDE 22 (fetch failed,
  retrying) are both retryable loading. Plain SERVFAIL is not.
- `/gd/tlsa` for an owned-but-not-ready name returns
  `{status:"loading", rcode:"SERVFAIL", ede:14|22,
  phase:"fetching"|"fetch_failed", retry_ms:1000}` and never
  unowned/no_tlsa/bad_record. `retry_ms` is honored inside the 10s
  budget. `no_tlsa` is final only when the node itself returns that
  status (it decides after 2 peers).
- A cold CONNECT through the PAC proxy waits, then returns
  `503` + `Retry-After: 1` + `X-GreatDANE-Status: loading`. Dane shows
  `GD_ZONE_LOADING` and auto-retries; this is not a security error.
- Stdio status adds `lazy`, `namespace_synced`, `zones_cached`,
  `zones_loading`, `zones_failed`, `namespace_sync_basis`
  (`peers`/`offline`/`none`), and `best_known_height`. In lazy mode
  Dane follows the live `namespace_synced` flag and does not latch it.
  Lazy mode also restores the height >= activation floor. The
  test-only pref `greatdane.node.lazyAllowPreActivation` (default off)
  is honoured only under automation (`Cu.isInAutomation`); if set
  outside automation it is ignored, logged once per session, and
  shown on about:dane with the full pref name and an about:config
  reset hint.
  The env alias `GREATDANE_LAZY_ALLOW_PRE_ACTIVATION` is for these
  Python tests only. A missing `namespace_synced` flag uses the
  full-mode rule (`passes >= 1` and the same floor). `best_known_height`
  is applied only in lazy mode when `namespace_sync_basis` is
  `offline` (`height+2 >=` that tip). Full mode and online (peers)
  lazy ignore it, so a hostile high-water mark cannot stall them.
- Static prefs `greatdane.node.lazy` and
  `greatdane.node.lazyTimeoutSec` (RelaxedAtomicBool /
  RelaxedAtomicInt32, mirror: always) plus the `greatdane` entry in
  `modules/libpref/moz.build` `pref_groups` are applied to a Firefox
  tree with `greatdane/tools/apply-greatdane-overlay.sh` (N1 hook,
  which calls `apply-greatdane-static-prefs.sh`). The apply is
  idempotent and all-or-nothing: a second run is a no-op success;
  a partial pre-state fails before any write. The script fails
  loudly if the patches do not apply or the result is missing or
  duplicated, in `--check` mode too. Names stay under `greatdane.*`.
  Patch 0163 commits the same libpref edits into the series, so on a
  tree built from the series the hook reports "already applied".
  `greatdane/tools/apply-dane-series.sh` runs the hook after the
  series and before clobber / configure (`--hook-only` for pipelines
  that apply the series themselves), fails closed, and commits the
  result. See `greatdane/tools/OVERLAY-HOOK.md`.
- `/gd/names` is unchanged and works from the namespace alone.

Run: `python3 test_lazy_node.py` (binds 127.0.0.1 only).

`python3 test_overlay_hook.py` checks the hook wiring with small
synthetic libpref files in temp git repos (no Firefox tree, no
network). With `GREATDANE_FIREFOX_SRC` set to an unpatched Firefox
tree, it also checks that the series' libpref hunks leave the hook
nothing to do. `test_static_prefs_patch.py` needs
`GREATDANE_FIREFOX_SRC` for its apply cases (there is no default tree).

Against a real `greatdane-node` (private netns, throwaway `--data`, no
real seeds/mesh):

    unshare -Urn -- sh -c 'ip link set lo up && \
      GREATDANE_NODE=/path/to/greatdane-node python3 test_lazy_node_e2e.py'

The e2e covers launch, a healthy fixture (height > 0, seller/buyer
zeroblob), default 3000 ms and 300 ms waits with no crash, `--lazy-wait-ms`
reaching the proxy and beating the env, `/gd/names`, `/gd/tlsa` loading
(EDE 14, then EDE 22 if the node emits it), unowned, CONNECT 503 loading,
and offline `namespace_synced` becoming true after the sync grace.
Loading then ok, and a bad-TLSA reject, stay stubbed in
`test_lazy_node.py` (seeding a fetched zone into an isolated node is
out of scope).
