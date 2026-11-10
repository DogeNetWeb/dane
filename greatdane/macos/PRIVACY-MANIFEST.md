# Dane privacy manifest (PrivacyInfo.xcprivacy): rationale

Shipped at `Dane.app/Contents/Resources/PrivacyInfo.xcprivacy`.
It's installed by `browser/app/Makefile.in` (repackage) and listed in `browser/installer/package-manifest.in`, so
`mach package` and every dmg built from the tree carry it. `greatdane/tools/finish-universal.sh` also copies it after
unify, and that stays harmless because the content is the same. A privacy manifest is optional for Developer ID
(non-App Store) distribution. It's kept accurate anyway, and Apple Polish asked for it.

Reason-code wording below is quoted from Apple's NSPrivacyAccessedAPITypeReasons reference (fetched 2026-11-10).

## Tracking
- `NSPrivacyTracking` = false. `NSPrivacyTrackingDomains` = empty. Dane has no ad or attribution SDKs, and the
  sponsored tiles, Pocket and ads feeds are off (browser/app/profile/firefox.js, GreatDANE block).

## Collected data types (conservative)
Every entry is a stock Firefox service that Dane keeps, with Mozilla receiving the data. Each one has Tracking=false.
If a feature only collects after the user turns it on, it's still declared.

**What Dane's own servers see.** This corrects the earlier "Dane's own servers receive nothing".
- The automatic update check `app.update.url` (browser/app/profile/firefox.js:3719) goes to pepecoin.surf. It carries
  product, version, build ID, build target, locale and channel, plus the client IP that every HTTPS request carries.
  It has no account or per-install identifier.
  - **Declaration and retention: PENDING the server-log answer** (owned by Curb Appeal, 2026-11-10). If the server
    keeps access logs for these requests, the plan is to declare them under the existing OtherDiagnosticData entry
    (not linked, not tracking, AppFunctionality; add Analytics only if the logs are used to count installs), and
    to state the retention in days here. If the logs are off or anonymized, it stays undeclared, and the log setting
    goes here. Until then, this document makes no claim about how the server uses or keeps these requests.
  - The check can be turned off: the `DisableAppUpdate` enterprise policy (policies.json) makes
    `UpdateServiceStub.updateDisabled` true (toolkit/mozapps/update/UpdateServiceStub.sys.mjs:209-215), and then no
    update check is made.
- **Default new-tab tiles:** the icons for pepecoin.surf, dogecoin.surf, greatdane.doge and grokipedia.com are bundled
  through tippytop (browser/components/topsites/content/tippytop, see greatdane/tippytop-ICON-SOURCES.md; grokipedia.com
  uses our own generated letter tile, not the site's mark). Showing
  the new-tab page doesn't fetch from those sites, so there's no favicon or screenshot request.
- **User-initiated loads** of pepecoin.surf, dogecoin.surf or greatdane.doge (clicking a tile, typing the address, the
  manual-download and release-notes links) are ordinary browsing. That site's operator sees a normal web request,
  the same as for any other site.

| Type | Linked | Purpose | Why it is declared |
|---|---|---|---|
| EmailAddress | yes | AppFunctionality | Optional Mozilla account sign-in for Sync (stock feature kept). Mozilla stores the account email. |
| DeviceID | no | AppFunctionality, Analytics | Web Push keeps a random per-install UAID at push.services.mozilla.com (on by default, see greatdane/PRIVACY.md). Glean's random client_id is sent only if the user opts in to data collection. |
| CoarseLocation | no | AppFunctionality | Stock region (country) lookup: `browser.region.network.url` = location.services.mozilla.com/v1/country (all.js), used for region defaults. |
| ProductInteraction | no | Analytics | Only if the user turns data collection ON. Dane ships it OFF (`datareporting.healthreport.uploadEnabled=false`, `toolkit.telemetry.enabled=false`, `toolkit.telemetry.server="data:,"`), but Glean's endpoint is compiled in as incoming.telemetry.mozilla.org (toolkit/components/glean/src/init/mod.rs). Patch 0028 keeps the opt-in visible. |
| PerformanceData | no | Analytics | Same opt-in as above (Glean/legacy telemetry performance metrics). |
| OtherDiagnosticData | no | AppFunctionality, Analytics | **Not opt-in only** (corrects round 2). The default-on GMP plugin update check (`media.gmp-provider.enabled=true`, firefox.js:2448; OpenH264/Widevine enabled, :2400/:2378) fetches `media.gmp-manager.url` = aus5.mozilla.org/update/3/GMP/%VERSION%/%BUILD_ID%/%BUILD_TARGET%/%LOCALE%/%CHANNEL%/%OS_VERSION%/... (modules/libpref/init/all.js:3474). That sends app version, build ID, build target (OS + CPU arch), locale, channel and OS version to Mozilla (AppFunctionality: to serve the right plugin). The opt-in telemetry diagnostics (Analytics) come on top. Dane's own update-check logging may also land here: pending, see above. |

Deliberately not declared:
- **CrashData:** the crash reporter is local-only. application.ini has an empty `[Crash Reporter] ServerURL`, and
  auto-submit and the tab-crash "send report" are off (greatdane/README.md).
- **BrowsingHistory / SearchHistory:** Safe Browsing sends hash prefixes only. Sync data is end-to-end encrypted and
  Mozilla can't read it. Search queries and suggestions go to the user-chosen engine as the service the user asked for.
- **PreciseLocation:** macOS CoreLocation (`geo.provider.use_corelocation=true`), behind a per-site permission, and
  delivered only to the requesting site.

Mozilla's own Firefox for iOS manifest (mozilla-mobile/firefox-ios `firefox-ios/PrivacyInfo.xcprivacy`, fetched
2026-11-10, sha256 a2b03d6b9adc82f566aeb200ac80eac7f34cbba59044c6fb12a6b45fb1de097b) declares no collected data types.
Dane deliberately declares more than that.

## Required-reason APIs
| Category | Reasons | Gecko use |
|---|---|---|
| FileTimestamp | C617.1, 3B52.1, DDA9.1 | **C617.1** ("files inside the app container…"): profile, cache, omni.ja, update staging mtimes (xpcom/io/nsLocalFileUnix.cpp). **3B52.1** ("files … the user specifically granted access to"): files picked in the file picker / drag-drop, exposed as `File.lastModified`. **DDA9.1** ("display file timestamps to the person"): downloads list and file:// directory listings. |
| SystemBootTime | 35F9.1, 8FFB.1 | **35F9.1**: `mach_absolute_time` for TimeStamp and timers (mozglue/misc/TimeStamp_darwin.cpp). **8FFB.1**: converting NSEvent timestamps (seconds since boot) to Gecko event times (widget/cocoa/nsCocoaUtils.mm). |
| DiskSpace | E174.1 | "check whether there is sufficient disk space to write files": cache smart-sizing, downloads, updater staging, and the run-from-dmg install (toolkit/xre/MacRunFromDmgUtils.mm, nsLocalFileUnix.cpp). |
| UserDefaults | CA92.1 | "information that is only accessible to the app itself": `[NSUserDefaults standardUserDefaults]` in widget/cocoa (window, look-and-feel). There's no App Group. **Stated openly:** Gecko also touches two other apps' preference domains. (1) **com.apple.dock**: it reads the Dock's persistent domain (`persistentDomainForName:kDockDomainName`, widget/cocoa/nsMacDockSupport.mm:367 and :407) and writes it back (`setPersistentDomain:forName:kDockDomainName`, nsMacDockSupport.mm:347). The read runs at startup for the `os_environment.is_kept_in_dock` metric (browser/components/StartupTelemetry.sys.mjs:512, uploaded only under the telemetry opt-in) and again when the pin flow checks. The write happens only through `ShellService.pinToTaskbar` (browser/components/shell/ShellService.sys.mjs:762), when the user accepts pin-to-Dock, for example in onboarding. (2) **com.apple.loginwindow**: it reads `TALLogoutSavesState` (`CFPreferencesCopyAppValue`, widget/cocoa/nsCocoaUtils.mm:310-312), only at a login-launch, to honor the user's "Reopen windows when logging back in" choice. Neither access is literally "only accessible to the app itself". No required-reason code covers other apps' domains, and CA92.1 is the closest declared reason. Mozilla's stock macOS build does the same thing. If Apple review objects, the fallback is to drop the Dock write path (a feature change, owner's call). |

Not declared: ActiveKeyboards (that category covers iOS `UITextInputMode`; Gecko on macOS uses TIS input-source APIs,
which aren't in the required-reason list).
