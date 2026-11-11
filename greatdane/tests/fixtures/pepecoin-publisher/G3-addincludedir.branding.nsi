; G3: !addincludedir of an absolute dir, then !include x.nsh.
; If makensis ran this it would write /tmp/dane-4l-g3-sentinel.
!addincludedir /tmp/dane-4l-g3-inc
!include "x.nsh"
!define CompanyName "Dane"
!define ARPPublisher "Dane"
