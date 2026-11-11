# Pepecoin publisher check fixtures (round 4i)

Negative test cases for `trademark_userfacing_check.py`. They are not shipped
in the product. Each fixture must be rejected (FAIL if used as a publisher
file). The real tree must PASS.

| File | NGD case | Must fail because |
|---|---|---|
| A.module.ver | `WIN32_MODULE_COMPANYNAME=Pepecoin # MOZ_APP_VENDOR` | Pepecoin company, comment must not exempt |
| A2.module.ver | `© Pepecoin (MOZ_APP_VENDOR)` | Pepecoin copyright, token in parentheses must not exempt |
| C.branding.nsi | `!define CompanyName "Pepecoin" ; MOZ_APP_VENDOR` | Pepecoin company, NSIS comment must not exempt |
| E.branding.nsi | `!define PUB "Pepecoin" ; HKCU\Software` then `ARPPublisher "${PUB}"` | resolved publisher is Pepecoin; path comment must not exempt |
| D2.branding.nsi | line-continued CompanyName using pepecoin.surf | continuations are joined; hostname is the company value |
| empty-company.module.ver | empty `WIN32_MODULE_COMPANYNAME` | company must be non-empty and not Mozilla |
| arp-mozilla.branding.nsi | `ARPPublisher "Mozilla"` | unofficial publisher must be non-empty and not Mozilla |
