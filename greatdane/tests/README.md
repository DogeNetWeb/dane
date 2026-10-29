# Dane test harness
All scripts import `greatdane/tools/gd_guard.py` first: it aborts if nowon's real
GreatDANE profiles.ini/installs.ini change, and gives throwaway profile/node-data dirs.
Run with the marionette venv, e.g.
`/Volumes/Storage/build/greatdane/mn-venv/bin/python smoke.py <Dane.app/Contents/MacOS/greatdane> arm64`

media_check.py: `media_check.py <greatdane> <arm64|x86_64> [h264file,h264,cleartears,google-tears-uat,shaka-angel-one,...]`.
Run the app from a path under /Volumes or /Applications, not /tmp: from a /tmp (symlink to /private/tmp)
mount the Widevine CDM process fails to launch ("GMPServiceChild failed to launch GMP: Process has not loaded").
