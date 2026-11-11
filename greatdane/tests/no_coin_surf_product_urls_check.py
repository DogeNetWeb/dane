#!/usr/bin/env python3
"""Fail if a non-excluded dogecoin.surf or pepecoin.surf reference remains
in Dane product files.

Run from the source tree root:
  python3 greatdane/tests/no_coin_surf_product_urls_check.py

Round 5a retargeted Dane product URLs and the default top-site tiles to
dane.surf. The following are intentionally left alone and must stay on
the exclusion list:

- DogeNet/PepeNet protocol, node, or .doge/.pepe names (including the
  greatdane.doge tile and greatdane.doge.* prefs)
- Node seeds and bootstrap hosts (e.g. seed.dogecoin.surf,
  seed.pepecoin.surf in embedded node sources, if those files are present)
- PepeNet desktop APP_RELEASES_URL (https://pepecoin.surf/releases)
- Publisher-check fixtures under greatdane/tests/fixtures/pepecoin-publisher/
- Patch/commit author emails (nowon@noreply.pepecoin.surf)
- Historical evidence/ and dated notes (not product files)
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PATTERN = re.compile(r"(?i)(dogecoin|pepecoin)\.surf")

# Explicit exclusion list (paths relative to the tree root).
# A directory prefix excludes every file under it.
EXCLUDE_PREFIXES = (
    "greatdane/tests/fixtures/pepecoin-publisher/",
    "evidence/",
)
# Exact files (if a leftover note has to live next to product code).
EXCLUDE_FILES = (
    # This check names the leftover hosts in its own comments and messages.
    "greatdane/tests/no_coin_surf_product_urls_check.py",
)
# Line-level allowances in otherwise-scanned files (author email only).
EXCLUDE_LINE_RES = (
    re.compile(r"nowon@noreply\.pepecoin\.surf"),
)

# Product roots scanned when present. .git and other trees are skipped.
SCAN_ROOTS = (
    "browser",
    "build",
    "greatdane",
    "security",
    "taskcluster",
    "toolkit",
    "xpcom",
    "modules",
)

SKIP_DIR_NAMES = {".git", "__pycache__", "node_modules", "obj-gd-win64", "obj-gd-linux64"}
# Binary / non-text suffixes. Filenames like pepecoin-surf.png do not contain
# a "pepecoin.surf" token; skip binaries anyway.
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".webp", ".svg",
    ".bmp", ".pdf", ".zip", ".gz", ".bz2", ".xz", ".7z", ".woff", ".woff2",
    ".ttf", ".otf", ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".pyc",
    ".class", ".jar", ".wasm",
}

TEXT_BYTES = 2 * 1024 * 1024


def excluded_path(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel in EXCLUDE_FILES:
        return True
    for pfx in EXCLUDE_PREFIXES:
        if rel == pfx.rstrip("/") or rel.startswith(pfx):
            return True
    return False


def is_binary(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in BINARY_SUFFIXES:
        return True
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
    except OSError:
        return True
    return b"\0" in chunk


def iter_files():
    for root_name in SCAN_ROOTS:
        base = os.path.join(ROOT, root_name)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for name in filenames:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, ROOT).replace("\\", "/")
                yield rel, path


def main() -> int:
    hits = []
    scanned = 0
    for rel, path in iter_files():
        if excluded_path(rel):
            continue
        if is_binary(path):
            continue
        try:
            if os.path.getsize(path) > TEXT_BYTES:
                continue
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print("FAIL could not read", rel, exc)
            return 1
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if not PATTERN.search(line):
                continue
            if any(r.search(line) for r in EXCLUDE_LINE_RES):
                continue
            hits.append((rel, i, line.strip()[:200]))
    if hits:
        print("FAIL %d non-excluded dogecoin.surf/pepecoin.surf reference(s):" % len(hits))
        for rel, i, line in hits:
            print("  %s:%d: %s" % (rel, i, line))
        return 1
    print("PASS no non-excluded dogecoin.surf/pepecoin.surf references (%d files scanned)" % scanned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
