# Dane wordmark and logo inventory (round 4e)

Source-level audit of where a Dane build would show a Firefox wordmark or logo.
Official branding paths were not changed. No Firefox feature was disabled.
This is not a trademark clearance.

Navy/white palette taken from existing Dane branding:
- `#13254A` / `#0A1631` — `about-logo.svg` gradient
- `#0B1B35` — `aboutDialog.css` background
- `#FFFFFF` — logo artwork

## Handled in this round

### chrome://branding/content/firefox-wordmark.svg (new tab + private browsing + About)

Stock CSS already loads this branding chrome URL; the files were not edited:

- `browser/extensions/newtab/content-src/components/Logo/_Logo.scss` (compiled into `css/activity-stream.css` and `css/nova/activity-stream.css`)
- `browser/themes/shared/privatebrowsing/aboutPrivateBrowsing.css`

The About dialog uses `chrome://branding/content/about-wordmark.svg` (`browser/base/content/aboutDialog.css`).

Both chrome URLs now serve one file, `greatdane/content/about-wordmark.svg`: a plain text "Dane" SVG on a transparent ground, `fill="context-fill #13254A"`. Stock CSS sets the color with `-moz-context-properties: fill` (`--newtab-wordmark-color` on new tab, `currentColor` on private browsing). The navy is the fallback when context-fill is not set. The `firefox-wordmark.svg` filename is kept only because it is the stock URL; `content/jar.mn` aliases it to `about-wordmark.svg`. The duplicate copy of the SVG was removed.

The Dane-tree copies of these SVGs already said "Dane" before this round (identical files, sha256 `286207e5…`); they were not the official Firefox path-logo. This round makes that a single source of truth and adds the palette fallback.

### chrome://browser/skin/window-firefox.svg (Preferences homepage icon)

`AboutPreferences.sys.mjs` uses this as the homepage section icon. It is a 16x14 window with a Firefox-head mark, registered under `chrome://browser/skin` (the same registry as the existing sidebar override). `content/jar.mn` now overrides it to `chrome://branding/content/greatdane-icon.svg` (already an alias of `about-logo.svg`). The stock `browser/themes/shared/icons/window-firefox.svg` file is unchanged, so official branding is unaffected.

## Already handled before this round (left as-is)

- `chrome://browser/skin/sidebar/firefox.svg` — already overridden to `greatdane-icon.svg`.
- `chrome://browser/skin/preferences/mozilla-logo.svg` — already overridden to `chrome://browser/skin/fxa/avatar-empty.svg`.
- `chrome://branding/content/about-logo.svg` / `.png` / `@2x.png` / `about-logo-private.png` — Dane artwork, used by About, about:welcome, asrouter, aboutPDF (`icon32.png`), and many chrome://branding/content/about-logo.svg call sites.
- `greatdane-icon.svg` — alias of `about-logo.svg`.

## Documented, not swapped (stock components; swapping risks breakage or would leak into official branding)

These live in shared (non-branding) trees. Replacing the files would change an official-branding build from the same source. A `browser.jar` `% override` is proven for `chrome://browser/skin/…` (sidebar, now window-firefox); it is not assumed to apply to built-in-addon `chrome://newtab/…` URLs or to `chrome://global/content/ml/…`.

- **Discovery Stream navigation logo.** `_Navigation.scss` / compiled activity-stream CSS uses `chrome://newtab/content/data/content/assets/firefox.svg` (the full-color Firefox logo, 20x20) for `.ds-navigation-family .firefox-logo`. This is a builtin-addon asset (`newtab@mozilla.org`). It appears only if that Discovery Stream navigation family row is shown. Not overridden in this round.
- **New-tab marketing illustrations.** `firefox-mascot-prop-paintbucket-rgb.svg`, `firefox-motion-head-pop-up-no-bg.svg`, and `highlights/firefox-wallpaper-desktop-hills-light-rgb.svg` are referenced from PromoCard, WallpaperFeatureHighlight, SportsWidget, and compiled CSS. They are large pictorial assets; swapping them for a wordmark would break layout. Not overridden.
- **Toolkit ML logo.** `chrome://global/content/ml/mozilla-logo.webp` is used by toolkit ML UI (`toolkit/components/ml`). Not a browser wordmark; left as Mozilla's mark.
- **Firefox View toolbar icon.** `chrome://browser/skin/firefox-view.svg` is a generic window/tabs icon, not a Firefox wordmark or logo. Left alone; Firefox View is not disabled.
- **aboutPDF "firefox-logo" element.** The HTML id is leftover naming. The image is `chrome://branding/content/icon32.png`, already the Dane app icon.
- **In-tree docs.** `docs/conf.py` sets `html_logo` to the *nightly* `firefox-wordmark.svg`. That is not a shipped Dane app path; official/nightly branding was not touched.
- **Linux installer symbolic icon.** `browser/installer/linux/app/flatpak/files/share/icons/hicolor/symbolic/apps/org.mozilla.firefox-symbolic.svg` is a packaging icon for Linux/Flatpak, not loaded by the Mac app chrome. Not changed here.
- **Fluent ids** such as `home-prefs-firefox-logo-header` are string identifiers, not graphics.

## Shipped filenames (round 4f)

- **`firefox-wordmark.svg` chrome URL — documented, not renamed.** Stock new-tab and private-browsing CSS load `chrome://branding/content/firefox-wordmark.svg`. Renaming the chrome URL would require editing those shared CSS files, which would leak into official branding or break it. The file is already an alias of `about-wordmark.svg` (plain-text "Dane") via `content/jar.mn` from round 4e. The source filename in the greatdane branding tree was already removed; only the chrome URL remains.
- **`firefox.VisualElementsManifest.xml` — renamed for greatdane only.** Windows looks for `<exe>.VisualElementsManifest.xml` next to the exe. Dane's exe is `greatdane.exe` (`MOZ_APP_NAME` is the lowercase of `--with-app-basename=GreatDANE`), so the shipped name is now `greatdane.VisualElementsManifest.xml`. `branding-common.mozbuild` selects that filename only when `MOZ_BRANDING_DIRECTORY` is `browser/branding/greatdane`. Official, nightly, aurora, and unofficial branding still package `firefox.VisualElementsManifest.xml`. Official-branding files are not edited. `package-manifest.in` now lists `@BINPATH@/@MOZ_APP_NAME@.VisualElementsManifest.xml`. `private_browsing.VisualElementsManifest.xml` is unchanged (it sits next to `private_browsing.exe`).

A source-level check is `greatdane/tests/wordmark_branding_check.py`. Round 4f also adds `greatdane/tests/trademark_userfacing_check.py`.
