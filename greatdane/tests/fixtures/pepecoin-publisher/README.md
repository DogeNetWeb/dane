# Pepecoin publisher check fixtures (rounds 4i and 4j)

Negative test cases for `trademark_userfacing_check.py` / `pepecoin_publisher.py`.
They are not shipped in the product. Each fixture must be rejected. The real
tree must pass.

Round 4j resolved values with `makensis -PPO` and a module.ver parser.
Round 4k keeps that, but the module.ver parser is a reimplementation (not
a vendored copy): it FAILs on any % directive other than %define/%include
and on an undefined @X@ in company or copyright. makensis is refused if
the include set contains compile-time command such as !system or
!appendfile, or if branding.nsi contains !if*. Publisher values must be
printable ASCII after resolution. Normalization (NFKC, casefold,
lookalikes, drop zero-width and non-letters) is unchanged, except the
wrong п→n map was removed.

| File | Case | Must fail because |
|---|---|---|
| A.module.ver | 4h/4i `WIN32_MODULE_COMPANYNAME=Pepecoin # MOZ_APP_VENDOR` | Pepecoin company |
| A2.module.ver | 4h/4i `© Pepecoin (MOZ_APP_VENDOR)` | Pepecoin copyright |
| C.branding.nsi | 4h/4i `!define CompanyName "Pepecoin" ; MOZ_APP_VENDOR` | Pepecoin company |
| E.branding.nsi | 4h/4i `PUB` + `${PUB}` | resolved ARPPublisher is Pepecoin |
| D2.branding.nsi | 4h/4i continued CompanyName using pepecoin.surf | makensis value contains pepecoin |
| empty-company.module.ver | empty `WIN32_MODULE_COMPANYNAME` | company must be non-empty and not contain mozilla |
| arp-mozilla.branding.nsi | `ARPPublisher "Mozilla"` | unofficial publisher must not contain mozilla |
| L1-N11-Uplus.branding.nsi | L1 / N11/N23 `Pepe${U+63}oin` | makensis yields Pepecoin |
| L2-N20-redef.branding.nsi | L2 / N20 `!define /redef` | later redef is Pepecoin |
| L3-N21-searchreplace.branding.nsi | L3 / N21 `!undef` + `!searchreplace` | makensis yields Pepecoin |
| L4-N22-file/ | L4 / N22 `!undef` + `!define /file` | file content is Pepecoin |
| L5-N5-ifndef.branding.nsi | L5 / N5 `/ifndef` concat | `${PA}${PB}` is Pepecoin |
| L5-N6-indented.branding.nsi | L5 / N6 indented `!define` | `${PA}coin` is Pepecoin |
| L5-N9b-include/ | L5 / N9b `!include` | included define concatenates to Pepecoin |
| L5-N14-define.module.ver | L5 / N14 `%define PB coin` + `Pepe@PB@` | parse_module_ver yields Pepecoin |
| L6-N1-cyrillic.branding.nsi | L6 / N1 Cyrillic е | lookalike fold is pepecoin |
| L6-N16-acute.branding.nsi | L6 / N16 Latin é | lookalike fold is pepecoin |
| L7-N2-zwsp.branding.nsi | L7 / N2 zero-width | zero-width stripped, pepecoin remains |
| L7-N3-hyphen.branding.nsi | L7 / N3 `Pepe-coin` | non-letters stripped |
| L7-N4-spaces.branding.nsi | L7 / N4 spaced letters | non-letters stripped |
| L8-mozilla-foundation.branding.nsi | L8 Mozilla Foundation | publisher contains mozilla |
| L8-mozilla-corporation.branding.nsi | L8 Mozilla Corporation | publisher contains mozilla |

The official `shared.nsh` Publisher `"Mozilla"` fallback is not a fixture:
it applies only when `ARPPublisher` is undefined, and it stays.

| F1-if.module.ver | F1 `%if` / `%else` / `%endif` | forbidden % directive |
| F1-undefined-at.module.ver | F1 `Pepe@NOPE@` | undefined @X@ in company |
| F2-system.branding.nsi | F2 `!system` touching `/tmp/dane-4k-f2-system-sentinel` | refused before makensis; sentinel must not be created |
| F2-appendfile.branding.nsi | F2 `!appendfile` to `/tmp/dane-4k-f2-appendfile-sentinel` | refused before makensis; sentinel must not be created |
| F3-ifdef.branding.nsi | F3 `!ifdef` in branding.nsi | refused (!if*) |
| F4-non-ascii.branding.nsi | F4 Armenian օ in CompanyName | not printable ASCII after resolution |


Round 4l replaces the NSIS command denylist with an allowlist. Logical
lines (backslash continuations joined first) of branding.nsi and its
includes must be blank, a comment, a simple `!define NAME value`, or a
relative sibling `!include` with no wildcard and no `..`. Anything else
fails, including a line starting with `${`. module.ver parsing still
prefers the ESR Preprocessor (hash of the file actually imported) and
falls back to the minimal reimplementation.

| File | Case | Must fail because |
|---|---|---|
| G2-abs-include.branding.nsi | G2 absolute-path `!include` | not a relative sibling; `/tmp/dane-4l-g2-sentinel` must not be created |
| G3-addincludedir.branding.nsi | G3 `!addincludedir` then `!include` | `!addincludedir` is not on the allowlist; `/tmp/dane-4l-g3-sentinel` must not be created |
| G4-continuation.branding.nsi | G4 `!sys\` / `tem` | joined line is `!system`, not on the allowlist; `/tmp/dane-4l-g4-sentinel` must not be created |
| G5-expanded-command.branding.nsi | G5 `!define C "!system"` then `${C}` | a line starting with `${` is not on the allowlist; `/tmp/dane-4l-g5-sentinel` must not be created |
| G10-wildcard-include.branding.nsi | G10 wildcard `!include` | wildcard / absolute include refused; `/tmp/dane-4l-g10-sentinel` must not be created |
| G7-tempfile.branding.nsi | `!tempfile` | not on the allowlist; `/tmp/dane-4l-tempfile-sentinel` must not be created |
