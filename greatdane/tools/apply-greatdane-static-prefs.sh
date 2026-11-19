#!/bin/sh
# Apply the GreatDANE StaticPrefs patches (greatdane.node.lazy and
# lazyTimeoutSec, plus the "greatdane" pref_groups entry) to a Firefox
# source tree. Idempotent and all-or-nothing:
#   - git apply --check on both patches before any write;
#   - already-applied (git apply --reverse --check) is a no-op success;
#   - a partial pre-state (only one patch applied) fails before writing;
#   - if the second apply fails, the first is reversed so the tree is
#     not left half-patched.
# Fails loudly if a patch does not apply or the result is missing the
# prefs / group.
#
#   apply-greatdane-static-prefs.sh <firefox-src>
#   apply-greatdane-static-prefs.sh --check <firefox-src>   # no writes
#
# This overlay does not vendor StaticPrefList.yaml or moz.build.
# Prefer the overlay hook greatdane/tools/apply-greatdane-overlay.sh,
# which calls this script.
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

# 1 if git apply $1 $2 succeeds (stdout/stderr discarded).
can_apply() {
  git -C "$TREE" apply "$@" >/dev/null 2>&1
}

already_yp=0
already_mp=0
can_yp=0
can_mp=0
if can_apply --reverse --check "$YP"; then already_yp=1; fi
if can_apply --reverse --check "$MP"; then already_mp=1; fi
if can_apply --check "$YP"; then can_yp=1; fi
if can_apply --check "$MP"; then can_mp=1; fi

# Partial pre-state: never write (a second yaml apply would duplicate
# the insertion; a lone moz.build apply would leave the pair split).
if [ "$already_yp" -ne "$already_mp" ]; then
  die "partial pre-state (yaml already-applied=$already_yp moz.build already-applied=$already_mp); refusing to write"
fi

# Both already applied: idempotent no-op. Still verify the greps.
if [ "$already_yp" -eq 1 ] && [ "$already_mp" -eq 1 ]; then
  :
else
  # Neither is applied. Both must --check cleanly before any write.
  if [ "$can_yp" -ne 1 ] || [ "$can_mp" -ne 1 ]; then
    die "patches do not apply (yaml --check=$can_yp moz.build --check=$can_mp); refusing to write"
  fi
  if [ -n "$CHECK" ]; then
    echo "apply-greatdane-static-prefs: --check OK"
    exit 0
  fi
  # Apply yaml first; if moz.build then fails, roll yaml back.
  git -C "$TREE" apply "$YP" || die "failed to apply StaticPrefList.yaml.patch"
  if ! git -C "$TREE" apply "$MP"; then
    if git -C "$TREE" apply --reverse "$YP"; then
      die "failed to apply moz.build.patch; yaml rolled back"
    fi
    die "failed to apply moz.build.patch; yaml apply could not be rolled back"
  fi
fi

# Loud post-apply (or already-applied) checks. The generator reads only
# StaticPrefList.yaml, and headers exist only for pref_groups.
# Count entries so a duplicate insertion is a hard failure. These run in
# --check mode too, so --check on an already-applied tree that carries a
# duplicate (or a wrong type) fails instead of reporting OK.
count_pref() {
  grep -c "$1" "$YAML" || true
}
n_lazy=$(count_pref '^[[:space:]]*- name: greatdane\.node\.lazy$')
n_to=$(count_pref '^[[:space:]]*- name: greatdane\.node\.lazyTimeoutSec$')
[ "$n_lazy" -eq 1 ] || die "expected exactly one greatdane.node.lazy in StaticPrefList.yaml, found $n_lazy"
[ "$n_to" -eq 1 ] || die "expected exactly one greatdane.node.lazyTimeoutSec, found $n_to"
awk '/name: greatdane\.node\.lazy$/{n=1} n&&/type:/{print; exit}' "$YAML" | grep -q RelaxedAtomicBool \
  || die "greatdane.node.lazy must be RelaxedAtomicBool"
awk '/name: greatdane\.node\.lazyTimeoutSec$/{n=1} n&&/type:/{print; exit}' "$YAML" | grep -q RelaxedAtomicInt32 \
  || die "greatdane.node.lazyTimeoutSec must be RelaxedAtomicInt32"
grep -q '"greatdane"' "$MOZ" || die "pref_groups is missing \"greatdane\" in moz.build"
if [ -n "$CHECK" ]; then
  # Already-applied path in --check mode: no writes happened.
  echo "apply-greatdane-static-prefs: --check OK (already applied)"
  exit 0
fi
if [ "$already_yp" -eq 1 ]; then
  echo "apply-greatdane-static-prefs: already applied, skipped in $TREE"
else
  echo "apply-greatdane-static-prefs: applied and verified in $TREE"
fi
