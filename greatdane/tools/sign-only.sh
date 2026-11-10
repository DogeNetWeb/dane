#!/bin/bash
# Dane: stage + per-binary sign + dmg. NEVER notarizes, staples or publishes.
# In-tree replacement (2026-11-10, NGD round 2 H1) for the out-of-tree $G/sign-only.sh, whose blanket
# `--entitlements browser.entitlements.plist --deep` loop gave every helper the browser's entitlements.
# Signing is done only by greatdane/tools/sign_dane_macos.py (map: greatdane/macos/sign-map.tsv, team:
# greatdane/macos/signing.conf), followed by its read-only `check`.
#
# Env (same names finish-universal.sh already passes):
#   DANE_APP_SRC        unified/arch Dane.app to stage (required; never /Volumes/Dane or DaneNotarized)
#   DANE_NODE           greatdane-node binary to embed (required)
#   DANE_ARCH           exactly universal | arm64 | x86_64 (default universal); anything else is refused
#                       before any rm. Used in the stage dir and dmg name.
#   DANE_OUT            output dir (default $TREE/obj-gd/dist/gd-release). An existing dmg is never
#                       overwritten: move it away or choose another DANE_OUT.
#   DANE_POLICIES       distribution policies.json to embed (default: $G/dane-policies.json).
#                       Set DANE_NO_POLICIES=1 to build without one on purpose.
#   DANE_SIGN_IDENTITY  optional; default = the one "Developer ID Application: ... (<TEAM_ID>)" identity in the
#                       keychain. It's never printed. Developer ID runs use `check --strict`.
#                       "-" = AD-HOC throwaway check run: no keychain, no timestamp; hardened runtime and
#                       per-binary entitlements are kept; check reports ad-hoc as expected-not-Developer-ID;
#                       the dmg is named ...-ADHOC.dmg and its volume "Dane-ADHOC". Never distribute or notarize
#                       an ad-hoc build (notarize.next-round4 refuses *-ADHOC.dmg and non-Developer-ID signatures).
#   DANE_DRY_RUN=1      stage + plan + print the codesign commands only; no signing, no dmg.
set -euo pipefail
TREE=$(cd "$(dirname "$0")/../.." && pwd -P)
G=$(cd "$TREE/.." && pwd -P)
CONF=$TREE/greatdane/macos/signing.conf
TEAM=$(sed -n 's/^TEAM_ID=\([A-Z0-9]\{10\}\)$/\1/p' "$CONF")
[ -n "$TEAM" ] || { echo "REFUSE: no TEAM_ID in $CONF" >&2; exit 2; }
SIGNER=$TREE/greatdane/tools/sign_dane_macos.py
refuse() { echo "REFUSE: $*" >&2; exit 2; }
[ $# -eq 0 ] || refuse "sign-only.sh takes no arguments (the legacy --deep modes are retired); configure it with DANE_* env"
# R2-M3: ARCH goes into rm -rf "$STAGE" and the dmg name, so allowlist it before anything else.
ARCH=${DANE_ARCH:-universal}
case "$ARCH" in universal|arm64|x86_64) ;; *) refuse "DANE_ARCH must be exactly universal, arm64 or x86_64 (got '$ARCH')" ;; esac
VER=$(cat "$TREE/browser/config/version_display.txt")
[[ "$VER" =~ ^[0-9][0-9A-Za-z.]*$ ]] || refuse "unexpected version string in browser/config/version_display.txt: '$VER'"
realp() { python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
# L-b: /System/Volumes/Data/<x> is the firmlinked /<x>; strip it before the /Applications, /Users, /Volumes rules.
fl() { case "$(lower "$1")" in /system/volumes/data|/system/volumes/data/) echo / ;; /system/volumes/data/*) echo "${1:20}" ;; *) echo "$1" ;; esac; }
SRC=$(fl "$(realp "${DANE_APP_SRC:?set DANE_APP_SRC}")")
NODE=$(fl "$(realp "${DANE_NODE:?set DANE_NODE}")")
OUT=$(fl "$(realp "${DANE_OUT:-$TREE/obj-gd/dist/gd-release}")")
ADHOC=0; [ "${DANE_SIGN_IDENTITY:-}" = "-" ] && ADHOC=1
SUFFIX=""; [ $ADHOC = 1 ] && SUFFIX="-ADHOC"
STAGE=$OUT/stage-$ARCH$SUFFIX
APP=$STAGE/Dane.app
DMG=$OUT/Dane-$VER-mac-$ARCH$SUFFIX.dmg
VOL=Dane$SUFFIX   # L-e: an ad-hoc dmg mounts as "Dane-ADHOC", never as "Dane"
POL=""
if [ "${DANE_NO_POLICIES:-0}" != 1 ]; then
  POL=$(fl "$(realp "${DANE_POLICIES:-$G/dane-policies.json}")")
  [ -f "$POL" ] || refuse "policies.json not found: $POL (set DANE_POLICIES or DANE_NO_POLICIES=1)"
fi

# Owner rules on the realpaths, using the signer's single implementation (owner volumes, DaneNotarized, the
# GreatDANE profile, /Applications, ~/Applications, attached owner dmgs on any mount point).
python3 "$SIGNER" guard-path "$SRC" "$NODE" "$OUT" "$STAGE" "$DMG" ${POL:+"$POL"} || refuse "off-limits source/target path (see above)"
[[ "$(lower "$OUT")" =~ ^/((volumes|users)(/[^/]+)?)?$ ]] && refuse "DANE_OUT too broad: $OUT"
case "$(lower "$SRC")/" in "$(lower "$STAGE")"/*) refuse "DANE_APP_SRC is inside the stage dir that gets deleted: $SRC" ;; esac
[ ! -L "$STAGE" ] || refuse "stage dir is a symlink: $STAGE"
# L-d: only a stage dir this script made (it carries the marker) is ever deleted.
MARK=.dane-sign-only-stage
mark() { printf 'made by greatdane/tools/sign-only.sh (stage-%s); safe to delete\n' "$ARCH$SUFFIX" > "$STAGE/$MARK"; }
if [ -e "$STAGE" ]; then
  [ -d "$STAGE" ] && [ -f "$STAGE/$MARK" ] && [ ! -L "$STAGE/$MARK" ] \
    || refuse "existing $STAGE has no $MARK marker, so sign-only.sh did not make it; not deleting it (move it away)"
fi
[ -f "$SRC/Contents/Info.plist" ] || refuse "not an app: $SRC"
[ -x "$NODE" ] || refuse "DANE_NODE not executable: $NODE"
[ ! -e "$DMG" ] || refuse "dmg already exists, not overwriting: $DMG (move it away or set DANE_OUT)"

if [ $ADHOC = 1 ]; then
  echo "== AD-HOC throwaway check run: identity '-', no keychain, no timestamp; NOT distributable"
elif [ -z "${DANE_SIGN_IDENTITY:-}" ] && [ "${DANE_DRY_RUN:-0}" != 1 ]; then
  command -v security >/dev/null || { echo "REFUSE: no 'security' tool (macOS only); set DANE_SIGN_IDENTITY" >&2; exit 2; }
  ids=$(security find-identity -v -p codesigning | sed -n "s/.*\"\(Developer ID Application: .* ($TEAM)\)\"$/\1/p" | sort -u)
  [ "$(printf '%s\n' "$ids" | grep -c .)" = 1 ] || { echo "REFUSE: need exactly one Developer ID Application identity for team $TEAM (set DANE_SIGN_IDENTITY)" >&2; exit 2; }
  DANE_SIGN_IDENTITY=$ids
fi
export DANE_SIGN_IDENTITY="${DANE_SIGN_IDENTITY:-}"
# The stage normally lives on /Volumes/Storage: allow exactly the stage dir for the signer's /Volumes guard
# (entries must be under /Volumes), and mark it as a work dir for the owner-bundle-ID rule (DANE_OUT outside the tree).
case "$(lower "$STAGE")" in /volumes/*) export DANE_SIGN_ALLOW_VOLUMES="$STAGE" ;; *) unset DANE_SIGN_ALLOW_VOLUMES ;; esac
export DANE_SIGN_WORK_DIRS="$STAGE"
STRICT=--strict; [ $ADHOC = 1 ] && STRICT=""

echo "== stage ($ARCH) -> $STAGE"
[ ! -e "$STAGE" ] || [ -f "$STAGE/$MARK" ] || refuse "stage marker vanished: $STAGE"
rm -rf "$STAGE"; mkdir -p "$STAGE"; mark
ditto --norsrc --noextattr "$SRC" "$APP"
cp "$NODE" "$APP/Contents/MacOS/greatdane-node"; chmod 755 "$APP/Contents/MacOS/greatdane-node"
if [ -z "$POL" ]; then echo "   (no policies.json, DANE_NO_POLICIES=1)"
else
  mkdir -p "$APP/Contents/Resources/distribution"; cp "$POL" "$APP/Contents/Resources/distribution/policies.json"
fi
[ -f "$APP/Contents/Resources/PrivacyInfo.xcprivacy" ] || cp "$TREE/greatdane/macos/PrivacyInfo.xcprivacy" "$APP/Contents/Resources/"
xattr -cr "$APP"
ln -sfn /Applications "$STAGE/Applications"

echo "== plan"
python3 "$SIGNER" plan "$APP"
if [ "${DANE_DRY_RUN:-0}" = 1 ]; then
  python3 "$SIGNER" sign "$APP" --dry-run
  echo "DRY RUN: nothing signed, no dmg"; exit 0
fi
echo "== sign per binary (no --deep; identity redacted)"
python3 "$SIGNER" sign "$APP"
python3 "$SIGNER" check "$APP" $STRICT --json "$OUT/entitlements-check-$ARCH$SUFFIX.json"

echo "== dmg -> $DMG"
[ ! -e "$DMG" ] || refuse "dmg appeared during the run, not overwriting: $DMG"
rm -f "$STAGE/$MARK"   # keep the marker out of the dmg; put back right after
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -format UDZO "$DMG" >/dev/null || { mark; refuse "hdiutil create failed"; }
mark
if [ $ADHOC = 1 ]; then
  codesign --force --sign - "$DMG"
else
  codesign --force --timestamp --sign "$DANE_SIGN_IDENTITY" "$DMG" 2>&1 | sed "s/$(printf '%s' "$DANE_SIGN_IDENTITY" | sed 's/[][\.*^$/]/\\&/g')/<identity redacted>/g"
fi
codesign --verify --verbose=2 "$DMG"
shasum -a 256 "$DMG"
if [ $ADHOC = 1 ]; then echo "== done (AD-HOC: throwaway check build; NOT Developer ID, NOT notarized, do not distribute)"
else echo "== done (NOT notarized)"; fi
