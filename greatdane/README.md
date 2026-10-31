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
