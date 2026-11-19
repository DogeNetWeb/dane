#!/bin/sh
# Apply the GreatDANE StaticPrefs patches (greatdane.node.lazy and
# lazyTimeoutSec, plus the "greatdane" pref_groups entry) to a Firefox
# source tree. Fails loudly if a patch does not apply or the result
# does not contain the prefs / group.
#
#   apply-greatdane-static-prefs.sh <firefox-src>
#   apply-greatdane-static-prefs.sh --check <firefox-src>   # no writes
#
# This overlay does not vendor StaticPrefList.yaml or moz.build.
set -eu
CHECK=
if [ "${1:-}" = "--check" ]; then
  CHECK=1
  shift
fi
if [ -z "${1:-}" ] || [ ! -d "$1" ]; then
  echo "apply-greatdane-static-prefs: usage: $0 [--check] <firefox-src>" >&2
  exit 2
fi
TREE=$(cd "$1" && pwd)
HERE=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
YP="$HERE/modules/libpref/init/StaticPrefList.yaml.patch"
MP="$HERE/modules/libpref/moz.build.patch"
YAML="$TREE/modules/libpref/init/StaticPrefList.yaml"
MOZ="$TREE/modules/libpref/moz.build"
die() { echo "apply-greatdane-static-prefs: $*" >&2; exit 1; }
[ -f "$YP" ] || die "missing $YP"
[ -f "$MP" ] || die "missing $MP"
[ -f "$YAML" ] || die "missing $YAML"
[ -f "$MOZ" ] || die "missing $MOZ"

if [ -n "$CHECK" ]; then
  git -C "$TREE" apply --check "$YP" || die "StaticPrefList.yaml.patch does not apply"
  git -C "$TREE" apply --check "$MP" || die "moz.build.patch does not apply"
  echo "apply-greatdane-static-prefs: --check OK"
  exit 0
fi

git -C "$TREE" apply "$YP" || die "failed to apply StaticPrefList.yaml.patch"
git -C "$TREE" apply "$MP" || die "failed to apply moz.build.patch"

# Loud post-apply checks (no include mechanism; the generator reads only
# StaticPrefList.yaml, and headers exist only for pref_groups).
grep -q 'name: greatdane.node.lazy$' "$YAML" || die "greatdane.node.lazy missing from StaticPrefList.yaml after apply"
grep -q 'name: greatdane.node.lazyTimeoutSec$' "$YAML" || die "greatdane.node.lazyTimeoutSec missing after apply"
awk '/name: greatdane.node.lazy$/{n=1} n&&/type:/{print; exit}' "$YAML" | grep -q RelaxedAtomicBool \
  || die "greatdane.node.lazy must be RelaxedAtomicBool"
awk '/name: greatdane.node.lazyTimeoutSec$/{n=1} n&&/type:/{print; exit}' "$YAML" | grep -q RelaxedAtomicInt32 \
  || die "greatdane.node.lazyTimeoutSec must be RelaxedAtomicInt32"
grep -q '"greatdane"' "$MOZ" || die "pref_groups is missing \"greatdane\" in moz.build after apply"
echo "apply-greatdane-static-prefs: applied and verified in $TREE"
