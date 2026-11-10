# GreatDANE (Dane) tree notes

## Bundle ID migration: org.mozilla.surf.pepecoin.greatdane -> surf.dogecoin.dane

Decision: per the coordinator's record of its Oct 27 2026 conversation with nowon (not verbatim). Plan:
/workspace/patches/dane-esr153head/BUNDLE-ID-MIGRATION-PLAN.md

- **0051** (871ceac538): bundle ID is now surf.dogecoin.dane. Uses `--with-distribution-id=surf` in mozconfig and
  mozconfig-x86_64, and `MOZ_MACBUNDLE_ID=dogecoin.dane` in browser/branding/greatdane/configure.sh.
  toolkit/moz.configure puts the helpers under the new ID: surf.dogecoin.dane.{plugincontainer,gpu-helper,media-plugin-helper}.
  The GreatDANE app name, the profile folder, the greatdane.* prefs and the MAR channel greatdane-esr don't change.
- **0054** (64f1606a70): renames the **updater** and the **dmgInstallHelper** from org.mozilla.* to surf.dogecoin.dane.*.
  That covers the executables, Info.plist/Launchd.plist, the SMPrivilegedExecutables list, the elevation check in
  updatecommon.cpp, and the /Library/PrivilegedHelperTools and /Library/LaunchDaemons paths.
  It also changes the team ID (OU) in the code-signing requirement from 43AQ936H96 (Mozilla's) to MNL79V994R (Dane's).
- **0055**: moves the ChannelPrefs and UpdateSettings framework IDs from org.mozilla.* to
  surf.dogecoin.dane.channelprefs and surf.dogecoin.dane.updatesettings.

### What changes for users moving from an old-ID build (e.g. 6c4bedb9)

- **Kept:** the profile folder ~/Library/Application Support/GreatDANE (named after the app, not the bundle ID).
  That keeps bookmarks, prefs, history, chain node data and **logins saved in the profile** (logins.json, encrypted
  with key4.db). This was tested across the ID change on Oct 28 (RESULTS.md).
- **Reset:** anything stored with OSKeyStore ("GreatDANE Encrypted Storage" keychain item). Saved cards and addresses
  (encrypted autofill data) may need to be entered again, and OS re-auth is set up again.
  Also reset: camera, mic, location and file permissions (TCC); the default-browser choice; the
  ~/Library/Preferences defaults domain and saved window state; LaunchServices URL-handler registrations for the
  old ID; and any LaunchAgents labelled with the old ID.
- **No auto-update:** the old build can't update across the ID change. Users install the new dmg from
  https://dogecoin.surf/dane/download/ and drag it over the old app. If Finder doesn't offer Replace (the old app may be
  named GreatDANE.app), delete GreatDANE.app from Applications first, then drag Dane in. The profile isn't affected.
  The greatdane.doge start page has this note. Later updates are expected to install in-app once Dane's own update
  signing (MAR key and update server) is in place; until then, updates are manual downloads.
- **Optional cleanup**, only needed if the old app was ever run from its dmg and its privileged installer was allowed
  (upstream dmgInstallHelper.md, old name):

      sudo launchctl unload /Library/LaunchDaemons/org.mozilla.dmgInstallHelper.plist
      sudo rm /Library/LaunchDaemons/org.mozilla.dmgInstallHelper.plist
      sudo rm /Library/PrivilegedHelperTools/org.mozilla.dmgInstallHelper

## Crash reporter (local-only) and known Rosetta issue

- The crash reporter is enabled again (`--disable-crashreporter` was removed from both mozconfigs), but it is **local-only**. application.ini has an empty `[Crash Reporter] ServerURL`, so there is no Mozilla or other submit endpoint. Auto-submit (`browser.crashReports.unsubmittedCheck.autoSubmit2`), the unsubmitted-report prompt and tab-crash "send report" are all off by default (branding prefs). Minidumps stay in the profile's "Crash Reports" folder.
- Known issue: the x86_64 (Intel) slice running under Rosetta 2 on Apple silicon can intermittently abort with `assertion failed [arm_interval().contains(address)]: code fragment does not contain the given arm address`. This is a Rosetta 2 fault, also reproduced on stock Firefox ESR (153.6.0esr), and the rate varies a lot between sessions (about 0–28%). It is not a GreatDANE regression.
- Native-Intel gate: x86_64 release sign-off has to come from runs on a native Intel Mac. Rosetta runs on Apple silicon don't count as passing or failing that gate.

## macOS signing: per-binary entitlements (Apple fixes, 2026-11-10)

- Map: `greatdane/macos/sign-map.tsv`. Tool: `greatdane/tools/sign_dane_macos.py plan|sign|check <Dane.app>`.
  It signs inside-out with `--force --timestamp --options runtime` and never uses `--deep` to sign. It refuses any
  regular Mach-O or nested bundle that no map row covers. The only exception is the CFBundleExecutable main
  executable of the app or of the mapped bundle that directly encloses it. It also refuses restricted
  entitlements without an embedded provisioning profile.
  Path guard: case-insensitive on the realpath. It refuses /Volumes/Dane (and `Dane N` / `Dane-N`), any
  `*DaneNotarized*` component and the GreatDANE profile path, plus anything else under /Volumes unless
  `--allow-volume` or `DANE_SIGN_ALLOW_VOLUMES` allowlists it. The identity is redacted in logs.
- Team ID: one source of truth, `greatdane/macos/signing.conf` (`TEAM_ID`). sign-map.tsv, the signer and the
  entitlement headers reference it. `build/moz.configure/update-programs.configure` keeps a build-time copy, and
  `greatdane/tests/sign_dane_macos_selftest.py` (T3) fails if the two differ.
- Release signing: `greatdane/tools/finish-universal.sh` calls the in-tree `greatdane/tools/sign-only.sh`
  (stage, then plan, sign, check, then dmg). It replaces the old out-of-tree `$G/sign-only.sh`, which used
  blanket `--entitlements ... --deep`. That script never notarizes. `check` is read-only and compares `codesign -d --entitlements -`
  for each row against the map, then runs `codesign --verify --deep --strict`.
- Entitlements by binary (Mozilla production config: taskcluster/config.yml mac-signing):
  - **Dane.app:** `production/dane.browser.xml`, which is firefox.browser.xml minus application-identifier and
    public-key-credential (they wait for Apple's grant). It keeps disable-library-validation, because ESR loads
    third-party PKCS#11 modules in the parent process. `dane.browser.no-dlv.xml` is the stricter alternative
    (`DANE_BROWSER_ENTITLEMENTS=dane.browser.no-dlv.xml`).
  - **plugin-container.app:** `plugin-container.xml` (allow-jit only).
  - **media-plugin-helper.app:** `media-plugin-helper.xml` (disable-library-validation only). It loads the
    Google-signed Widevine CDM and the OpenH264 GMP.
  - **No entitlements, hardened runtime only:** gpu-helper.app, updater.app (+ UpdateSettings.framework), the
    LaunchServices surf.dogecoin.dane.updater and surf.dogecoin.dane.dmgInstallHelper, crashreporter.app,
    crashhelper, pingsender, nmhproxy, XUL, *.dylib, gmp-clearkey, ChannelPrefs.framework and greatdane-node*.
- **Known regression: system passkeys.** Passkeys stored in the macOS system (Touch ID / iCloud Keychain, through
  `com.apple.developer.web-browser.public-key-credential`) are unavailable until Apple grants Dane's team that
  entitlement and a matching provisioning profile is embedded in Dane.app. Security keys (USB/NFC FIDO2) and
  passkeys from third-party password managers that inject through the web page aren't affected.
- `mach macos-sign` reads taskcluster/config.yml. It now uses the Dane LaunchServices names, includes
  greatdane-node*, and uses dane.browser.xml for the app.
