# Dane

Dane is a Firefox ESR 153 based browser for DogeNet and PepeNet. It resolves the `.doge` and `.pepe`
chain names through a local naming node and checks their TLS keys against owner-published TLSA records
(DANE-EE). Chain hosts fail closed instead of falling back to the normal CA system.

This repository holds Dane's own changes. It does not contain a Firefox source tree.

## Contents

- `patches/`: Dane's commits as an ordered patch series (`git format-patch` output, with binary hunks),
  listed in order in `patches/series`. There is one patch per Dane commit. Upstream Mozilla commits are not
  included.
- `greatdane/`: Dane's own top-level source directory (tools, macOS signing and packaging scripts, tests,
  privacy notes, artwork sources). The path is kept exactly as it is in the build tree so the patches
  apply unchanged. The same files are also created by the patch series.

## History

This history was extracted from Dane's private build tree (branch `dane-linux-build`, a full Firefox ESR
checkout). Each commit here corresponds to one Dane commit in that tree, in order and with its original
message and author date. Each commit adds that commit's patch file to `patches/` and updates `greatdane/`
to its state at that commit. The `Extracted-from:` trailer names the build-tree commit and the patch number.
Upstream ESR commits and merges are left out.

## Base

- Firefox ESR 153 (`esr153` branch of https://github.com/mozilla-firefox/firefox).
- Dane's work started on `esr153` at `ef80361e4d2417048eb2b49c592185a9c559548d`. The build tree then took
  29 later upstream ESR commits, up to `3bd39ccf6af8b2c836e2f96d928bc9282adaf28e`. Dane's commits sit on
  top of those.
- **Apply the series on `3bd39ccf6af8b2c836e2f96d928bc9282adaf28e`.** All 144 patches then apply cleanly,
  and the resulting tree is identical to the build tree. On `ef80361e4d` itself, patch 0133 fails, because
  it pins `browser/locales/l10n-changesets.json` on top of the upstream l10n bumps.

## Applying

```sh
git clone --branch esr153 --single-branch https://github.com/mozilla-firefox/firefox.git
cd firefox
git checkout -b dane 3bd39ccf6af8b2c836e2f96d928bc9282adaf28e
/path/to/dane/greatdane/tools/apply-dane-series.sh .   # git am the series, then the overlay hook
# or by hand: git am --keep-cr /path/to/dane/patches/*.patch, then
#   /path/to/dane/greatdane/tools/apply-dane-series.sh --hook-only .
# apply without committing (this is how the series was verified):
#   for p in $(cat /path/to/dane/patches/series); do git apply --check /path/to/dane/patches/$p && git apply /path/to/dane/patches/$p; done
```

`apply-dane-series.sh` runs the GreatDANE overlay hook after the series and before any clobber or
configure. The hook fails closed, and the script commits anything it changes, so the HEAD tree is the tree
you build. See `greatdane/tools/OVERLAY-HOOK.md`.

Build Dane the same way as Firefox (`./mach build`), using the mozconfig files that the series adds.
macOS signing needs your own Developer ID identity. No keys or certificates are included.

## License

Firefox is licensed under the MPL 2.0 (see `LICENSE` in the Firefox tree). This repository does not add a separate license file.
