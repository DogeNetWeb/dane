# Dane test harness
All scripts import `greatdane/tools/gd_guard.py` first: it aborts if nowon's real
GreatDANE profiles.ini/installs.ini change, and gives throwaway profile/node-data dirs.
Run with the marionette venv, e.g.
`/Volumes/Storage/build/greatdane/mn-venv/bin/python smoke.py <Dane.app/Contents/MacOS/greatdane> arm64`
