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
Dane's own servers receive nothing. Every entry is a stock Firefox service that Dane keeps, with Mozilla receiving
the data. Each one has Tracking=false. If a feature only collects after the user turns it on, it's still declared.

| Type | Linked | Purpose | Why it is declared |
|---|---|---|---|
| EmailAddress | yes | AppFunctionality | Optional Mozilla account sign-in for Sync (stock feature kept). Mozilla stores the account email. |
| DeviceID | no | AppFunctionality, Analytics | Web Push keeps a random per-install UAID at push.services.mozilla.com (on by default, see greatdane/PRIVACY.md). Glean's random client_id is sent only if the user opts in to data collection. |
| CoarseLocation | no | AppFunctionality | Stock region (country) lookup: `browser.region.network.url` = location.services.mozilla.com/v1/country (all.js), used for region defaults. |
| ProductInteraction | no | Analytics | Only if the user turns data collection ON. Dane ships it OFF (`datareporting.healthreport.uploadEnabled=false`, `toolkit.telemetry.enabled=false`, `toolkit.telemetry.server="data:,"`), but Glean's endpoint is compiled in as incoming.telemetry.mozilla.org (toolkit/components/glean/src/init/mod.rs). Patch 0028 keeps the opt-in visible. |
| PerformanceData | no | Analytics | Same opt-in as above (Glean/legacy telemetry performance metrics). |
| OtherDiagnosticData | no | Analytics | Same opt-in as above. |

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
| UserDefaults | CA92.1 | "information that is only accessible to the app itself": `[NSUserDefaults standardUserDefaults]` in widget/cocoa (dock, window, look-and-feel). There's no App Group. |

Not declared: ActiveKeyboards (that category covers iOS `UITextInputMode`; Gecko on macOS uses TIS input-source APIs,
which aren't in the required-reason list).
