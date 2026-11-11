#!/usr/bin/env python3
"""Source-level check that Dane branding covers every shipped locale.

Run from the source tree root:
  python3 greatdane/tests/locale_branding_check.py

No build, no signing, no network. Exit 0 on pass, 1 on any failure.
"""
from __future__ import annotations

import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "browser", "locales"))
import generate_ini  # noqa: E402

EN_US_UPDATER = os.path.join(ROOT, "browser/locales/en-US/updater/updater.ini")
ALL_LOCALES = os.path.join(ROOT, "browser/locales/all-locales")
SHIPPED_LOCALES = os.path.join(ROOT, "browser/locales/shipped-locales")
BRAND_FTL = os.path.join(ROOT, "browser/branding/greatdane/locales/en-US/brand.ftl")
BRAND_JAR = os.path.join(ROOT, "browser/branding/greatdane/locales/jar.mn")
ABOUT_FTL = os.path.join(ROOT, "browser/locales/en-US/browser/aboutDialog.ftl")
ABOUT_XHTML = os.path.join(ROOT, "browser/base/content/aboutDialog.xhtml")
FIXTURES = os.path.join(ROOT, "greatdane/tests/fixtures/updater-ini")

EXPECTED_ATTR = (
    "{ -brand-short-name } is built from Mozilla's open source Firefox ESR web browser. "
    "{ -brand-short-name } is not officially associated with Mozilla or its products."
)
EXPECTED_TRADEMARK = (
    "Firefox and Mozilla are trademarks of Mozilla.org in the U.S. and other countries."
)
# Upstream ESR153 en-US aboutDialog.ftl (NGD L1). Official branding uses these IDs.
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
DANE_MAINT = generate_ini.branded_maintenance_description("Dane")
# Product names that must not remain in the overridden maintenance value.
FORBIDDEN_MAINT = re.compile(r"Mozilla Firefox|(?<![A-Za-z])Firefox(?![A-Za-z])")

# Locale codes used as fixtures, all of which must also appear in the shipped list
# except the synthetic xx-* cases.
L10N_FIXTURES = ("de", "fr", "ja", "zh-CN", "en-GB", "ar")

# ESR153 browser/locales/l10n-changesets.json records this revision for every
# locale, including the six fixtures (NGD L3).
L10N_CHANGESETS = os.path.join(ROOT, "browser/locales/l10n-changesets.json")
ESR153_L10N_REVISION = "3ae91662ee285b44f21ef31b9cae722d132e28ea"


def read_locales(path):
    codes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                codes.append(line)
    return codes


def fail(msg, bad):
    print("FAIL " + msg)
    bad.append(msg)


def pass_(msg):
    print("PASS " + msg)


def maint_value(text):
    m = re.search(r"^MozillaMaintenanceDescription=(.*)$", text, re.MULTILINE)
    return m.group(1) if m else None


def run_generate(path, display_name, os_target="Darwin"):
    out = io.StringIO()
    generate_ini.main(
        out,
        path,
        substs={"MOZ_APP_DISPLAYNAME": display_name, "OS_TARGET": os_target},
    )
    return out.getvalue()


def check_locale_lists(bad):
    all_codes = read_locales(ALL_LOCALES)
    shipped = read_locales(SHIPPED_LOCALES)
    union = sorted(set(all_codes) | set(shipped) | {"en-US"})
    if "en-US" not in shipped:
        fail("en-US missing from shipped-locales", bad)
    if not all_codes:
        fail("all-locales is empty", bad)
    if len(shipped) < 2:
        fail("shipped-locales looks too small: %d" % len(shipped), bad)
    # The override must not be a locale allowlist: every listed locale is covered
    # by the same display-name gate.
    uncovered = [
        loc
        for loc in union
        if not generate_ini.should_override_maintenance_description("Dane")
    ]
    if uncovered:
        fail("display-name gate missed locales: " + ", ".join(uncovered), bad)
    else:
        pass_(
            "maintenance override is global (not an allowlist): "
            "%d locales in all-locales, %d in shipped-locales, %d in the union"
            % (len(all_codes), len(shipped), len(union))
        )
    missing_fixtures = [loc for loc in L10N_FIXTURES if loc not in set(all_codes) | set(shipped)]
    if missing_fixtures:
        fail("fixture locales not in all-locales/shipped-locales: " + ", ".join(missing_fixtures), bad)
    else:
        pass_("fixture locales de/fr/ja/zh-CN/en-GB/ar are in the shipped or all-locales lists")
    return union


def check_en_us_source(bad):
    text = open(EN_US_UPDATER, encoding="utf-8").read()
    val = maint_value(text)
    if val is None:
        fail("en-US updater.ini has no MozillaMaintenanceDescription", bad)
        return
    if "%MOZ_APP_DISPLAYNAME%" not in val:
        fail("en-US MozillaMaintenanceDescription does not use %MOZ_APP_DISPLAYNAME%", bad)
    elif "Mozilla Firefox" in val or re.search(r"(?<![%A-Za-z])Firefox(?![A-Za-z])", val):
        fail("en-US MozillaMaintenanceDescription still names Firefox literally: " + val, bad)
    else:
        pass_("en-US updater.ini already uses %MOZ_APP_DISPLAYNAME% in MozillaMaintenanceDescription")


def check_fixtures(bad):
    for loc in L10N_FIXTURES:
        path = os.path.join(FIXTURES, loc + ".ini")
        raw = open(path, encoding="utf-8").read()
        raw_val = maint_value(raw)
        if raw_val is None or "Firefox" not in raw_val:
            fail("%s fixture does not contain a Firefox maintenance string (bad fixture)" % loc, bad)
            continue
        dane = run_generate(path, "Dane")
        official = run_generate(path, "Firefox")
        official_moz = run_generate(path, "Mozilla Firefox")
        dane_val = maint_value(dane)
        if dane_val != DANE_MAINT:
            fail("%s + Dane: expected branded English value, got %r" % (loc, dane_val), bad)
        elif FORBIDDEN_MAINT.search(dane_val or ""):
            fail("%s + Dane: leftover Firefox/Mozilla Firefox in maintenance value" % loc, bad)
        elif dane.count("MozillaMaintenanceDescription=") != 1:
            fail("%s + Dane: key not unique (%d)" % (loc, dane.count("MozillaMaintenanceDescription=")), bad)
        else:
            pass_("%s + Dane: MozillaMaintenanceDescription is the branded Dane wording" % loc)
        # Title/Info stay localized and get the display name.
        if "%MOZ_APP_DISPLAYNAME%" in dane:
            fail("%s + Dane: unsubstituted %%MOZ_APP_DISPLAYNAME%% remains" % loc, bad)
        if "TitleText=" in dane and "Dane" not in [ln.split("=", 1)[-1] for ln in dane.splitlines() if ln.startswith("TitleText=")][0]:
            fail("%s + Dane: TitleText was not localized-substituted" % loc, bad)
        # Official builds must keep the original localized value (minus Title/Info substitution).
        if maint_value(official) != raw_val:
            fail("%s + Firefox: official wording was changed" % loc, bad)
        else:
            pass_("%s + Firefox: official localized MozillaMaintenanceDescription kept" % loc)
        if maint_value(official_moz) != raw_val:
            fail("%s + Mozilla Firefox: official wording was changed" % loc, bad)

    # en-US source through the generator
    dane = run_generate(EN_US_UPDATER, "Dane")
    if maint_value(dane) != DANE_MAINT:
        fail("en-US + Dane: generator output mismatch: %r" % maint_value(dane), bad)
    elif FORBIDDEN_MAINT.search(maint_value(dane) or ""):
        fail("en-US + Dane: leftover Firefox in output", bad)
    else:
        pass_("en-US + Dane: generator output is the branded wording")

    # Synthetic leftover and missing-key cases
    leftover = run_generate(os.path.join(FIXTURES, "xx-TEST.ini"), "Dane")
    if maint_value(leftover) != DANE_MAINT or FORBIDDEN_MAINT.search(leftover.split("MozillaMaintenanceDescription=", 1)[1].splitlines()[0]):
        fail("xx-TEST + Dane did not replace the leftover Firefox wording", bad)
    else:
        pass_("xx-TEST + Dane: leftover Mozilla Firefox / Firefox line replaced")

    missing = run_generate(os.path.join(FIXTURES, "xx-MISSING.ini"), "Dane")
    if maint_value(missing) != DANE_MAINT:
        fail("xx-MISSING + Dane did not append MozillaMaintenanceDescription", bad)
    else:
        pass_("xx-MISSING + Dane: missing key was appended")

    official_missing = run_generate(os.path.join(FIXTURES, "xx-MISSING.ini"), "Firefox")
    if maint_value(official_missing) is not None:
        fail("xx-MISSING + Firefox must not invent a maintenance line", bad)
    else:
        pass_("xx-MISSING + Firefox: no maintenance line added")

    # NGD L4: CRLF input must keep CR on the replaced line.
    crlf_path = os.path.join(FIXTURES, "xx-CRLF.ini")
    crlf_raw = open(crlf_path, "rb").read()
    if b"\r\n" not in crlf_raw or b"MozillaMaintenanceDescription=" not in crlf_raw:
        fail("xx-CRLF.ini fixture is missing CRLF endings or the maintenance key", bad)
    else:
        dane_crlf = run_generate(crlf_path, "Dane")
        dane_val = (maint_value(dane_crlf) or "").rstrip("\r")
        if "\r\n" not in dane_crlf:
            fail("xx-CRLF + Dane: generator dropped CR, output has no CRLF", bad)
        elif dane_val != DANE_MAINT:
            fail("xx-CRLF + Dane: maintenance value mismatch: %r" % dane_val, bad)
        elif FORBIDDEN_MAINT.search(dane_val):
            fail("xx-CRLF + Dane: leftover Firefox in maintenance value", bad)
        else:
            pass_("xx-CRLF + Dane: MozillaMaintenanceDescription replaced and CRLF preserved")


def ftl_value(text, key):
    # Single-line Fluent messages only (these are).
    m = re.search(r"^" + re.escape(key) + r" = (.+)$", text, re.MULTILINE)
    return m.group(1) if m else None


def check_about(bad):
    brand = open(BRAND_FTL, encoding="utf-8").read()
    about = open(ABOUT_FTL, encoding="utf-8").read()
    xhtml = open(ABOUT_XHTML, encoding="utf-8").read()
    jar = open(BRAND_JAR, encoding="utf-8").read()

    for key in ("dane-community-2", "dane-community-exp"):
        val = ftl_value(brand, key)
        if not val:
            fail("brand.ftl missing %s" % key, bad)
            continue
        if EXPECTED_ATTR not in val:
            fail("%s is missing the proposed attribution / disassociation sentence" % key, bad)
        elif "Firefox ESR web browser" not in val or "Mozilla" not in val:
            fail("%s dropped Firefox or Mozilla attribution: %s" % (key, val), bad)
        elif "based on Mozilla Firefox" in val:
            fail("%s still uses the old 'based on Mozilla Firefox' phrase" % key, bad)
        else:
            pass_("brand.ftl %s has the proposed wording (Firefox ESR + disassociation)" % key)

    tm = ftl_value(brand, "trademarkInfo")
    if tm != EXPECTED_TRADEMARK:
        fail("trademarkInfo is %r, expected %r" % (tm, EXPECTED_TRADEMARK), bad)
    else:
        pass_("trademarkInfo attributes Firefox and Mozilla to Mozilla.org")

    # NGD L1: stock en-US IDs must stay upstream so an official-branding build
    # does not say "Firefox is not officially associated with Mozilla".
    expected_stock = {"community-exp": UPSTREAM_COMMUNITY_EXP, "community-2": UPSTREAM_COMMUNITY_2}
    for key, expected in expected_stock.items():
        val = ftl_value(about, key)
        if val != expected:
            fail("en-US aboutDialog.ftl %s is not the upstream ESR153 stock string: %r" % (key, val), bad)
        elif EXPECTED_ATTR in (val or ""):
            fail("en-US aboutDialog.ftl %s still carries the Dane disassociation" % key, bad)
        else:
            pass_("en-US aboutDialog.ftl %s is the upstream stock string (NGD L1)" % key)

    helpus = ftl_value(about, "helpus")
    if not helpus or "helpus-donateLink" not in helpus:
        fail("en-US aboutDialog.ftl helpus should stay the stock donate/get-involved string for official builds", bad)
    else:
        pass_("en-US aboutDialog.ftl helpus stays stock for official branding")

    dane_helpus = ftl_value(brand, "dane-helpus")
    if not dane_helpus or "helpus-getInvolvedLink" not in dane_helpus:
        fail("brand.ftl missing dane-helpus (unofficial About help line)", bad)
    elif "helpus-donateLink" in dane_helpus or "donation" in dane_helpus.lower():
        fail("brand.ftl dane-helpus still mentions a donation", bad)
    else:
        pass_("brand.ftl dane-helpus has no donate link")

    if 'branding                                          (en-US/**/*.ftl)' not in jar and "en-US/**/*.ftl" not in jar:
        fail("greatdane locales/jar.mn does not ship en-US FTL to every locale", bad)
    else:
        pass_("greatdane locales/jar.mn ships en-US branding FTL into every locale")

    # xhtml: unique IDs for non-official branding, stock IDs behind MOZ_OFFICIAL_BRANDING
    if "dane-community-2" not in xhtml or "dane-community-exp" not in xhtml:
        fail("aboutDialog.xhtml does not reference dane-community-* IDs", bad)
    elif "#ifndef MOZ_OFFICIAL_BRANDING" not in xhtml:
        fail("aboutDialog.xhtml is missing the MOZ_OFFICIAL_BRANDING gate", bad)
    else:
        # Stock IDs must still appear in the official branch.
        if "data-l10n-id=\"community-2\"" not in xhtml or "data-l10n-id=\"community-exp\"" not in xhtml:
            fail("aboutDialog.xhtml official branch dropped community-2 / community-exp", bad)
        else:
            pass_("aboutDialog.xhtml uses dane-community-* unless MOZ_OFFICIAL_BRANDING")

    # Brand names / prefs / bundle ID must not have been edited in these files.
    for token, label in (
        ("-brand-short-name = Dane", "brand short name"),
        ("-vendor-short-name = Dane", "vendor short name"),
    ):
        if token not in brand:
            fail("brand.ftl lost %s" % label, bad)
        else:
            pass_("brand.ftl keeps %s" % label)


def check_l10n_pin(bad):
    """NGD L3: fixtures are pinned to the ESR153 l10n-changesets revision."""
    if not os.path.isfile(L10N_CHANGESETS):
        print("SKIP l10n-changesets.json is not in this tree; expected pin is %s" % ESR153_L10N_REVISION)
        return
    import json

    data = json.loads(open(L10N_CHANGESETS, encoding="utf-8").read())
    missing = [loc for loc in L10N_FIXTURES if loc not in data]
    if missing:
        fail("l10n-changesets.json is missing fixture locale(s): " + ", ".join(missing), bad)
        return
    revisions = {loc: data[loc].get("revision") for loc in L10N_FIXTURES}
    unexpected = {loc: rev for loc, rev in revisions.items() if rev != ESR153_L10N_REVISION}
    if unexpected:
        fail("fixture locale revisions are not the ESR153 pin %s: %s" % (ESR153_L10N_REVISION, unexpected), bad)
    else:
        pass_(
            "l10n fixtures de/fr/ja/zh-CN/en-GB/ar are pinned to ESR153 revision %s"
            % ESR153_L10N_REVISION
        )

    checkout = os.environ.get("GREATDANE_L10N_CHECKOUT")
    if not checkout:
        print(
            "SKIP no GREATDANE_L10N_CHECKOUT; not iterating a live l10n tree "
            "(fixtures are pinned to %s)" % ESR153_L10N_REVISION
        )
        return
    if not os.path.isdir(checkout):
        fail("GREATDANE_L10N_CHECKOUT is set but not a directory: %s" % checkout, bad)
        return
    replaced = 0
    appended = 0
    missing_ini = 0
    leftover = []
    for loc, meta in sorted(data.items()):
        ini = os.path.join(checkout, loc, "browser", "updater", "updater.ini")
        if not os.path.isfile(ini):
            missing_ini += 1
            continue
        raw_val = maint_value(open(ini, encoding="utf-8").read())
        dane = run_generate(ini, "Dane")
        official = run_generate(ini, "Firefox")
        dane_val = maint_value(dane)
        if dane_val != DANE_MAINT or FORBIDDEN_MAINT.search(dane_val or ""):
            leftover.append(loc)
            continue
        if raw_val is None:
            appended += 1
        else:
            replaced += 1
        if maint_value(official) != raw_val:
            leftover.append(loc + " (official changed)")
    if leftover:
        fail("l10n checkout: unexpected maintenance output for: " + ", ".join(leftover[:20]), bad)
    else:
        pass_(
            "l10n checkout %s: %d replaced, %d appended, %d with no updater.ini, 0 leftovers"
            % (checkout, replaced, appended, missing_ini)
        )


def main():
    bad = []
    print("locale_branding_check: root %s" % ROOT)
    check_locale_lists(bad)
    check_en_us_source(bad)
    check_fixtures(bad)
    check_l10n_pin(bad)
    check_about(bad)
    print()
    if bad:
        print("%d FAIL(s)" % len(bad))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
