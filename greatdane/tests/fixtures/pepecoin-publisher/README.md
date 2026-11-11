# Pepecoin publisher check fixtures (rounds 4i and 4j)

Negative test cases for `trademark_userfacing_check.py` / `pepecoin_publisher.py`.
They are not shipped in the product. Each fixture must be rejected. The real
tree must pass.

Round 4j resolves values with real tools (`makensis -PPO` for NSIS,
vendored `create_rc.parse_module_ver` for module.ver) and then normalizes
(NFKC, casefold, Cyrillic/Greek/Latin-accent lookalikes, drop zero-width
and non-letters) before matching.

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
