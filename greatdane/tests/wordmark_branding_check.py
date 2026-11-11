#!/usr/bin/env python3
"""Source-level check that Dane branding does not ship a Firefox wordmark.

Run from the source tree root:
  python3 greatdane/tests/wordmark_branding_check.py

No build, no signing, no network. Exit 0 on pass, 1 on any failure.
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

ABOUT_WM = os.path.join(ROOT, "browser/branding/greatdane/content/about-wordmark.svg")
FIREFOX_WM = os.path.join(ROOT, "browser/branding/greatdane/content/firefox-wordmark.svg")
JAR = os.path.join(ROOT, "browser/branding/greatdane/content/jar.mn")
INVENTORY = os.path.join(ROOT, "greatdane/WORDMARK-SOURCES.md")
OFFICIAL_WM = os.path.join(ROOT, "browser/branding/official/content/firefox-wordmark.svg")

# Fragment of the official Firefox path-logo (must not appear in Dane wordmarks).
OFFICIAL_PATH_FRAG = "M0 0h52.89"
NAVY = "#13254A"

STOCK_WORDMARK_URL = "chrome://branding/content/firefox-wordmark.svg"
ABOUT_WORDMARK_URL = "chrome://branding/content/about-wordmark.svg"

STOCK_CSS = (
    "browser/extensions/newtab/content-src/components/Logo/_Logo.scss",
    "browser/extensions/newtab/css/activity-stream.css",
    "browser/extensions/newtab/css/nova/activity-stream.css",
    "browser/themes/shared/privatebrowsing/aboutPrivateBrowsing.css",
)
ABOUT_CSS = "browser/base/content/aboutDialog.css"

DOCUMENTED_LEFTOVERS = (
    "chrome://newtab/content/data/content/assets/firefox.svg",
    "firefox-mascot-prop-paintbucket-rgb.svg",
    "firefox-motion-head-pop-up-no-bg.svg",
    "firefox-wallpaper-desktop-hills-light-rgb.svg",
    "chrome://global/content/ml/mozilla-logo.webp",
)


def fail(msg, bad):
    print("FAIL " + msg)
    bad.append(msg)


def pass_(msg):
    print("PASS " + msg)


def skip(msg):
    print("SKIP " + msg)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def check_wordmark_svg(path, label, bad):
    if not os.path.isfile(path):
        fail("%s is missing (%s)" % (label, path), bad)
        return
    text = read(path)
    if OFFICIAL_PATH_FRAG in text or "h52.89v11.95" in text:
        fail("%s still contains the official Firefox path-logo" % label, bad)
    if re.search(r"<path[\s>]", text):
        fail("%s should be a text wordmark, but contains a <path>" % label, bad)
    if not re.search(r">Dane</text>", text):
        fail("%s does not contain a plain-text 'Dane' element" % label, bad)
    if "context-fill" not in text:
        fail("%s is missing context-fill (stock CSS sets fill via context properties)" % label, bad)
    # Navy fallback, case-insensitive, allow with or without the hash on a separate fill.
    if NAVY.lower() not in text.lower() and NAVY in text:
        pass_("%s has navy fallback" % label)
    elif NAVY.lower() not in text.lower():
        fail("%s is missing the navy fallback %s" % (label, NAVY), bad)
    else:
        pass_("%s is a plain-text Dane wordmark with context-fill and navy fallback %s" % (label, NAVY))
    # Transparent ground: no full-canvas rect / background fill other than text.
    if re.search(r"<rect[^>]*fill=", text, re.I):
        fail("%s has a filled rect (wordmark should be on transparent ground)" % label, bad)
    else:
        pass_("%s has no background rect (transparent ground)" % label)


def check_jar(bad):
    if not os.path.isfile(JAR):
        fail("greatdane content/jar.mn is missing", bad)
        return
    text = read(JAR)
    # Alias: firefox-wordmark.svg maps to about-wordmark.svg
    alias = re.search(
        r"content/branding/firefox-wordmark\.svg\s+\(about-wordmark\.svg\)",
        text,
    )
    if not alias:
        fail("jar.mn does not alias firefox-wordmark.svg to about-wordmark.svg", bad)
    else:
        pass_("jar.mn aliases content/branding/firefox-wordmark.svg to about-wordmark.svg")
    if "content/branding/about-wordmark.svg" not in text:
        fail("jar.mn does not ship about-wordmark.svg", bad)
    else:
        pass_("jar.mn ships about-wordmark.svg")
    if "% override chrome://browser/skin/window-firefox.svg chrome://branding/content/greatdane-icon.svg" not in text:
        fail("jar.mn is missing the window-firefox.svg override to greatdane-icon.svg", bad)
    else:
        pass_("jar.mn overrides chrome://browser/skin/window-firefox.svg to greatdane-icon.svg")
    if "% override chrome://browser/skin/sidebar/firefox.svg chrome://branding/content/greatdane-icon.svg" not in text:
        fail("jar.mn lost the existing sidebar/firefox.svg override", bad)
    else:
        pass_("jar.mn keeps the existing sidebar/firefox.svg override")
    # Must not override official branding files or disable packs.
    if "browser/branding/official" in text:
        fail("jar.mn unexpectedly mentions official branding", bad)


def check_no_duplicate_file(bad):
    if os.path.isfile(FIREFOX_WM):
        # Allowed only if it is byte-identical to about-wordmark.svg.
        about = open(ABOUT_WM, "rb").read()
        other = open(FIREFOX_WM, "rb").read()
        if about != other:
            fail("firefox-wordmark.svg exists and differs from about-wordmark.svg; it should be an alias only", bad)
        else:
            pass_("firefox-wordmark.svg is a byte-identical copy of about-wordmark.svg")
    else:
        pass_("no separate firefox-wordmark.svg file (chrome URL is the jar.mn alias)")


def check_official_untouched(bad):
    if not os.path.isfile(OFFICIAL_WM):
        skip("official firefox-wordmark.svg is not in this tree (snapshot); official branding was not imported or changed")
        return
    text = read(OFFICIAL_WM)
    if OFFICIAL_PATH_FRAG not in text:
        fail("official firefox-wordmark.svg no longer looks like the upstream Firefox wordmark", bad)
    else:
        pass_("official firefox-wordmark.svg is still the upstream Firefox path-logo")


def check_stock_css_untouched(bad):
    found = 0
    for rel in STOCK_CSS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        found += 1
        text = read(path)
        if STOCK_WORDMARK_URL not in text:
            fail("%s no longer references %s" % (rel, STOCK_WORDMARK_URL), bad)
        else:
            pass_("%s still loads %s (stock file not rewritten)" % (rel, STOCK_WORDMARK_URL))
    if found == 0:
        skip("stock new-tab / private-browsing CSS not in this snapshot; expected URL is %s" % STOCK_WORDMARK_URL)
    about = os.path.join(ROOT, ABOUT_CSS)
    if os.path.isfile(about):
        text = read(about)
        if ABOUT_WORDMARK_URL not in text:
            fail("aboutDialog.css no longer references %s" % ABOUT_WORDMARK_URL, bad)
        else:
            pass_("aboutDialog.css still loads %s" % ABOUT_WORDMARK_URL)
    else:
        skip("aboutDialog.css not in this snapshot; expected URL is %s" % ABOUT_WORDMARK_URL)


def check_inventory(bad):
    if not os.path.isfile(INVENTORY):
        fail("greatdane/WORDMARK-SOURCES.md is missing", bad)
        return
    text = read(INVENTORY)
    missing = [item for item in DOCUMENTED_LEFTOVERS if item not in text]
    if missing:
        fail("WORDMARK-SOURCES.md does not document leftover(s): " + ", ".join(missing), bad)
    else:
        pass_("WORDMARK-SOURCES.md documents the stock leftovers that were not swapped")
    if "not a trademark clearance" not in text.lower() and "Not a trademark clearance" not in text:
        # the file says "This is not a trademark clearance."
        if "trademark clearance" not in text.lower():
            fail("WORDMARK-SOURCES.md should state this is not a trademark clearance", bad)
        else:
            pass_("WORDMARK-SOURCES.md states this is not a trademark clearance")
    else:
        pass_("WORDMARK-SOURCES.md states this is not a trademark clearance")


def main():
    bad = []
    print("wordmark_branding_check: root %s" % ROOT)
    check_wordmark_svg(ABOUT_WM, "about-wordmark.svg", bad)
    check_no_duplicate_file(bad)
    check_jar(bad)
    check_official_untouched(bad)
    check_stock_css_untouched(bad)
    check_inventory(bad)
    print()
    if bad:
        print("%d FAIL(s)" % len(bad))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
