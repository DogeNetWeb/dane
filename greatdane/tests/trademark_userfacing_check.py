#!/usr/bin/env python3
"""Source-level check for leftover user-facing Firefox/Mozilla uses (round 4f).

Covers Frank Exchange Of Views' 11 Change items and NGD 4d M1 / L1, against
the files in this tree. No build, no signing, no network.

Run from the source tree root:
  python3 greatdane/tests/trademark_userfacing_check.py

Exit 0 on pass, 1 on any failure. Files absent from a snapshot are SKIP, not PASS.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

ABOUT_XHTML = os.path.join(ROOT, "browser/base/content/aboutDialog.xhtml")
ABOUT_FTL = os.path.join(ROOT, "browser/locales/en-US/browser/aboutDialog.ftl")
BRAND_FTL = os.path.join(ROOT, "browser/branding/greatdane/locales/en-US/brand.ftl")
MODULE_VERS = (
    "browser/app/module.ver",
    "browser/app/pbproxy/module.ver",
)
EXE_MANIFEST = os.path.join(ROOT, "browser/app/firefox.exe.manifest")
LAUNCHER_MANIFEST = os.path.join(
    ROOT, "browser/app/desktop-launcher/desktop-launcher.exe.manifest"
)
BRANDING_NSI = os.path.join(ROOT, "browser/branding/greatdane/branding.nsi")
PREFS_FTL = os.path.join(ROOT, "browser/locales/en-US/browser/preferences/preferences.ftl")
BRANDING_JS = os.path.join(ROOT, "browser/branding/greatdane/pref/firefox-branding.js")
SYNC_INC = os.path.join(ROOT, "browser/components/preferences/sync.inc.xhtml")
BOOKMARKS_HTML = os.path.join(ROOT, "browser/base/content/default-bookmarks.html")
BOOKMARKS_FTL = os.path.join(ROOT, "browser/locales/en-US/browser/profile/default-bookmarks.ftl")
PACKAGE_MANIFEST = os.path.join(ROOT, "browser/installer/package-manifest.in")
BRANDING_COMMON = os.path.join(ROOT, "browser/branding/branding-common.mozbuild")
GREATDANE_VE = os.path.join(
    ROOT, "browser/branding/greatdane/greatdane.VisualElementsManifest.xml"
)
OLD_VE = os.path.join(
    ROOT, "browser/branding/greatdane/firefox.VisualElementsManifest.xml"
)
JAR = os.path.join(ROOT, "browser/branding/greatdane/content/jar.mn")
INVENTORY = os.path.join(ROOT, "greatdane/WORDMARK-SOURCES.md")

APPROVED_ATTR = (
    "{ -brand-short-name } is built from Mozilla's open source Firefox ESR web browser. "
    "{ -brand-short-name } is not officially associated with Mozilla or its products."
)
UPSTREAM_COMMUNITY_EXP = (
    '<label data-l10n-name="community-exp-mozillaLink">{ -vendor-short-name }</label> '
    'is a <label data-l10n-name="community-exp-creditsLink">global community</label> '
    "working together to keep the Web open, public and accessible to all."
)
UPSTREAM_COMMUNITY_2 = (
    "{ -brand-short-name } is designed by "
    '<label data-l10n-name="community-mozillaLink">{ -vendor-short-name }</label>, a '
    '<label data-l10n-name="community-creditsLink">global community</label> '
    "working together to keep the Web open, public and accessible to all."
)

PRIVACY_URL = "https://dane.surf/privacy/"
SUPPORT_URL = "https://dane.surf/support/"
DOWNLOAD_URL = "https://dane.surf/download/"
HOME_URL = "https://dane.surf/"
MOZILLA_HOME = "https://www.mozilla.org/"


def fail(msg, bad):
    print("FAIL " + msg)
    bad.append(msg)


def pass_(msg):
    print("PASS " + msg)


def skip(msg):
    print("SKIP " + msg)


def read(path, encoding="utf-8"):
    with open(path, encoding=encoding) as f:
        return f.read()


def ftl_value(text, key):
    m = re.search(r"^" + re.escape(key) + r" = (.+)$", text, re.MULTILINE)
    return m.group(1) if m else None


def unofficial_block(text, inner_pattern=None):
    """Return #ifndef MOZ_OFFICIAL_BRANDING ... #else / #endif chunks."""
    chunks = []
    for m in re.finditer(
        r"#ifndef MOZ_OFFICIAL_BRANDING\n(.*?)(?:#else\n(.*?))?#endif",
        text,
        re.DOTALL,
    ):
        chunks.append((m.group(1), m.group(2) or ""))
    return chunks


def check_about(bad):
    if not os.path.isfile(ABOUT_XHTML):
        skip("aboutDialog.xhtml is not in this tree")
        return
    xhtml = read(ABOUT_XHTML)

    # Unofficial Terms / Privacy (Frank 1-2, NGD M1)
    unofficial_has_terms = False
    unofficial_has_privacy = False
    official_keeps_terms = False
    official_keeps_privacy = False
    for unoff, off in unofficial_block(xhtml):
        if 'data-l10n-id="bottom-links-terms"' in unoff and SUPPORT_URL in unoff:
            unofficial_has_terms = True
        if 'data-l10n-id="bottom-links-privacy"' in unoff and PRIVACY_URL in unoff:
            unofficial_has_privacy = True
        if "terms/firefox/" in off and 'data-l10n-id="bottom-links-terms"' in off:
            official_keeps_terms = True
        if "privacy/firefox/" in off and 'data-l10n-id="bottom-links-privacy"' in off:
            official_keeps_privacy = True
    if not unofficial_has_terms:
        fail("unofficial About Terms link is not %s" % SUPPORT_URL, bad)
    else:
        pass_("unofficial About Terms link is %s (dane.surf/terms/ 404; support used)" % SUPPORT_URL)
    if not unofficial_has_privacy:
        fail("unofficial About Privacy link is not %s" % PRIVACY_URL, bad)
    else:
        pass_("unofficial About Privacy link is %s" % PRIVACY_URL)
    if not official_keeps_terms or not official_keeps_privacy:
        fail("official About Terms/Privacy URLs were not preserved", bad)
    else:
        pass_("official About Terms/Privacy URLs are unchanged")

    # Donate dropped unofficial only (Frank 3, NGD M1)
    unofficial_donate = False
    official_donate = False
    unofficial_involved = False
    for unoff, off in unofficial_block(xhtml):
        if "helpus-donateLink" in unoff or "foundation.mozilla.org" in unoff:
            unofficial_donate = True
        if 'data-l10n-id="dane-helpus"' in unoff and SUPPORT_URL in unoff:
            unofficial_involved = True
        if "helpus-donateLink" in off and "foundation.mozilla.org" in off:
            official_donate = True
    if unofficial_donate:
        fail("unofficial About still has a donate link", bad)
    else:
        pass_("unofficial About drops the donate link")
    if not unofficial_involved:
        fail("unofficial About get-involved is not %s under dane-helpus" % SUPPORT_URL, bad)
    else:
        pass_("unofficial About get-involved is %s" % SUPPORT_URL)
    if not official_donate:
        fail("official About donate link was removed", bad)
    else:
        pass_("official About donate link is unchanged")

    # Community UTM stripped unofficial only (Frank 4); destination mozilla.org stays
    unofficial_clean = False
    official_utm = False
    unofficial_utm = False
    for unoff, off in unofficial_block(xhtml):
        if 'data-l10n-name="community-mozillaLink"' in unoff or 'data-l10n-name="community-exp-mozillaLink"' in unoff:
            if "utm_source=firefox-browser" in unoff:
                unofficial_utm = True
            if MOZILLA_HOME in unoff:
                unofficial_clean = True
        if "utm_source=firefox-browser" in off and "community-" in off:
            official_utm = True
    if unofficial_utm:
        fail("unofficial About mozilla.org community links still have firefox-browser UTMs", bad)
    elif not unofficial_clean:
        fail("unofficial About mozilla.org community links are missing or not %s" % MOZILLA_HOME, bad)
    else:
        pass_("unofficial About mozilla.org community links keep the destination and drop firefox-browser UTMs")
    if not official_utm:
        fail("official About community UTMs were stripped", bad)
    else:
        pass_("official About community UTMs are unchanged")

    if "about:license" not in xhtml or "about:credits" not in xhtml:
        fail("about:license or about:credits is missing", bad)
    else:
        pass_("about:license and about:credits are unchanged")


def check_ftl_wording(bad):
    if not os.path.isfile(BRAND_FTL) or not os.path.isfile(ABOUT_FTL):
        skip("brand.ftl or aboutDialog.ftl is not in this tree")
        return
    brand = read(BRAND_FTL)
    about = read(ABOUT_FTL)
    for key in ("dane-community-2", "dane-community-exp"):
        val = ftl_value(brand, key)
        if not val or APPROVED_ATTR not in val:
            fail("brand.ftl %s no longer has the approved About paragraph" % key, bad)
        else:
            pass_("brand.ftl %s still has the approved About paragraph" % key)
    expected = {"community-exp": UPSTREAM_COMMUNITY_EXP, "community-2": UPSTREAM_COMMUNITY_2}
    for key, exp in expected.items():
        val = ftl_value(about, key)
        if val != exp:
            fail("aboutDialog.ftl %s is not the upstream stock string (NGD L1): %r" % (key, val), bad)
        elif APPROVED_ATTR in (val or ""):
            fail("aboutDialog.ftl %s still carries the Dane disassociation" % key, bad)
        else:
            pass_("aboutDialog.ftl %s is the upstream stock string (NGD L1)" % key)
    helpus = ftl_value(about, "helpus")
    if not helpus or "helpus-donateLink" not in helpus:
        fail("aboutDialog.ftl helpus should remain stock for official builds", bad)
    else:
        pass_("aboutDialog.ftl helpus stays stock for official branding")
    dane_helpus = ftl_value(brand, "dane-helpus")
    if not dane_helpus or "donation" in dane_helpus.lower() or "helpus-donateLink" in dane_helpus:
        fail("brand.ftl dane-helpus is missing or still mentions a donation", bad)
    else:
        pass_("brand.ftl dane-helpus has no donate wording")


def check_module_ver(bad):
    found = 0
    for rel in MODULE_VERS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            skip("%s is not in this tree" % rel)
            continue
        found += 1
        raw = open(path, "rb").read()
        text = raw.decode("latin-1")
        if "WIN32_MODULE_COMPANYNAME=Pepecoin" not in text:
            fail("%s company is not Pepecoin" % rel, bad)
        elif "Mozilla Corporation" in text:
            fail("%s still names Mozilla Corporation" % rel, bad)
        elif "Firefox is a Trademark of The Mozilla Foundation" in text:
            fail("%s still uses the Firefox-product trademark line" % rel, bad)
        elif "Firefox and Mozilla are trademarks of Mozilla.org" not in text:
            fail("%s is missing the Mozilla.org trademark credit" % rel, bad)
        elif "WIN32_MODULE_COPYRIGHT=" not in text or "Pepecoin" not in text.split("WIN32_MODULE_COPYRIGHT=", 1)[1].splitlines()[0]:
            fail("%s copyright is not Pepecoin" % rel, bad)
        elif b"\xa9" not in raw:
            fail("%s copyright is missing the Latin-1 copyright sign" % rel, bad)
        else:
            pass_("%s company/copyright are Pepecoin with a Mozilla.org trademark credit" % rel)
    if found == 0:
        skip("module.ver files are not in this snapshot")


def check_manifests(bad):
    if not os.path.isfile(EXE_MANIFEST):
        skip("firefox.exe.manifest is not in this tree")
    else:
        text = read(EXE_MANIFEST)
        if 'name="Dane"' not in text or "<description>Dane</description>" not in text:
            fail("firefox.exe.manifest assembly name/description are not Dane", bad)
        elif 'name="Firefox"' in text or "<description>Firefox</description>" in text:
            fail("firefox.exe.manifest still says Firefox", bad)
        else:
            pass_("firefox.exe.manifest assembly name and description are Dane (filename kept)")
    if not os.path.isfile(LAUNCHER_MANIFEST):
        skip("desktop-launcher.exe.manifest is not in this tree")
    else:
        text = read(LAUNCHER_MANIFEST)
        if 'name="Dane.DesktopLauncher"' not in text or "Desktop launcher for Dane" not in text:
            fail("desktop-launcher.exe.manifest is not branded as Dane", bad)
        elif "Mozilla.Firefox" in text or "Mozilla Firefox" in text:
            fail("desktop-launcher.exe.manifest still says Mozilla Firefox", bad)
        else:
            pass_("desktop-launcher.exe.manifest is Dane.DesktopLauncher")


def check_branding_nsi(bad):
    if not os.path.isfile(BRANDING_NSI):
        skip("greatdane/branding.nsi is not in this tree")
        return
    text = read(BRANDING_NSI)
    expected = {
        "URLInfoAbout": HOME_URL.rstrip("/") + "/'\"",  # we'll do looser checks
    }
    checks = [
        ('URLInfoAbout', 'https://dane.surf/'),
        ('HelpLink', SUPPORT_URL),
        ('URLStubDownloadX86', DOWNLOAD_URL),
        ('URLStubDownloadAMD64', DOWNLOAD_URL),
        ('URLStubDownloadAArch64', DOWNLOAD_URL),
        ('URLManualDownload', DOWNLOAD_URL),
        ('URLSystemRequirements', SUPPORT_URL),
        ('CertNameDownload', 'Pepecoin'),
        ('CertIssuerDownload', 'Pepecoin'),
    ]
    missing = []
    for key, val in checks:
        if not re.search(r'!define\s+' + re.escape(key) + r'\s+"' + re.escape(val.rstrip("/")) + r'/?\"', text) and \
           ('"%s"' % val) not in text and ("\"%s\"" % val.rstrip("/")) not in text:
            # simpler: key line contains the value
            line = [ln for ln in text.splitlines() if ln.startswith("!define %s" % key) or ln.startswith("!define  %s" % key)]
            # branding uses spaces like !define URLInfoAbout          "..."
            line = [ln for ln in text.splitlines() if re.match(r"!define\s+" + re.escape(key) + r"\s+", ln)]
            if not line or val.rstrip("/") not in line[0]:
                missing.append((key, val, line))
    if missing:
        fail("branding.nsi missing expected defines: %s" % missing, bad)
    defines = "\n".join(ln for ln in text.splitlines() if ln.startswith("!define"))
    if "download.mozilla.org" in defines or "product=firefox-latest" in defines:
        fail("branding.nsi still points stub URLs at official Firefox", bad)
    elif "Mozilla Corporation" in defines:
        fail("branding.nsi still uses Mozilla Corporation as CertNameDownload", bad)
    elif "support.mozilla.org" in defines or "mozilla.org/firefox/system-requirements" in defines:
        fail("branding.nsi still points help/requirements at Mozilla Firefox pages", bad)
    else:
        pass_("branding.nsi HelpLink/stub/manual/requirements use dane.surf; cert name is Pepecoin")


def check_sync_promo(bad):
    if not os.path.isfile(PREFS_FTL):
        skip("preferences.ftl is not in this tree")
    else:
        text = read(PREFS_FTL)
        val = ftl_value(text, "sync-mobile-promo")
        if not val:
            fail("preferences.ftl is missing sync-mobile-promo", bad)
        elif re.search(r"Download Firefox", val) or "Android" in (val or "") or "iOS" in (val or ""):
            fail("sync-mobile-promo still promotes Firefox or a mobile app: %r" % val, bad)
        elif "android-link" not in (val or "") or "download page" not in (val or ""):
            fail("sync-mobile-promo does not point at a download page: %r" % val, bad)
        else:
            pass_("sync-mobile-promo no longer says Download Firefox and points at the download page")
    if not os.path.isfile(BRANDING_JS):
        skip("firefox-branding.js is not in this tree")
    else:
        text = read(BRANDING_JS)
        if 'pref("identity.mobilepromo.android", "https://dane.surf/download/?ref=")' not in text or \
           'pref("identity.mobilepromo.ios", "https://dane.surf/download/?ref=")' not in text:
            fail("identity.mobilepromo.* are not set to %s?ref=" % DOWNLOAD_URL, bad)
        else:
            pass_("identity.mobilepromo.* point at %s?ref= (sync.js appends sync-preferences)" % DOWNLOAD_URL)
    if not os.path.isfile(SYNC_INC):
        skip("sync.inc.xhtml is not in this tree")
    else:
        text = read(SYNC_INC)
        if "logo-android.svg" in text or "logo-ios.svg" in text:
            fail("sync-mobile-promo markup still includes Android/iOS store icons", bad)
        elif "fxaMobilePromo-android" not in text:
            fail("sync-mobile-promo lost the android-link target sync.js fills", bad)
        elif 'id="connect-another-device"' not in text:
            fail("connect-another-device was removed; Sync UI must stay", bad)
        else:
            pass_("sync promo markup is a single download link; connect-another-device remains")


def check_bookmarks(bad):
    if not os.path.isfile(BOOKMARKS_HTML):
        skip("default-bookmarks.html is not in this tree")
    else:
        text = read(BOOKMARKS_HTML)
        if "support.mozilla.org" in text or "customize-firefox" in text:
            fail("default-bookmarks.html still links to Firefox help/customize pages", bad)
        elif "blog.nightly.mozilla.org" in text or "bugzilla.mozilla.org" in text or "addons.mozilla.org/firefox" in text:
            fail("default-bookmarks.html still has Firefox Nightly resource links", bad)
        elif "#ifndef NIGHTLY_BUILD" in text or "#else" in text:
            fail("default-bookmarks.html still has a live NIGHTLY_BUILD branch", bad)
        elif SUPPORT_URL not in text or HOME_URL not in text:
            fail("default-bookmarks.html is missing dane.surf support or home URLs", bad)
        elif "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0" in text:
            fail("default-bookmarks.html still embeds the old Firefox PNG icon", bad)
        else:
            pass_("default-bookmarks.html uses Dane URLs and Dane icon data; no Nightly Firefox block")
    if not os.path.isfile(BOOKMARKS_FTL):
        skip("default-bookmarks.ftl is not in this tree")
    else:
        text = read(BOOKMARKS_FTL)
        heading = ftl_value(text, "default-bookmarks-firefox-heading")
        nightly = ftl_value(text, "default-bookmarks-nightly-heading")
        if heading != "Dane":
            fail("default-bookmarks-firefox-heading is %r, not Dane" % heading, bad)
        elif nightly == "Firefox Nightly Resources":
            fail("default-bookmarks-nightly-heading still says Firefox Nightly Resources", bad)
        else:
            pass_("default-bookmarks folder titles are Dane, not Firefox Nightly Resources")


def check_filenames(bad):
    # Wordmark: filename/chrome URL documented, not renamed
    if not os.path.isfile(JAR):
        skip("greatdane content/jar.mn is not in this tree")
    else:
        text = read(JAR)
        if not re.search(r"content/branding/firefox-wordmark\.svg\s+\(about-wordmark\.svg\)", text):
            fail("jar.mn no longer aliases firefox-wordmark.svg to about-wordmark.svg", bad)
        else:
            pass_("firefox-wordmark.svg chrome URL remains an alias of about-wordmark.svg (not renamed)")
    if os.path.isfile(INVENTORY):
        text = read(INVENTORY)
        if "firefox-wordmark.svg" not in text or "not renamed" not in text.lower() and "documented, not renamed" not in text.lower() and "is not renamed" not in text.lower() and "filename is kept" not in text.lower() and "documented, not renamed" not in text:
            # accept several phrasings already in the file from 4e/4f
            if "not renamed" in text.lower() or "filename is kept" in text.lower() or "documented, not renamed" in text.lower() or "is kept only because" in text.lower():
                pass_("WORDMARK-SOURCES.md documents why firefox-wordmark.svg was not renamed")
            else:
                fail("WORDMARK-SOURCES.md does not document why firefox-wordmark.svg was not renamed", bad)
        else:
            pass_("WORDMARK-SOURCES.md documents why firefox-wordmark.svg was not renamed")
    else:
        skip("WORDMARK-SOURCES.md is not in this tree")

    # VisualElements renamed for greatdane only
    if os.path.isfile(OLD_VE) and not os.path.isfile(GREATDANE_VE):
        fail("greatdane still ships firefox.VisualElementsManifest.xml and has no greatdane.VisualElementsManifest.xml", bad)
    elif not os.path.isfile(GREATDANE_VE):
        skip("greatdane.VisualElementsManifest.xml is not in this tree")
    else:
        if os.path.isfile(OLD_VE):
            fail("greatdane still has firefox.VisualElementsManifest.xml next to the renamed file", bad)
        else:
            pass_("greatdane source file is greatdane.VisualElementsManifest.xml")
    if not os.path.isfile(BRANDING_COMMON):
        skip("branding-common.mozbuild is not in this tree")
    else:
        text = read(BRANDING_COMMON)
        if "greatdane.VisualElementsManifest.xml" not in text:
            fail("branding-common.mozbuild does not package greatdane.VisualElementsManifest.xml for greatdane", bad)
        elif 'CONFIG["MOZ_BRANDING_DIRECTORY"] == "browser/branding/greatdane"' not in text:
            fail("branding-common.mozbuild VisualElements rename is not gated on greatdane branding", bad)
        elif 'visual_elements_manifest = "firefox.VisualElementsManifest.xml"' not in text:
            fail("branding-common.mozbuild no longer packages firefox.VisualElementsManifest.xml for other branding", bad)
        else:
            pass_("branding-common.mozbuild renames VisualElements only for greatdane; official name unchanged")
    if not os.path.isfile(PACKAGE_MANIFEST):
        skip("package-manifest.in is not in this tree")
    else:
        text = read(PACKAGE_MANIFEST)
        if "@BINPATH@/firefox.VisualElementsManifest.xml" in text:
            fail("package-manifest.in still ships firefox.VisualElementsManifest.xml", bad)
        elif "@BINPATH@/@MOZ_APP_NAME@.VisualElementsManifest.xml" not in text:
            fail("package-manifest.in does not ship @MOZ_APP_NAME@.VisualElementsManifest.xml", bad)
        else:
            pass_("package-manifest.in ships @MOZ_APP_NAME@.VisualElementsManifest.xml")


def main():
    bad = []
    print("trademark_userfacing_check: root %s" % ROOT)
    check_about(bad)
    check_ftl_wording(bad)
    check_module_ver(bad)
    check_manifests(bad)
    check_branding_nsi(bad)
    check_sync_promo(bad)
    check_bookmarks(bad)
    check_filenames(bad)
    print()
    if bad:
        print("%d FAIL(s)" % len(bad))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
