# Lazy-node contract (Dane side)

Parametric wiring for Keeper's on-demand zone fetch. The launch pref is
off until the node flag lands. This directory is a localhost-only stub
and a policy test; it does not start a real node or talk to the mesh.

## Placeholders

- `TODO-KEEPER-FLAG`: CLI flag `--lazy` and env `GREATDANE_NODE_LAZY=1`.
  Passed only when `greatdane.node.lazy` is true. Replace when Keeper
  publishes the real flag or env name.
- `TODO-KEEPER-EDE`: Extended DNS Error code constant is `0` (unassigned).
  While it is 0, Dane does **not** treat any EDE as loading. Interim
  signal is HTTP `/gd/tlsa` `{"status":"loading"}`, which the node should
  emit when dnsd returns SERVFAIL plus the loading EDE. Plain SERVFAIL
  without that EDE stays on the existing fail-closed path.
- Timeout pref: `greatdane.node.lazyTimeoutSec` (default 10).

## Suggested node HTTP mapping

`/gd/tlsa?host=` should return `status: "loading"` (and optionally
`rcode: "SERVFAIL"` plus `ede: <TODO-KEEPER-EDE>`) while the zone is
being fetched. Never `unowned` / `no_tlsa` for a name that is in the
namespace but whose zone is not here yet. `/gd/names` should keep
working from the namespace alone.

Run: `python3 test_lazy_node.py` (binds 127.0.0.1 only).
