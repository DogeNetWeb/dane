# Dane test harness
All scripts import `greatdane/tools/gd_guard.py` first: it aborts if nowon's real
GreatDANE profiles.ini/installs.ini change, and gives throwaway profile/node-data dirs.
Run with the marionette venv, e.g.
`/Volumes/Storage/build/greatdane/mn-venv/bin/python smoke.py <Dane.app/Contents/MacOS/greatdane> arm64`

media_check.py: `media_check.py <greatdane> <arm64|x86_64> [h264file,h264,cleartears,google-tears-uat,shaka-angel-one,...]`.
Run the app from a path under /Volumes or /Applications, not /tmp: from a /tmp (symlink to /private/tmp)
mount the Widevine CDM process fails to launch ("GMPServiceChild failed to launch GMP: Process has not loaded").

ids_search_check.py: `ids_search_check.py <greatdane> <arm64|x86_64> (--expected BUILDID | --buildinfo BUILDINFO-<id>.txt)`.
The expected BuildID never comes from the app itself. Checks application.ini == platform.ini == appinfo == expected, and that every child process's -parentBuildID == expected.
run_gd_prefs.py: `run_gd_prefs.py <greatdane> [arm64|x86_64] [/abs/screens_dir]`. Without an arch it runs natively. Before this change, a second argument was taken as the screens dir.
guard_negative_test.py: proves gd_guard rejects out-of-root dataDir and safe() paths and stray dirs in the source tree. Launches no browser.
gd_guard now requires every profile and node data path to be inside this run's mkdtemp roots. At exit, it fails with code 96 if a profile's dataDir is outside them, or if new dirs appeared in greatdane/, the cwd, or $HOME.
passkey_check.py: `passkey_check.py <Dane.app> <arm64|x86_64> [--static-only]`. Passkey READINESS check (PASSKEYS-PLAN.md §5). A pass is not proof that passkeys work: it only shows there are no stray restricted entitlements, the pref is on and the generic WebAuthn API exists. Static: with no Contents/embedded.provisionprofile, no Mach-O may carry com.apple.developer.web-browser.public-key-credential or com.apple.application-identifier. With a profile, only the main app may carry both (MNL79V994R.surf.dogecoin.dane), and the profile must grant them. Runtime (gd_guard throwaway profile, ABI gate, free Marionette port picked at run time, child killed if it does not quit in 30s): security.webauthn.enable_macos_passkeys is true and PublicKeyCredential exists. The runtime part makes one network request, to https://example.com/ (needed for a secure context). Read-only on the bundle; changes no signing inputs.
