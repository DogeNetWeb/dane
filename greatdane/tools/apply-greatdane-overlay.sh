#!/bin/sh
# In-repo GreatDANE overlay apply hook for a Firefox source tree.
# Run this after the Dane patch series has been applied (git am) and
# before clobber / mach configure / mach build.
#
# This is the hook that runs apply-greatdane-static-prefs.sh (N1).
# The repo's own entry point, greatdane/tools/apply-dane-series.sh,
# calls it after the series and commits the result. Pipelines that apply
# the series themselves should call
#   greatdane/tools/apply-dane-series.sh --hook-only <firefox-src>
# at the same point; see greatdane/tools/OVERLAY-HOOK.md for where the
# pinned Linux pipeline gets the call at its next re-pin.
#
#   apply-greatdane-overlay.sh <firefox-src>
#   apply-greatdane-overlay.sh --check <firefox-src>
set -eu
HERE=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
AS="$HERE/greatdane/tools/apply-greatdane-static-prefs.sh"
[ -x "$AS" ] || { echo "apply-greatdane-overlay: missing $AS" >&2; exit 1; }
# N1 hook: apply (or verify) the StaticPrefs yaml + moz.build patches.
exec "$AS" "$@"
