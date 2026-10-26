#!/bin/bash
# Sequential: faster JS rebuild+package (both, same BuildID) -> pinned-sqlite node (arm64, x86_64, lipo) -> unify -> sign. No notarize.
set -euo pipefail
G=/Volumes/Storage/build/greatdane; TREE=$G/firefox-esr153; ND=$G/pepenet-desktop
export PATH="$HOME/.cargo/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin" MOZ_BUILD_DATE=20261026160337
st() { echo "$(date '+%F %T') $*" >> $G/universal.status; }
cd $TREE
for m in mozconfig mozconfig-x86_64; do st "faster+package $m"
  MOZCONFIG=$TREE/$m ./mach --no-interactive build > $G/fin-$m.log 2>&1
  MOZCONFIG=$TREE/$m ./mach --no-interactive package >> $G/fin-$m.log 2>&1; done
st "node pinned sqlite"
for a in arm64 x86_64; do cmake --build $ND/build-pin-$a --target greatdane-node -j6 > $G/pin-build-$a.log 2>&1; done
mkdir -p $ND/build-pin-universal
lipo -create $ND/build-pin-arm64/greatdane-node $ND/build-pin-x86_64/greatdane-node -output $ND/build-pin-universal/greatdane-node
lipo -archs $ND/build-pin-universal/greatdane-node | tee -a $G/universal.status
st "unify"
U=$G/universal-work; rm -rf $U; mkdir -p $U/arm64 $U/x86_64
VER=$(cat browser/config/version_display.txt); V=${VER%esr}
./mach python -m mozbuild.action.unpack_dmg obj-gd/dist/greatdane-$V.en-US.mac.dmg $U/arm64 > $G/universal-unify.log 2>&1
./mach python -m mozbuild.action.unpack_dmg obj-gd-x86_64/dist/greatdane-$V.en-US.mac.dmg $U/x86_64 >> $G/universal-unify.log 2>&1
./mach python toolkit/mozapps/installer/unify.py $U/x86_64/Dane.app $U/arm64/Dane.app >> $G/universal-unify.log 2>&1
lipo -archs $U/x86_64/Dane.app/Contents/MacOS/greatdane | tee -a $G/universal.status
st "sign (no notarize)"
DANE_ARCH=universal DANE_APP_SRC=$U/x86_64/Dane.app DANE_NODE=$ND/build-pin-universal/greatdane-node $G/sign-only.sh > $G/universal-sign.log 2>&1
st "buildinfo"
$TREE/greatdane/tools/gd-buildinfo.sh $TREE/obj-gd/dist/gd-release/Dane-$VER-mac-universal.dmg $ND >> $G/universal.status 2>&1
st "done"
