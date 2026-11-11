; G7: !tempfile (not on the allowlist). The !appendfile would write the
; sentinel if makensis ran.
!tempfile FOO
!appendfile "/tmp/dane-4l-tempfile-sentinel" "x"
!define CompanyName "Dane"
!define ARPPublisher "Dane"
