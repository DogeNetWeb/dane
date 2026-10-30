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
