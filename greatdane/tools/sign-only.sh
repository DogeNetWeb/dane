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
#   DANE_ARCH           universal | arm64 | x86_64 (default universal); used in the dmg name
#   DANE_POLICIES       distribution policies.json to embed (default: $G/dane-policies.json).
#                       Set DANE_NO_POLICIES=1 to build without one on purpose.
#   DANE_SIGN_IDENTITY  optional; default = the one "Developer ID Application: ... (<TEAM_ID>)" identity in the
#                       keychain. It's never printed.
#   DANE_DRY_RUN=1      stage + plan + print the codesign commands only; no signing, no dmg.
set -euo pipefail
TREE=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$TREE/.." && pwd)
CONF=$TREE/greatdane/macos/signing.conf
TEAM=$(sed -n 's/^TEAM_ID=\([A-Z0-9]\{10\}\)$/\1/p' "$CONF")
[ -n "$TEAM" ] || { echo "REFUSE: no TEAM_ID in $CONF" >&2; exit 2; }
SIGNER=$TREE/greatdane/tools/sign_dane_macos.py
ARCH=${DANE_ARCH:-universal}
SRC=${DANE_APP_SRC:?set DANE_APP_SRC}
NODE=${DANE_NODE:?set DANE_NODE}
VER=$(cat "$TREE/browser/config/version_display.txt")
OUT=$TREE/obj-gd/dist/gd-release
STAGE=$OUT/stage-$ARCH
APP=$STAGE/Dane.app
DMG=$OUT/Dane-$VER-mac-$ARCH.dmg

owner_path() {  # same owner rules as sign_dane_macos.py (case-insensitive)
  local low; low=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$low" in
    /volumes/dane|/volumes/dane/*|/volumes/dane[\ -][0-9]*|*danenotarized*|*"/application support/greatdane"*) return 0 ;;
  esac
  return 1
}
for p in "$SRC" "$STAGE" "$DMG"; do
  if owner_path "$p"; then echo "REFUSE: off-limits path: $p" >&2; exit 2; fi
done
[ -f "$SRC/Contents/Info.plist" ] || { echo "REFUSE: not an app: $SRC" >&2; exit 2; }
[ -x "$NODE" ] || { echo "REFUSE: DANE_NODE not executable: $NODE" >&2; exit 2; }
POL=${DANE_POLICIES:-$G/dane-policies.json}
if [ "${DANE_NO_POLICIES:-0}" != 1 ] && [ ! -f "$POL" ]; then
  echo "REFUSE: policies.json not found: $POL (set DANE_POLICIES or DANE_NO_POLICIES=1)" >&2; exit 2; fi

if [ -z "${DANE_SIGN_IDENTITY:-}" ] && [ "${DANE_DRY_RUN:-0}" != 1 ]; then
  command -v security >/dev/null || { echo "REFUSE: no 'security' tool (macOS only); set DANE_SIGN_IDENTITY" >&2; exit 2; }
  ids=$(security find-identity -v -p codesigning | sed -n "s/.*\"\(Developer ID Application: .* ($TEAM)\)\"$/\1/p" | sort -u)
  [ "$(printf '%s\n' "$ids" | grep -c .)" = 1 ] || { echo "REFUSE: need exactly one Developer ID Application identity for team $TEAM (set DANE_SIGN_IDENTITY)" >&2; exit 2; }
  DANE_SIGN_IDENTITY=$ids
fi
export DANE_SIGN_IDENTITY="${DANE_SIGN_IDENTITY:-}"
# The stage normally lives on /Volumes/Storage; allow exactly the stage dir for the signer's /Volumes guard.
export DANE_SIGN_ALLOW_VOLUMES="$STAGE"

echo "== stage ($ARCH) -> $STAGE"
rm -rf "$STAGE"; mkdir -p "$STAGE"
ditto --norsrc --noextattr "$SRC" "$APP"
cp "$NODE" "$APP/Contents/MacOS/greatdane-node"; chmod 755 "$APP/Contents/MacOS/greatdane-node"
if [ "${DANE_NO_POLICIES:-0}" = 1 ]; then echo "   (no policies.json, DANE_NO_POLICIES=1)"
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
python3 "$SIGNER" check "$APP" --json "$OUT/entitlements-check-$ARCH.json"

echo "== dmg -> $DMG"
rm -f "$DMG"
hdiutil create -volname Dane -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
codesign --force --timestamp --sign "$DANE_SIGN_IDENTITY" "$DMG" 2>&1 | sed "s/$(printf '%s' "$DANE_SIGN_IDENTITY" | sed 's/[][\.*^$/]/\\&/g')/<identity redacted>/g"
codesign --verify --verbose=2 "$DMG"
shasum -a 256 "$DMG"
echo "== done (NOT notarized)"
