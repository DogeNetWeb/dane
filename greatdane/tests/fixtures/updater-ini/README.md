# updater.ini fixtures for locale_branding_check.py

Pinned to the 153.7.0esr `browser/locales/l10n-changesets.json` revision

    4e2e25a0b94740a84c357e93346ec4f4c94521e3

(mozilla-l10n/firefox-l10n). Every locale in that changesets file records this
same revision. The six real fixtures were fetched over public HTTPS from

    https://raw.githubusercontent.com/mozilla-l10n/firefox-l10n/4e2e25a0b94740a84c357e93346ec4f4c94521e3/<locale>/browser/updater/updater.ini

on 2026-11-10, America/Chicago (UTC-6). The six files are byte-identical to
the previous 4f pin at 3ae91662ee285b44f21ef31b9cae722d132e28ea and to the
copies previously taken from firefox-l10n `main` the same day. The pin is
the 153.7.0esr l10n-changesets revision (full SHA above), not `main`. Licensed under MPL 2.0,
same as the upstream files. They are test inputs only; they are not shipped in
the product.

xx-TEST.ini and xx-MISSING.ini are synthetic cases (a leftover "Mozilla Firefox"
line, and a file with no MozillaMaintenanceDescription key).
The NGD L4 CRLF case is synthesized at runtime from xx-TEST.ini so a checked-in
CRLF fixture cannot be flattened by format-patch / git-am.

If a real firefox-l10n checkout at this revision is available, set
`GREATDANE_L10N_CHECKOUT` to its root and `locale_branding_check.py` will
iterate every locale that has `browser/updater/updater.ini`.
