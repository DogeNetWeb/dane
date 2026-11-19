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
  `zones_loading`, `zones_failed`. In lazy mode Dane uses
  `namespace_synced` when present.
- `/gd/names` is unchanged and works from the namespace alone.

Run: `python3 test_lazy_node.py` (binds 127.0.0.1 only).

Against a real `greatdane-node` (private netns, throwaway `--data`, no
real seeds/mesh):

    unshare -Urn -- sh -c 'ip link set lo up && \
      GREATDANE_NODE=/path/to/greatdane-node python3 test_lazy_node_e2e.py'

The e2e covers launch, `namespace_synced` on stdio, `/gd/names`,
`/gd/tlsa` loading (EDE 14), unowned, and CONNECT 503 loading. Loading
then ok, and a bad-TLSA reject, stay stubbed in `test_lazy_node.py`
(seeding a fetched zone into an isolated node is out of scope).
