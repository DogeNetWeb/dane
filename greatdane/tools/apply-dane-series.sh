#!/bin/sh
# Apply the Dane patch series to a Firefox ESR source tree and run the
# GreatDANE overlay hook, so the tree is ready for clobber / configure.
# This is the repo's build entry point for the series (see README.md,
# "Applying"). It never runs mach, clobber or configure itself.
#
#   apply-dane-series.sh [--patches <dir>] <firefox-src>
#       git am --keep-cr every patch in <dir>/series (default: this
#       repo's patches/), then run the hook step below.
#   apply-dane-series.sh --hook-only <firefox-src>
#       Only the hook step, for pipelines that apply the series
#       themselves. Call it after the last product commit and before
#       clobber / configure.
#
# Hook step (fail closed):
#   1. the tracked tree must be clean;
#   2. apply-greatdane-overlay.sh --check must pass (no writes);
#   3. apply-greatdane-overlay.sh applies (or verifies already-applied);
#   4. if the hook changed modules/libpref/init/StaticPrefList.yaml or
#      modules/libpref/moz.build, those two paths are committed, so the
#      HEAD tree is the tree that gets configured and built. Any other
#      change is refused.
# Commits use the tree's git identity (user.name / user.email).
set -eu
HERE=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
OVL="$HERE/greatdane/tools/apply-greatdane-overlay.sh"
PATCHES="$HERE/patches"
HOOK_ONLY=
die() { echo "apply-dane-series: $*" >&2; exit 1; }
usage() {
  echo "apply-dane-series: usage: $0 [--patches <dir>] <firefox-src> | --hook-only <firefox-src>" >&2
  exit 2
}
while [ $# -gt 0 ]; do
  case "$1" in
    --hook-only) HOOK_ONLY=1; shift ;;
    --patches) [ $# -ge 2 ] || usage; PATCHES=$2; shift 2 ;;
    --) shift; break ;;
    -*) usage ;;
    *) break ;;
  esac
done
[ $# -eq 1 ] && [ -d "$1" ] || usage
TREE=$(CDPATH= cd -- "$1" && pwd)
[ -x "$OVL" ] || die "missing $OVL"
git -C "$TREE" rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$TREE is not a git work tree"
[ "$(git -C "$TREE" rev-parse --show-toplevel)" = "$TREE" ] || die "$TREE is not the top of its git work tree"

YAML_REL=modules/libpref/init/StaticPrefList.yaml
MOZ_REL=modules/libpref/moz.build

tracked_clean() {
  [ -z "$(git -C "$TREE" status --porcelain --untracked-files=no)" ]
}

if [ -z "$HOOK_ONLY" ]; then
  SERIES="$PATCHES/series"
  [ -f "$SERIES" ] || die "missing $SERIES"
  tracked_clean || die "tracked changes in $TREE; refusing to apply the series"
  n=0
  while IFS= read -r p || [ -n "$p" ]; do
    case "$p" in ''|'#'*) continue ;; esac
    [ -f "$PATCHES/$p" ] || die "series names a missing patch: $p"
    if ! git -C "$TREE" am --keep-cr -q "$PATCHES/$p"; then
      git -C "$TREE" am --abort >/dev/null 2>&1 || true
      die "git am failed at $p (aborted; the overlay hook did not run)"
    fi
    n=$((n + 1))
  done < "$SERIES"
  echo "apply-dane-series: applied $n patches from $SERIES"
fi

# Hook step.
tracked_clean || die "tracked changes in $TREE before the overlay hook; refusing"
"$OVL" --check "$TREE" || die "overlay hook --check failed; tree left unchanged"
"$OVL" "$TREE" || die "overlay hook failed"
changed=$(git -C "$TREE" status --porcelain --untracked-files=no | awk '{print $2}')
for f in $changed; do
  case "$f" in
    "$YAML_REL"|"$MOZ_REL") ;;
    *) die "overlay hook changed an unexpected path: $f" ;;
  esac
done
if [ -n "$changed" ]; then
  git -C "$TREE" add -- "$YAML_REL" "$MOZ_REL"
  git -C "$TREE" commit -q -m "GreatDANE: StaticPrefs overlay hook (greatdane.node.lazy prefs, greatdane pref group)" \
    || die "could not commit the overlay hook result"
  echo "apply-dane-series: committed the overlay hook result ($(git -C "$TREE" rev-parse --short HEAD))"
else
  echo "apply-dane-series: overlay hook made no changes (series already carries them)"
fi
tracked_clean || die "tree is not clean after the overlay hook"
echo "apply-dane-series: ready for clobber / configure in $TREE"
