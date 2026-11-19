#!/bin/sh
# In-repo GreatDANE overlay apply hook for a Firefox source tree.
# Run this after the product commits have been git-am'd (or the overlay
# files copied) and before mach configure / mach build.
#
# This is the hook that runs apply-greatdane-static-prefs.sh (N1).
# The historical dane-linux pin sequences live outside this repo and
# were not modified. What is still needed: one invocation of this
# script against the Linux tree, after product git am and before
# ./mach configure, at:
#   /workspace/dane-linux/prepare-final-pin-sequence.sh:179
#     (right after 'Product commits applied...') and again after v3
#     before the clobber+configure block (~line 228);
#   /workspace/dane-linux/prepare-final-pin-sequence-r9.sh:746
#     (after 'git am of 5b-5e completed') and before
#     run_mach configure at line 955
# (and the same relative spots in the r3–r8 copies).
#
#   apply-greatdane-overlay.sh <firefox-src>
#   apply-greatdane-overlay.sh --check <firefox-src>
set -eu
HERE=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
AS="$HERE/greatdane/tools/apply-greatdane-static-prefs.sh"
[ -x "$AS" ] || { echo "apply-greatdane-overlay: missing $AS" >&2; exit 1; }
# N1 hook: apply (or verify) the StaticPrefs yaml + moz.build patches.
exec "$AS" "$@"
