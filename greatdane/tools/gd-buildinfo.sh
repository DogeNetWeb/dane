#!/bin/bash
# Write BUILDINFO.txt beside a Dane dmg. Read-only inputs; no secrets.
# Usage: gd-buildinfo.sh DMG [NODE_REPO] [OBJDIR]
set -euo pipefail
DMG=$1; TREE=$(cd "$(dirname "$0")/../.." && pwd)
NODE=${2:-$TREE/../pepenet-desktop}; OBJ=${3:-$TREE/obj-gd}
cfg() { grep -o "'$1': '[^']*'" "$OBJ/config.status" 2>/dev/null | head -1 | sed "s/.*: '//; s/'\$//"; }
AMAL=$(sed -n 's/^SQLITE_AMALGAMATION:PATH=//p' "$NODE/build-pin-arm64/CMakeCache.txt" 2>/dev/null)
SQL=$(sed -n 's/^#define SQLITE_VERSION *"\(.*\)"/\1/p' "$AMAL/sqlite3.h" 2>/dev/null)
BID=$(sed -n 's/^BuildID=//p' "$OBJ/dist/bin/application.ini" 2>/dev/null)
SHA=$(shasum -a 256 "$DMG" | cut -d' ' -f1); REL=$(dirname "$DMG")
# BuildIDs are unique per build: refuse if this BuildID is already recorded for a different dmg.
for f in $(grep -rls "^build_id: *$BID\$" "$REL" 2>/dev/null); do
  o=$(sed -n 's/^dmg_sha256: *//p' "$f"); [ -z "$o" ] || [ "$o" = "$SHA" ] || {
    echo "gd-buildinfo: BuildID $BID already used by $f (sha $o) != $SHA; refusing" >&2; exit 1; }; done
{
echo "product:        Dane $(cat "$TREE/browser/config/version_display.txt")"
echo "dmg:            $(basename "$DMG")"
echo "dmg_sha256:     $SHA"
echo "build_id:       $BID"
echo "tree:           $(git -C "$TREE" rev-parse HEAD) ($(git -C "$TREE" rev-parse --abbrev-ref HEAD))$(git -C "$TREE" diff --quiet HEAD || echo ' +dirty')"
echo "node:           $(git -C "$NODE" rev-parse HEAD) ($(git -C "$NODE" rev-parse --abbrev-ref HEAD))"
echo "sqlite:         ${SQL:-unknown}"
echo "update_channel: $(cfg MOZ_UPDATE_CHANNEL)"
echo "mar_channel:    $(cfg MAR_CHANNEL_ID)"
echo "accepted_mar:   $(cfg ACCEPTED_MAR_CHANNEL_IDS)"
echo "generated:      $(date '+%F %T %Z')"
} > "$REL/BUILDINFO.txt"
cp "$REL/BUILDINFO.txt" "$REL/BUILDINFO-$BID.txt"
# keep a BuildID-named copy of the dmg beside the generic one
[ -e "$REL/$(basename "$DMG" .dmg)-$BID.dmg" ] || cp "$DMG" "$REL/$(basename "$DMG" .dmg)-$BID.dmg"
cat "$REL/BUILDINFO.txt"
