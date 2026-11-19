# GreatDANE overlay hook: where it runs

The StaticPrefs overlay (`greatdane.node.lazy`, `greatdane.node.lazyTimeoutSec` and the `greatdane`
`pref_groups` entry) has two parts:

- `patches/0163-*` commits the libpref edits themselves (`modules/libpref/init/StaticPrefList.yaml`
  and `modules/libpref/moz.build`), so a tree built from the series already carries them.
- `greatdane/tools/apply-greatdane-overlay.sh` (which runs `apply-greatdane-static-prefs.sh`) verifies
  them, and applies them to a tree that does not carry 0163. It is idempotent: on a tree with 0163 it
  reports "already applied" and still runs the exact-count and type checks, in `--check` mode too.

## In this repo

`greatdane/tools/apply-dane-series.sh <firefox-src>` is the build entry point. It `git am`s the series,
then runs the hook: `--check` first (fail closed, no writes), then apply, then commits any change to the
two libpref paths so the HEAD tree is the tree that gets configured. It refuses a dirty tree and any hook
change outside those two paths. Pipelines that apply the series themselves call
`apply-dane-series.sh --hook-only <firefox-src>` after their last product commit and before
clobber / configure.

No allowlist in this repo restricts which paths a patch may touch, so 0163 needs no allowlist entry here.

## Pinned Linux pipeline (next re-pin)

The pinned Linux pin-sequence scripts live outside this repo and were not edited. Per the reviewer's
round-3 call-site notes, they get one hook call each at the next re-pin (and a new review of that pin):

- `prepare-final-pin-sequence.sh`: after the v3 commit (after the "v3 applied" echo, about line 213)
  and before the clobber + configure block (about lines 225-228). Follow it with
  `git add modules/libpref/init/StaticPrefList.yaml modules/libpref/moz.build` and a commit
  (`--hook-only` does both). Not after line 179: that is before the v3 acceptance gate, which can exit
  and leave a modified tree, and the v3 commit only adds six named files.
- `prepare-final-pin-sequence-r9.sh`: after the changed-path / mode+blob check (ends about line 905)
  and before the inode / clobber / `run_mach configure` steps (configure at about line 955). Not after
  line 746: the 5b-5e invariants, the L5 am/apply and the v3.6 am/apply still run after it. Add the two
  libpref paths to that script's changed-path allowlist ("apple 15 paths + v3.6 files"), or the check
  refuses them. Commit there too.
- The same relative spots in the earlier r3-r8 copies, if any of them is re-pinned.

The lazy-node commits are not in the pinned 5b-5e / L5 / v3.6 series yet, so the hook and 0163 only
exist in that pipeline once those commits are added. If the libpref edits stay uncommitted, the pin's
tree hash will not match what is actually built.
