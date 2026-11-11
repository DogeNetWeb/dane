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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pepecoin_publisher import (
    MakensisError,
    MakensisMissing,
    ModuleVerError,
    branding_publisher_values,
    cleanup_4l_bypass_payloads,
    is_empty_or_mozilla_publisher,
    is_printable_ascii,
    makensis_is_path_fallback,
    makensis_path,
    makensis_report,
    manifest_has_pepecoin,
    mentions_pepecoin,
    module_ver_company,
    module_ver_copyright,
    module_ver_parser_kind,
    module_ver_parser_report,
    module_ver_preprocessor_sha256,
    module_ver_preprocessor_sha_ok,
    prepare_4l_bypass_payloads,
    remove_command_sentinels,
    sentinels_that_exist,
    shared_nsh_has_pepecoin,
    UPSTREAM_PREPROCESSOR_SHA256,
)

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
SOURCE_URL = "https://dane.surf/source/"
DOWNLOAD_URL = "https://dane.surf/download/"
MANUAL_DOWNLOAD_URL = "https://dane.surf/download/?channel=unofficial"
HOME_URL = "https://dane.surf/"
MOZILLA_HOME = "https://www.mozilla.org/"
SHARED_NSH = os.path.join(ROOT, "browser/installer/windows/nsis/shared.nsh")


def fail(msg, bad):
    print("FAIL " + msg)
    bad.append(msg)


def pass_(msg):
    print("PASS " + msg)


def skip(msg):
    print("SKIP " + msg)


def warn(msg):
    print("WARN " + msg)


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

    # Unofficial Support / Privacy (round 4g: Terms relabeled Support)
    unofficial_has_support = False
    unofficial_has_privacy = False
    official_keeps_terms = False
    official_keeps_privacy = False
    unofficial_still_says_terms = False
    for unoff, off in unofficial_block(xhtml):
        if 'data-l10n-id="dane-bottom-links-support"' in unoff and SUPPORT_URL in unoff:
            unofficial_has_support = True
        if 'data-l10n-id="bottom-links-terms"' in unoff:
            unofficial_still_says_terms = True
        if 'data-l10n-id="bottom-links-privacy"' in unoff and PRIVACY_URL in unoff:
            unofficial_has_privacy = True
        if "terms/firefox/" in off and 'data-l10n-id="bottom-links-terms"' in off:
            official_keeps_terms = True
        if "privacy/firefox/" in off and 'data-l10n-id="bottom-links-privacy"' in off:
            official_keeps_privacy = True
    if unofficial_still_says_terms:
        fail("unofficial About still uses bottom-links-terms; it should be dane-bottom-links-support", bad)
    elif not unofficial_has_support:
        fail("unofficial About Support link is not %s with dane-bottom-links-support" % SUPPORT_URL, bad)
    else:
        pass_("unofficial About Support link is %s (dane-bottom-links-support)" % SUPPORT_URL)
    if not unofficial_has_privacy:
        fail("unofficial About Privacy link is not %s" % PRIVACY_URL, bad)
    else:
        pass_("unofficial About Privacy link is %s" % PRIVACY_URL)
    if not official_keeps_terms or not official_keeps_privacy:
        fail("official About Terms/Privacy URLs or IDs were not preserved", bad)
    else:
        pass_("official About Terms/Privacy URLs and Terms of Use ID are unchanged")

    # Donate dropped unofficial only (Frank 3, NGD M1)
    unofficial_donate = False
    official_donate = False
    unofficial_involved = False
    for unoff, off in unofficial_block(xhtml):
        if "helpus-donateLink" in unoff or "foundation.mozilla.org" in unoff:
            unofficial_donate = True
        if 'data-l10n-id="dane-helpus"' in unoff and SOURCE_URL in unoff:
            unofficial_involved = True
        if "helpus-donateLink" in off and "foundation.mozilla.org" in off:
            official_donate = True
    if unofficial_donate:
        fail("unofficial About still has a donate link", bad)
    else:
        pass_("unofficial About drops the donate link")
    if not unofficial_involved:
        fail("unofficial About get-involved is not %s under dane-helpus" % SOURCE_URL, bad)
    else:
        pass_("unofficial About get-involved is %s" % SOURCE_URL)
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

    support = ftl_value(brand, "dane-bottom-links-support")
    if support != "Support":
        fail("brand.ftl dane-bottom-links-support is %r, expected 'Support'" % support, bad)
    else:
        pass_("brand.ftl dane-bottom-links-support is Support")
    official_terms = ftl_value(about, "bottom-links-terms")
    if official_terms != "Terms of Use":
        fail("aboutDialog.ftl bottom-links-terms is %r, official Terms of Use must stay intact" % official_terms, bad)
    else:
        pass_("aboutDialog.ftl bottom-links-terms stays 'Terms of Use' for official branding")

    dane_sync = ftl_value(brand, "dane-sync-mobile-promo")
    if not dane_sync or "download page" not in dane_sync or re.search(r"Download Firefox", dane_sync or ""):
        fail("brand.ftl dane-sync-mobile-promo is missing or still says Download Firefox: %r" % dane_sync, bad)
    else:
        pass_("brand.ftl dane-sync-mobile-promo is the unofficial Dane download wording")


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
        try:
            company = module_ver_company(path)
            copyright = module_ver_copyright(path) or ""
        except ModuleVerError as exc:
            fail("%s module.ver parser failed: %s" % (rel, exc), bad)
            continue
        if mentions_pepecoin(company) or mentions_pepecoin(copyright):
            fail("%s still has a Pepecoin publisher/company/copyright string" % rel, bad)
        elif "TODO-OWNER" not in text:
            fail("%s is missing a TODO-OWNER marker on the publisher/company placeholders" % rel, bad)
        elif "Mozilla Corporation" in text:
            fail("%s still names Mozilla Corporation" % rel, bad)
        elif "Firefox is a Trademark of The Mozilla Foundation" in text:
            fail("%s still uses the Firefox-product trademark line" % rel, bad)
        elif "Firefox and Mozilla are trademarks of Mozilla.org" not in text:
            fail("%s is missing the Mozilla.org trademark credit" % rel, bad)
        elif "WIN32_MODULE_COMPANYNAME=" not in text or "WIN32_MODULE_COPYRIGHT=" not in text:
            fail("%s is missing company or copyright keys" % rel, bad)
        elif b"\xa9" not in raw:
            fail("%s copyright is missing the Latin-1 copyright sign" % rel, bad)
        elif is_empty_or_mozilla_publisher(company):
            fail("%s WIN32_MODULE_COMPANYNAME is empty or contains 'mozilla': %r" % (rel, company), bad)
        elif not is_printable_ascii(company):
            fail("%s WIN32_MODULE_COMPANYNAME is not printable ASCII: %r" % (rel, company), bad)
        else:
            pass_("%s has TODO-OWNER publisher placeholders, no Pepecoin, Mozilla.org trademark credit kept" % rel)
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
        ('URLManualDownload', MANUAL_DOWNLOAD_URL),
        ('URLSystemRequirements', SUPPORT_URL),
        ('CertNameDownload', 'TODO-NO-WINDOWS-SIGNING-IDENTITY-YET'),
        ('CertIssuerDownload', 'TODO-NO-WINDOWS-SIGNING-IDENTITY-YET'),
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
    elif "TODO-OWNER" not in text:
        fail("branding.nsi is missing a TODO-OWNER marker on the publisher placeholders", bad)
    elif "ARPPublisher" not in defines:
        fail("branding.nsi is missing ARPPublisher for Add/Remove Programs", bad)
    elif "TODO(windows-signing)" not in text or "owner's decision" not in text.lower():
        fail("branding.nsi is missing the TODO comment that no Windows signing identity exists yet and the publisher name is the owner's decision", bad)
    else:
        try:
            company, publisher = branding_publisher_values(BRANDING_NSI)
        except MakensisMissing as exc:
            fail("makensis is required to resolve branding.nsi publisher values but was not found (%s); not PASS" % exc, bad)
            return
        except MakensisError as exc:
            fail("makensis -PPO failed on greatdane branding.nsi: %s" % exc, bad)
            return
        if mentions_pepecoin(company) or mentions_pepecoin(publisher):
            fail("branding.nsi still has a Pepecoin publisher/company define (makensis -PPO: CompanyName=%r ARPPublisher=%r)" % (company, publisher), bad)
        elif is_empty_or_mozilla_publisher(company) or is_empty_or_mozilla_publisher(publisher):
            fail("branding.nsi CompanyName/ARPPublisher is empty or contains 'mozilla': CompanyName=%r ARPPublisher=%r" % (company, publisher), bad)
        elif not is_printable_ascii(company) or not is_printable_ascii(publisher):
            fail("branding.nsi CompanyName/ARPPublisher is not printable ASCII: CompanyName=%r ARPPublisher=%r" % (company, publisher), bad)
        else:
            pass_("branding.nsi has TODO-OWNER publisher placeholders, ARPPublisher, stub cert TODOs, and dane.surf URLs (makensis %s)" % (makensis_report() or "unknown"))


def check_sync_promo(bad):
    if not os.path.isfile(PREFS_FTL):
        skip("preferences.ftl is not in this tree")
    else:
        text = read(PREFS_FTL)
        val = ftl_value(text, "sync-mobile-promo")
        if not val:
            fail("preferences.ftl is missing sync-mobile-promo", bad)
        elif "Download Firefox" not in val or "Android" not in val or "iOS" not in val:
            fail("preferences.ftl sync-mobile-promo is not the stock official Firefox string: %r" % val, bad)
        else:
            pass_("preferences.ftl sync-mobile-promo is the stock official Firefox string")
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
        unofficial_ok = (
            'data-l10n-id="dane-sync-mobile-promo"' in text
            and "fxaMobilePromo-android" in text
            and "#ifndef MOZ_OFFICIAL_BRANDING" in text
        )
        official_ok = (
            'data-l10n-id="sync-mobile-promo"' in text
            and "logo-android.svg" in text
            and "logo-ios.svg" in text
            and "fxaMobilePromo-ios" in text
        )
        if not unofficial_ok:
            fail("sync.inc.xhtml unofficial branch is not the gated dane-sync-mobile-promo markup", bad)
        elif not official_ok:
            fail("sync.inc.xhtml official branch is not the stock Android/iOS promo markup", bad)
        elif 'id="connect-another-device"' not in text:
            fail("connect-another-device was removed; Sync UI must stay", bad)
        else:
            pass_("sync promo: unofficial uses dane-sync-mobile-promo; official stock markup kept; Sync itself unchanged")


def check_bookmarks(bad):
    if not os.path.isfile(BOOKMARKS_HTML):
        skip("default-bookmarks.html is not in this tree")
    else:
        text = read(BOOKMARKS_HTML)
        if "#ifndef MOZ_OFFICIAL_BRANDING" not in text:
            fail("default-bookmarks.html is not gated on MOZ_OFFICIAL_BRANDING", bad)
        elif "dane-default-bookmarks-community" not in text or SOURCE_URL not in text:
            fail("unofficial bookmarks are missing Get Involved -> %s" % SOURCE_URL, bad)
        elif SUPPORT_URL not in text or HOME_URL not in text:
            fail("unofficial bookmarks are missing dane.surf support or home URLs", bad)
        elif "dane-default-bookmarks-customize" in text:
            fail("unofficial bookmarks still have a Customize Dane entry (no support anchor exists)", bad)
        elif "support.mozilla.org/products/firefox" not in text or "customize-firefox-controls" not in text:
            fail("official bookmark URLs were not restored", bad)
        elif "#ifndef NIGHTLY_BUILD" not in text or "blog.nightly.mozilla.org" not in text:
            fail("official NIGHTLY_BUILD bookmark block was not restored", bad)
        else:
            pass_("default-bookmarks.html: unofficial Dane URLs (no Customize, Get Involved -> source); official stock restored")
    if not os.path.isfile(BOOKMARKS_FTL):
        skip("default-bookmarks.ftl is not in this tree")
    else:
        text = read(BOOKMARKS_FTL)
        heading = ftl_value(text, "default-bookmarks-firefox-heading")
        customize = ftl_value(text, "default-bookmarks-firefox-customize")
        nightly = ftl_value(text, "default-bookmarks-nightly-heading")
        if heading != "Mozilla Firefox":
            fail("default-bookmarks-firefox-heading is %r, official stock is Mozilla Firefox" % heading, bad)
        elif customize != "Customize Firefox":
            fail("default-bookmarks-firefox-customize is %r, official stock is Customize Firefox" % customize, bad)
        elif nightly != "Firefox Nightly Resources":
            fail("default-bookmarks-nightly-heading is %r, official stock was not restored" % nightly, bad)
        else:
            pass_("default-bookmarks.ftl official titles are the stock Firefox strings")


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


# Windows publisher/company metadata. pepecoin.surf update URLs and other
# existing site / bundle-id references are not publisher strings.
PUBLISHER_FILES = (
    "browser/app/module.ver",
    "browser/app/pbproxy/module.ver",
    "browser/app/firefox.exe.manifest",
    "browser/app/desktop-launcher/desktop-launcher.exe.manifest",
    "browser/branding/greatdane/branding.nsi",
    "browser/installer/windows/nsis/shared.nsh",
)


def check_no_pepecoin_publisher(bad):
    found = 0
    for rel in PUBLISHER_FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            skip("%s is not in this tree (Pepecoin publisher scan)" % rel)
            continue
        found += 1
        raw = open(path, "rb").read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        pepe = False
        if rel.endswith("module.ver"):
            try:
                pepe = mentions_pepecoin(module_ver_company(path)) or mentions_pepecoin(module_ver_copyright(path))
            except ModuleVerError as exc:
                fail("%s module.ver parser failed: %s" % (rel, exc), bad)
                continue
        elif rel.endswith("branding.nsi"):
            try:
                company, publisher = branding_publisher_values(path)
            except MakensisMissing as exc:
                fail("makensis is required to scan branding.nsi but was not found (%s); not PASS" % exc, bad)
                continue
            except MakensisError as exc:
                fail("makensis -PPO failed on %s: %s" % (rel, exc), bad)
                continue
            pepe = mentions_pepecoin(company) or mentions_pepecoin(publisher)
        elif rel.endswith(".manifest"):
            pepe = manifest_has_pepecoin(path)
        elif rel.endswith("shared.nsh"):
            pepe = shared_nsh_has_pepecoin(path)
        else:
            pepe = mentions_pepecoin(text)
        if pepe:
            fail("%s still contains a Pepecoin publisher/company/copyright string" % rel, bad)
        else:
            pass_("%s has no Pepecoin publisher/company/copyright string" % rel)
    if found == 0:
        skip("no Windows publisher metadata files in this snapshot")




# NGD 4h/4i fixtures, 4j L1–L8, and 4k F1–F4. Each must be rejected.
# The real tree must still pass.
FIXTURE_DIR = os.path.join(ROOT, "greatdane/tests/fixtures/pepecoin-publisher")

# name, kind ('module.ver' or 'branding.nsi'), relative path, expected verdict
PEPECOIN_BYPASS_FIXTURES = (
    # 4h/4i residual cases, still required
    ("A", "module.ver", "A.module.ver", "pepecoin"),
    ("A2", "module.ver", "A2.module.ver", "pepecoin"),
    ("C", "branding.nsi", "C.branding.nsi", "pepecoin"),
    ("E", "branding.nsi", "E.branding.nsi", "pepecoin"),
    ("D2", "branding.nsi", "D2.branding.nsi", "pepecoin"),
    ("empty-company", "module.ver", "empty-company.module.ver", "empty-or-mozilla"),
    ("arp-mozilla", "branding.nsi", "arp-mozilla.branding.nsi", "empty-or-mozilla"),
    # L1–L8 (NGD 4i reproduced bypasses)
    ("L1-N11", "branding.nsi", "L1-N11-Uplus.branding.nsi", "pepecoin"),
    ("L2-N20", "branding.nsi", "L2-N20-redef.branding.nsi", "not-allowlisted"),
    ("L3-N21", "branding.nsi", "L3-N21-searchreplace.branding.nsi", "not-allowlisted"),
    ("L4-N22", "branding.nsi", "L4-N22-file/branding.nsi", "not-allowlisted"),
    ("L5-N5", "branding.nsi", "L5-N5-ifndef.branding.nsi", "not-allowlisted"),
    ("L5-N6", "branding.nsi", "L5-N6-indented.branding.nsi", "pepecoin"),
    ("L5-N9b", "branding.nsi", "L5-N9b-include/branding.nsi", "pepecoin"),
    ("L5-N14", "module.ver", "L5-N14-define.module.ver", "pepecoin"),
    ("L6-N1", "branding.nsi", "L6-N1-cyrillic.branding.nsi", "pepecoin"),
    ("L6-N16", "branding.nsi", "L6-N16-acute.branding.nsi", "pepecoin"),
    ("L7-N2", "branding.nsi", "L7-N2-zwsp.branding.nsi", "pepecoin"),
    ("L7-N3", "branding.nsi", "L7-N3-hyphen.branding.nsi", "pepecoin"),
    ("L7-N4", "branding.nsi", "L7-N4-spaces.branding.nsi", "pepecoin"),
    ("L8-foundation", "branding.nsi", "L8-mozilla-foundation.branding.nsi", "empty-or-mozilla"),
    ("L8-corporation", "branding.nsi", "L8-mozilla-corporation.branding.nsi", "empty-or-mozilla"),
    # 4k F1–F4. F1-if: the upstream Preprocessor evaluates `%if 1` and
    # the company is Pepecoin (verdict "pepecoin"). The fallback
    # reimplementation refuses any % directive other than define/include
    # (verdict "forbidden-directive"). F2/F3 NSIS constructs are now
    # caught by the 4l allowlist (verdict "not-allowlisted").
    ("F1-if", "module.ver", "F1-if.module.ver",
     "pepecoin" if module_ver_parser_kind() == "mozbuild.preprocessor" else "forbidden-directive"),
    ("F1-undefined-at", "module.ver", "F1-undefined-at.module.ver", "undefined-subst"),
    ("F2-system", "branding.nsi", "F2-system.branding.nsi", "not-allowlisted"),
    ("F2-appendfile", "branding.nsi", "F2-appendfile.branding.nsi", "not-allowlisted"),
    ("F3-ifdef", "branding.nsi", "F3-ifdef.branding.nsi", "not-allowlisted"),
    ("F4-non-ascii", "branding.nsi", "F4-non-ascii.branding.nsi", "non-ascii"),
    # 4l G2/G3/G4/G5/G10 + !tempfile: allowlist refusals (were denylist bypasses)
    ("G2-abs-include", "branding.nsi", "G2-abs-include.branding.nsi", "not-allowlisted"),
    ("G3-addincludedir", "branding.nsi", "G3-addincludedir.branding.nsi", "not-allowlisted"),
    ("G4-continuation", "branding.nsi", "G4-continuation.branding.nsi", "not-allowlisted"),
    ("G5-expanded-command", "branding.nsi", "G5-expanded-command.branding.nsi", "not-allowlisted"),
    ("G10-wildcard-include", "branding.nsi", "G10-wildcard-include.branding.nsi", "not-allowlisted"),
    ("G7-tempfile", "branding.nsi", "G7-tempfile.branding.nsi", "not-allowlisted"),
)


def fixture_violations(name, kind, rel, expect):
    """Return the violation kind detected in a fixture, or None if it slipped through."""
    path = os.path.join(FIXTURE_DIR, rel)
    if not os.path.isfile(path):
        return None
    try:
        if kind == "module.ver":
            company = module_ver_company(path)
            copyright = module_ver_copyright(path)
            pepe = mentions_pepecoin(company) or mentions_pepecoin(copyright)
            empty = is_empty_or_mozilla_publisher(company)
            non_ascii = not is_printable_ascii(company)
        else:
            company, publisher = branding_publisher_values(path)
            pepe = mentions_pepecoin(company) or mentions_pepecoin(publisher)
            empty = is_empty_or_mozilla_publisher(company) or is_empty_or_mozilla_publisher(publisher)
            non_ascii = not is_printable_ascii(company) or not is_printable_ascii(publisher)
    except ModuleVerError as exc:
        msg = str(exc).lower()
        if "undefined" in msg:
            return "undefined-subst"
        return "forbidden-directive"
    except MakensisError as exc:
        msg = str(exc)
        if "refused to invoke makensis" in msg and (
            "allowlist" in msg or "not a relative sibling" in msg
        ):
            return "not-allowlisted"
        if "refused to invoke makensis" in msg and any(
            token in msg for token in ("!ifdef", "!ifndef", " contains !if")
        ):
            return "forbidden-if"
        if "refused to invoke makensis" in msg:
            return "forbidden-command"
        raise
    if expect == "pepecoin" and pepe:
        return "pepecoin"
    if expect == "empty-or-mozilla" and empty:
        return "empty-or-mozilla"
    if expect == "non-ascii" and non_ascii:
        return "non-ascii"
    if pepe:
        return "pepecoin"
    if empty:
        return "empty-or-mozilla"
    if non_ascii:
        return "non-ascii"
    return None


def check_module_ver_parser(bad):
    """Report the parser in use; FAIL if an imported preprocessor.py hash mismatches."""
    pass_("module.ver parser: %s" % module_ver_parser_report())
    if module_ver_parser_kind() != "mozbuild.preprocessor":
        return
    actual = module_ver_preprocessor_sha256()
    if module_ver_preprocessor_sha_ok():
        pass_(
            "imported preprocessor.py sha256 %s matches ESR 153.7.0" % actual
        )
    else:
        fail(
            "imported preprocessor.py sha256 %s does not match ESR 153.7.0 %s"
            % (actual, UPSTREAM_PREPROCESSOR_SHA256),
            bad,
        )


def check_pepecoin_bypass_fixtures(bad):
    report = makensis_report()
    if not makensis_path():
        fail(
            "makensis is required to evaluate NSIS publisher fixtures but was not found "
            "($MAKENSISU, ~/.mozbuild/nsis/bin/makensis, or PATH); not PASS",
            bad,
        )
        return
    pass_("makensis -PPO available: %s" % report)
    if makensis_is_path_fallback():
        warn(
            "makensis is the PATH fallback: %s (not $MAKENSISU or ~/.mozbuild v3.07)"
            % report
        )
    prepare_4l_bypass_payloads(FIXTURE_DIR)
    remove_command_sentinels()
    try:
        for name, kind, rel, expect in PEPECOIN_BYPASS_FIXTURES:
            path = os.path.join(FIXTURE_DIR, rel)
            if not os.path.isfile(path):
                fail("bypass fixture %s is missing: %s" % (name, rel), bad)
                continue
            try:
                got = fixture_violations(name, kind, rel, expect)
            except (MakensisMissing, MakensisError, ModuleVerError) as exc:
                fail("bypass fixture %s: tool failed: %s" % (name, exc), bad)
                continue
            if got != expect:
                fail(
                    "bypass fixture %s was not rejected as %s (got %s)"
                    % (name, expect, got),
                    bad,
                )
            else:
                pass_("bypass fixture %s correctly rejected (%s)" % (name, expect))
        leftover = sentinels_that_exist()
        if leftover:
            fail("makensis wrote command sentinels: %s" % leftover, bad)
        else:
            pass_("no command sentinels were written by the bypass fixtures")
    finally:
        cleanup_4l_bypass_payloads()


def check_shared_nsh(bad):
    if not os.path.isfile(SHARED_NSH):
        skip("shared.nsh is not in this tree")
        return
    text = read(SHARED_NSH)
    if "!ifdef ARPPublisher" not in text or '"${ARPPublisher}"' not in text:
        fail("shared.nsh does not use branding ARPPublisher for Add/Remove Programs Publisher", bad)
    elif '"Mozilla"' not in text or "!else" not in text:
        fail("shared.nsh official Publisher Mozilla fallback is missing", bad)
    elif "TODO-OWNER" not in text:
        fail("shared.nsh is missing a TODO-OWNER marker on the Add/Remove Programs publisher", bad)
    elif shared_nsh_has_pepecoin(SHARED_NSH):
        fail("shared.nsh still has a Pepecoin publisher string", bad)
    else:
        pass_("shared.nsh Add/Remove Programs Publisher is ${ARPPublisher} when defined, else Mozilla; TODO-OWNER present")


def main():
    bad = []
    print("trademark_userfacing_check: root %s" % ROOT)
    check_about(bad)
    check_ftl_wording(bad)
    check_module_ver(bad)
    check_manifests(bad)
    check_branding_nsi(bad)
    check_module_ver_parser(bad)
    check_shared_nsh(bad)
    check_no_pepecoin_publisher(bad)
    check_pepecoin_bypass_fixtures(bad)
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
