#!/usr/bin/env python3
"""Fail if a non-excluded dogecoin.surf or pepecoin.surf reference remains
in Dane product files.

Run from the source tree root:
  python3 greatdane/tests/no_coin_surf_product_urls_check.py

Round 5a retargeted Dane product URLs and the default top-site tiles to
dane.surf. Round 5b (NGD 5A-L3) scans the whole tree (not a fixed list of
product roots), treats .svg as text, fails loudly on files over 2 MB
instead of skipping them, and when an author-email allowance matches,
strips only the email and re-tests the rest of the line.

The following are intentionally left alone and must stay on the
exclusion list:

- DogeNet/PepeNet protocol, node, or .doge/.pepe names (including the
  greatdane.doge tile and greatdane.doge.* prefs)
- Node seeds and bootstrap hosts (e.g. seed.dogecoin.surf,
  seed.pepecoin.surf in embedded node sources, if those files are present)
- PepeNet desktop APP_RELEASES_URL (https://pepecoin.surf/releases)
- Publisher-check fixtures under greatdane/tests/fixtures/pepecoin-publisher/
- Patch/commit author emails (nowon@noreply.pepecoin.surf) — the email
  token only, not the rest of the line
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
# Author-email token only (5A-L3 a): strip the match and re-test the rest
# of the line. A URL on the same line is not hidden by the email.
AUTHOR_EMAIL_RE = re.compile(r"nowon@noreply\.pepecoin\.surf")

# Allowed leftover host/URL tokens in a full tree (still re-test the rest
# of the line after they are stripped). These are not product URLs.
ALLOWED_TOKEN_RES = (
    re.compile(r"(?i)(?<![\w.-])seed\.dogecoin\.surf(?![\w.-])"),
    re.compile(r"(?i)(?<![\w.-])seed\.pepecoin\.surf(?![\w.-])"),
    re.compile(r"(?i)https://pepecoin\.surf/releases/?"),
)

SKIP_DIR_NAMES = {
    ".git", "__pycache__", "node_modules",
    "obj-gd-win64", "obj-gd-linux64", "obj-firefox", "objdir", "obj-gd",
}

# Binary / non-text suffixes. .svg is text and is scanned (5A-L3 b).
# Filenames like pepecoin-surf.png do not contain a "pepecoin.surf" token;
# skip raster/binaries anyway.
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".webp",
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
    """Walk the whole tree (5A-L3 d), including top-level files."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        # Drop excluded directories early (and known skip names).
        keep = []
        for d in dirnames:
            if d in SKIP_DIR_NAMES:
                continue
            child = (d if not rel_dir else rel_dir + "/" + d) + "/"
            if excluded_path(child) or excluded_path(child.rstrip("/")):
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            yield rel, path


def line_without_allowances(line: str) -> str:
    """Strip author-email and allowed leftover tokens, keep the rest."""
    rest = AUTHOR_EMAIL_RE.sub("", line)
    for tok in ALLOWED_TOKEN_RES:
        rest = tok.sub("", rest)
    return rest


def main() -> int:
    hits = []
    scanned = 0
    oversized = []
    for rel, path in iter_files():
        if excluded_path(rel):
            continue
        if is_binary(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError as exc:
            print("FAIL could not stat", rel, exc)
            return 1
        if size > TEXT_BYTES:
            oversized.append((rel, size))
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError as exc:
            print("FAIL could not read", rel, exc)
            return 1
        scanned += 1
        for i, line in enumerate(text.splitlines(), 1):
            if not PATTERN.search(line):
                continue
            rest = line_without_allowances(line)
            if not PATTERN.search(rest):
                continue
            hits.append((rel, i, line.strip()[:200]))
    if oversized:
        print("FAIL %d file(s) over %d bytes; not skipped, cannot attest they are clean:"
              % (len(oversized), TEXT_BYTES))
        for rel, size in oversized:
            print("  %s: %d bytes" % (rel, size))
        return 1
    if hits:
        print("FAIL %d non-excluded dogecoin.surf/pepecoin.surf reference(s):" % len(hits))
        for rel, i, line in hits:
            print("  %s:%d: %s" % (rel, i, line))
        return 1
    print("PASS no non-excluded dogecoin.surf/pepecoin.surf references (%d files scanned)" % scanned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
