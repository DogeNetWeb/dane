#!/usr/bin/env python3
"""Resolve and normalize Windows publisher/company values for the 4j check.

This is test tooling only. It is not shipped in the product.

NSIS values are taken from `makensis -PPO` on a tiny wrapper that !includes
the branding file and echoes ${CompanyName} and ${ARPPublisher}. If makensis
is missing, callers must SKIP or FAIL — never PASS.

module.ver values use a vendored copy of the parse/preprocess logic from
Firefox ESR 153.7.0 `config/create_rc.py` (preprocess at lines 79–87,
parse_module_ver at lines 89–97). That file is not in this snapshot (it
imports buildconfig), so the marker-% substitution, %define, %include, and
`#` comment split are reproduced here and cited below. If `config/create_rc.py`
is later present and importable, it is preferred.

Values are normalized before matching: NFKC, casefold, Cyrillic/Greek (and
common Latin-accent) lookalikes mapped to Latin, then zero-width and
non-letter characters stripped (NGD 4i L6/L7). A publisher/company value
that contains "pepecoin" or "mozilla" after that fold is a failure (L8).
The official shared.nsh Publisher "Mozilla" fallback is the exception, and
applies only when ARPPublisher is undefined.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

# Letters in "pepecoin" / "mozilla" and close confusables. Keys are
# already-casefolded where possible; lookup uses casefold(ch).
_LOOKALIKE = {
    # Cyrillic
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ї": "i",
    "ј": "j",
    "ѕ": "s",
    "һ": "h",
    "ӏ": "l",
    "м": "m",
    "п": "n",  # visually a shako; used cautiously
    "л": "l",
    "ｚ": "z",
    # Greek
    "α": "a",
    "ε": "e",
    "ο": "o",
    "ρ": "p",
    "ι": "i",
    "ν": "v",
    "η": "n",
    "χ": "x",
    "κ": "k",
    "μ": "m",
    "ѕ": "s",
    # Latin accented (N16); also covered if we drop combining marks after NFKD
    "é": "e",
    "è": "e",
    "ê": "e",
    "ë": "e",
    "ę": "e",
    "ė": "e",
    "ē": "e",
    "á": "a",
    "à": "a",
    "â": "a",
    "ä": "a",
    "ã": "a",
    "å": "a",
    "ī": "i",
    "í": "i",
    "ì": "i",
    "î": "i",
    "ï": "i",
    "ó": "o",
    "ò": "o",
    "ô": "o",
    "ö": "o",
    "õ": "o",
    "ø": "o",
    "ú": "u",
    "ù": "u",
    "û": "u",
    "ü": "u",
    "ý": "y",
    "ç": "c",
    "ñ": "n",
}


class MakensisMissing(Exception):
    """makensis is not on PATH."""


class MakensisError(Exception):
    """makensis -PPO failed."""


def makensis_path():
    return shutil.which("makensis")


def makensis_version():
    path = makensis_path()
    if not path:
        return None
    r = subprocess.run([path, "-VERSION"], capture_output=True, text=True)
    return (r.stdout or r.stderr or "").strip() or None


def normalize_publisher(value):
    """NFKC, casefold, lookalike fold, then drop zero-width and non-letters."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = s.casefold()
    s = "".join(_LOOKALIKE.get(ch, ch) for ch in s)
    # Drop combining marks so a leftover acute (or NFKC-stable é already mapped)
    # cannot keep a decorated letter in the string.
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            out.append(ch)
        # Cf/Cc/Zs/Pd and other non-letters (zero-width, spaces, hyphens) dropped
    return "".join(out)


def mentions_pepecoin(value):
    return "pepecoin" in normalize_publisher(value)


def mentions_mozilla(value):
    return "mozilla" in normalize_publisher(value)


def is_empty_or_mozilla_publisher(value):
    """True if missing, empty, or the publisher contains 'mozilla' (L8)."""
    if value is None:
        return True
    if str(value).strip() == "":
        return True
    # Unresolved NSIS ${Name} means the symbol was not defined.
    s = str(value).strip()
    if s.startswith("${") and s.endswith("}") and s[2:-1].isidentifier():
        return True
    return mentions_mozilla(s)


# ---------------------------------------------------------------------------
# module.ver: vendored from Firefox ESR 153.7.0 config/create_rc.py
# preprocess(): lines 79–87 (Preprocessor marker="%", substitution filter)
# parse_module_ver(): lines 89–97 (split # comments, key=value)
# ---------------------------------------------------------------------------

_AT_SUBST = re.compile(r"@(\w+)@")


def _expand_at(text, defines):
    def repl(m):
        key = m.group(1)
        if key in defines:
            return str(defines[key])
        return m.group(0)

    return _AT_SUBST.sub(repl, text)


def _preprocess_module_ver(path, defines):
    """Marker-% preprocess: %define, %include, @KEY@ substitution.

    Mirrors create_rc.preprocess (marker '%', substitution filter). Input
    encoding is latin1, as in create_rc.py.
    """
    defines = dict(defines)
    path = os.fspath(path)
    out_lines = []
    with open(path, encoding="latin1") as fh:
        for line in fh:
            stripped = line.lstrip()
            if stripped.startswith("%define"):
                rest = stripped[len("%define") :].strip()
                name, _, val = rest.partition(" ")
                if name:
                    defines[name] = _expand_at(val.strip(), defines)
                continue
            if stripped.startswith("%include"):
                inc = stripped[len("%include") :].strip().strip('"').strip("'")
                inc_path = inc if os.path.isabs(inc) else os.path.join(os.path.dirname(path), inc)
                out_lines.extend(_preprocess_module_ver(inc_path, defines))
                continue
            if stripped.startswith("%"):
                # Other % directives are not copied into parse_module_ver output
                # once consumed by the preprocessor (same as mozbuild).
                continue
            out_lines.append(_expand_at(line, defines))
    return out_lines, defines


def parse_module_ver(path, defines=None):
    """Parse a module.ver the way create_rc.parse_module_ver does.

    Tries config/create_rc.py in the same tree if it can be imported; otherwise
    uses the vendored logic cited above.
    """
    defines = dict(defines or {})
    tree_create_rc = None
    # Walk up from the given file to a source root that has config/create_rc.py
    cur = os.path.abspath(os.path.dirname(os.fspath(path)))
    for _ in range(8):
        candidate = os.path.join(cur, "config", "create_rc.py")
        if os.path.isfile(candidate):
            tree_create_rc = candidate
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    if tree_create_rc:
        try:
            import importlib.util

            spec = importlib.util.spec_from_file_location("_dane_create_rc", tree_create_rc)
            mod = importlib.util.module_from_spec(spec)
            # create_rc imports buildconfig at module level; this will usually fail
            # in the snapshot. Fall through to the vendored copy.
            spec.loader.exec_module(mod)
            return mod.parse_module_ver(path, defines)
        except Exception:
            pass
    result = {}
    lines, _defs = _preprocess_module_ver(path, defines)
    for line in lines:
        content, *_comment = line.split("#", 1)
        if not content.strip():
            continue
        if "=" not in content:
            continue
        entry, value = content.split("=", 1)
        result[entry.strip()] = value.strip()
    return result


def module_ver_company(path):
    parsed = parse_module_ver(path)
    if "WIN32_MODULE_COMPANYNAME" not in parsed:
        return None
    return parsed["WIN32_MODULE_COMPANYNAME"]


def module_ver_copyright(path):
    parsed = parse_module_ver(path)
    return parsed.get("WIN32_MODULE_COPYRIGHT")


# ---------------------------------------------------------------------------
# NSIS: makensis -PPO
# ---------------------------------------------------------------------------

_PPO_COMPANY = re.compile(r'^!echo "PPO_CompanyName=(.*)"\s*$')
_PPO_ARP = re.compile(r'^!echo "PPO_ARPPublisher=(.*)"\s*$')


def resolve_branding_nsi(branding_path):
    """Return (company, arp_publisher, ppo_stdout) from makensis -PPO.

    The wrapper !includes the branding file and echoes the two symbols.
    Sidecar files in the same directory (!include, /file) are available.
    """
    path = makensis_path()
    if not path:
        raise MakensisMissing(
            "makensis is not on PATH; the publisher check cannot resolve NSIS values"
        )
    branding_path = Path(branding_path).resolve()
    if not branding_path.is_file():
        raise MakensisError("branding file not found: %s" % branding_path)
    with tempfile.TemporaryDirectory(prefix="dane-ppo-") as td:
        td = Path(td)
        for sib in branding_path.parent.iterdir():
            if sib.is_file():
                shutil.copy2(sib, td / sib.name)
        if branding_path.name != "branding.nsi":
            shutil.copy2(branding_path, td / "branding.nsi")
        wrapper = td / "wrapper.nsi"
        wrapper.write_text(
            '!include "branding.nsi"\n'
            '!echo "PPO_CompanyName=${CompanyName}"\n'
            '!echo "PPO_ARPPublisher=${ARPPublisher}"\n',
            encoding="utf-8",
        )
        try:
            r = subprocess.run(
                [path, "-PPO", "-INPUTCHARSET", "UTF8", str(wrapper)],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as exc:
            raise MakensisError("makensis -PPO timed out") from exc
        if r.returncode != 0:
            raise MakensisError(
                "makensis -PPO rc=%s stderr=%s stdout=%s"
                % (r.returncode, (r.stderr or "")[-500:], (r.stdout or "")[-500:])
            )
        company = arp = None
        for line in r.stdout.splitlines():
            m = _PPO_COMPANY.match(line)
            if m:
                company = m.group(1)
            m = _PPO_ARP.match(line)
            if m:
                arp = m.group(1)
        return company, arp, r.stdout


def _unresolved(value):
    if value is None:
        return True
    s = str(value).strip()
    return s.startswith("${") and s.endswith("}") and s[2:-1].isidentifier()


def branding_publisher_values(branding_path):
    company, arp, _stdout = resolve_branding_nsi(branding_path)
    if _unresolved(company):
        company = None
    if _unresolved(arp):
        arp = None
    return company, arp


def manifest_has_pepecoin(path):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return mentions_pepecoin(text)


def shared_nsh_has_pepecoin(path):
    text = Path(path).read_text(encoding="utf-8")
    return mentions_pepecoin(text)
