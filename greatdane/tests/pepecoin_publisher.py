#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Resolve and normalize Windows publisher/company values (round 4k).

This is test tooling only. It is not shipped in the product.

NSIS values come from makensis -PPO on a tiny wrapper that sets
`Unicode true`, mirrors installer.nsi's pre-branding defines
(NO_STARTMENU_DIR, NONADMIN_ELEVATE, and AbortSurveyURL with the
stock kampyle URL), !includes the branding file, and echoes
${CompanyName} and ${ARPPublisher}. The binary is chosen in this
order: $MAKENSISU, then ~/.mozbuild/nsis/bin/makensis (the
bootstrapped build tool), then PATH as a labelled fallback. If
makensis is missing, callers must FAIL — never PASS. This is not a
full build-environment mirror (AB_CD, Manifest*, FileFunc and the
rest of installer.nsi stay unset).

Before makensis is invoked, every logical line of branding.nsi and of
the files it includes must be blank, a comment, a simple `!define NAME
value` (optional quoted value; no flags such as /redef or /file), or an
`!include` of a relative sibling with no wildcard and no `..`. Anything
else, including a line starting with `${`, is refused. A trailing backslash is a continuation only after
stripping ASCII space, tab, and CR (not other Unicode whitespace).
Any line that contains NUL, a C0 control other than tab, or
non-ASCII whitespace is refused, so a comment that ends in a
backslash plus a Unicode space, or a NUL before the backslash,
cannot hide the next line from the checker.

module.ver is parsed with mozbuild.preprocessor.Preprocessor
(marker='%') from pre-release esr153 snapshot 3bd39ccf6a when that package is
importable (this box: /workspace/dane-windows/firefox-esr153/python/mozbuild;
preprocessor.py sha256 378dcc667104271a22eedd58cba175fa35debeb29b431f022ac39ef879b25166,
which is the 3bd39ccf6a file and also matches FIREFOX_153_7_0esr_RELEASE 9aecd40e),
then the small create_rc.parse_module_ver loop (config/create_rc.py
lines 89–97). Import order: $DANE_ESR_MOZBUILD (the python/mozbuild directory)
if set, then a mozbuild already on sys.path, then the boxed
/workspace/dane-windows/firefox-esr153/python/mozbuild. If the import
fails, a minimal
reimplementation is used that only allows %define and %include; any
other % directive is a failure. Either way, an undefined @X@ in a
company or copyright value is a failure. MOZ_APP_WINVERSION,
MOZ_APP_VERSION, and MOZ_APP_DISPLAYNAME are pre-defined as
placeholders so the snapshot module.ver (which still carries those
build substitutions on non-company keys) can be parsed; any other
undefined @X@ still fails. This helper is not a vendored copy of
the preprocessor when the fallback path is in use.

Values are normalized before matching: NFKC, casefold, Cyrillic/Greek
(and common Latin-accent) lookalikes mapped to Latin, then zero-width
and non-letter characters stripped. A company or publisher value must
also be printable ASCII after resolution. A value that contains
"pepecoin" or "mozilla" after the fold is a failure. The official
shared.nsh Publisher "Mozilla" fallback is the exception, and applies
only when ARPPublisher is undefined.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

# Letters in "pepecoin" / "mozilla" and close confusables. Keys are
# already-casefolded where possible.
_LOOKALIKE = {
    # Cyrillic (no "п"→"n": that map was wrong)
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
    # Latin accented
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

# Sentinels used by the F2 (4k) and G2–G10 / tempfile (4l) fixtures.
# The check must refuse those fixtures and must not create these paths.
# Bypass fixtures that could run commands only touch /tmp sentinels.
F2_SYSTEM_SENTINEL = "/tmp/dane-4k-f2-system-sentinel"
F2_APPENDFILE_SENTINEL = "/tmp/dane-4k-f2-appendfile-sentinel"
G2_SENTINEL = "/tmp/dane-4l-g2-sentinel"
G3_SENTINEL = "/tmp/dane-4l-g3-sentinel"
G4_SENTINEL = "/tmp/dane-4l-g4-sentinel"
G5_SENTINEL = "/tmp/dane-4l-g5-sentinel"
G10_SENTINEL = "/tmp/dane-4l-g10-sentinel"
G7_TEMPFILE_SENTINEL = "/tmp/dane-4l-tempfile-sentinel"
H1_SENTINEL = "/tmp/dane-4m-h1-sentinel"
H8_SENTINEL = "/tmp/dane-4m-h8-sentinel"
G2_OUTSIDE_TMP = "/tmp/dane-4l-g2-outside.nsh"
G3_INCLUDEDIR_TMP = "/tmp/dane-4l-g3-inc"
G10_INCLUDEDIR_TMP = "/tmp/dane-4l-g10-inc"

ALL_COMMAND_SENTINELS = (
    F2_SYSTEM_SENTINEL,
    F2_APPENDFILE_SENTINEL,
    G2_SENTINEL,
    G3_SENTINEL,
    G4_SENTINEL,
    G5_SENTINEL,
    G10_SENTINEL,
    G7_TEMPFILE_SENTINEL,
    H1_SENTINEL,
    H8_SENTINEL,
)


class MakensisMissing(Exception):
    """No usable makensis ($MAKENSISU, ~/.mozbuild, or PATH)."""


class MakensisError(Exception):
    """makensis -PPO failed, or the input was refused before invocation."""


class ModuleVerError(Exception):
    """module.ver contains a forbidden % directive or an undefined @X@."""


def makensis_choice():
    """Return (path, version, label) for the makensis that will run, or Nones.

    Order: $MAKENSISU, then ~/.mozbuild/nsis/bin/makensis, then PATH
    (labelled as a fallback). The first existing executable wins.
    """
    candidates = []
    env = os.environ.get("MAKENSISU")
    if env:
        candidates.append((env, "$MAKENSISU"))
    candidates.append(
        (str(Path.home() / ".mozbuild/nsis/bin/makensis"), "~/.mozbuild/nsis/bin/makensis")
    )
    which = shutil.which("makensis")
    if which:
        candidates.append((which, "PATH fallback"))
    seen = set()
    for raw, label in candidates:
        path = Path(raw).expanduser()
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file() and os.access(path, os.X_OK):
            r = subprocess.run([resolved, "-VERSION"], capture_output=True, text=True)
            version = (r.stdout or r.stderr or "").strip() or "unknown"
            return resolved, version, label
    return None, None, None


def makensis_path():
    path, _version, _label = makensis_choice()
    return path


def makensis_version():
    _path, version, _label = makensis_choice()
    return version


def makensis_report():
    """Human-readable 'path (version, label)' or None if no makensis."""
    path, version, label = makensis_choice()
    if not path:
        return None
    return "%s (%s, %s)" % (path, version, label)


def makensis_is_path_fallback():
    """True when the chosen binary is the labelled PATH fallback, not $MAKENSISU or ~/.mozbuild."""
    _path, _version, label = makensis_choice()
    return label == "PATH fallback"


def normalize_publisher(value):
    """NFKC, casefold, lookalike fold, then drop zero-width and non-letters."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = s.casefold()
    s = "".join(_LOOKALIKE.get(ch, ch) for ch in s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in s if unicodedata.category(ch).startswith("L"))


def mentions_pepecoin(value):
    return "pepecoin" in normalize_publisher(value)


def mentions_mozilla(value):
    return "mozilla" in normalize_publisher(value)


def is_printable_ascii(value):
    """True if every character is in the printable ASCII range 0x20–0x7E."""
    if value is None:
        return True
    return all(32 <= ord(ch) <= 126 for ch in str(value))


def is_empty_or_mozilla_publisher(value):
    """True if missing, empty, or the publisher contains 'mozilla' (L8)."""
    if value is None:
        return True
    if str(value).strip() == "":
        return True
    s = str(value).strip()
    if s.startswith("${") and s.endswith("}") and s[2:-1].isidentifier():
        return True
    return mentions_mozilla(s)


# ---------------------------------------------------------------------------
# module.ver: prefer mozbuild.preprocessor.Preprocessor(marker="%") from
# pre-release esr153 snapshot 3bd39ccf6a (python/mozbuild/mozbuild/preprocessor.py,
# file sha256 378dcc667104271a22eedd58cba175fa35debeb29b431f022ac39ef879b25166
# on this box at /workspace/dane-windows/firefox-esr153; the same digest is
# in FIREFOX_153_7_0esr_RELEASE 9aecd40e), then the
# create_rc.parse_module_ver loop (config/create_rc.py lines 89–97).
# Fallback: a minimal reimplementation that only accepts %define /
# %include. Not a vendored copy of the preprocessor when falling back.
# %if / %ifdef and friends fail on the fallback path; an undefined @X@
# in a company or copyright value fails on either path.
# ---------------------------------------------------------------------------

_AT_SUBST = re.compile(r"@(\w+)@")

# Build-time substitutions the real create_rc.py receives from the build.
# They appear in the snapshot module.ver on non-company keys. Pre-defining
# them as placeholders lets the upstream Preprocessor parse the real tree;
# any other undefined @X@ still fails.
MODULE_VER_BUILD_PLACEHOLDERS = {
    "MOZ_APP_WINVERSION": "0.0.0.0",
    "MOZ_APP_VERSION": "0.0.0",
    "MOZ_APP_DISPLAYNAME": "Dane",
}

UPSTREAM_PREPROCESSOR_SHA256 = (
    "378dcc667104271a22eedd58cba175fa35debeb29b431f022ac39ef879b25166"
)
_DEFAULT_ESR_MOZBUILD = "/workspace/dane-windows/firefox-esr153/python/mozbuild"

_PREPROCESSOR_CLS = None
_PARSER_KIND = "minimal-reimplementation"
_PARSER_SOURCE = (
    "minimal reimplementation of create_rc.parse_module_ver "
    "(pre-release esr153 snapshot 3bd39ccf6a config/create_rc.py:89-97); only %define / %include"
)
_PARSER_FILE = None
_PARSER_FILE_SHA256 = None


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record_preprocessor(cls, loc):
    """Record the Preprocessor class, the file it came from, and that file's sha256."""
    global _PREPROCESSOR_CLS, _PARSER_KIND, _PARSER_SOURCE
    global _PARSER_FILE, _PARSER_FILE_SHA256
    _PREPROCESSOR_CLS = cls
    _PARSER_KIND = "mozbuild.preprocessor"
    _PARSER_FILE = loc
    try:
        _PARSER_FILE_SHA256 = _sha256_file(loc) if loc and os.path.isfile(loc) else None
    except OSError:
        _PARSER_FILE_SHA256 = None
    actual = _PARSER_FILE_SHA256 or "unreadable"
    if _PARSER_FILE_SHA256 == UPSTREAM_PREPROCESSOR_SHA256:
        match = "matches pre-release esr153 snapshot 3bd39ccf6a (same digest as FIREFOX_153_7_0esr_RELEASE 9aecd40e)"
    else:
        match = "MISMATCH expected pre-release esr153 snapshot 3bd39ccf6a (sha %s)" % UPSTREAM_PREPROCESSOR_SHA256
    _PARSER_SOURCE = (
        "mozbuild.preprocessor.Preprocessor(marker='%%') from %s "
        "(preprocessor.py sha256 %s; %s)"
        % (loc, actual, match)
    )


def _evict_mozbuild():
    """Drop cached mozbuild/mozpack modules so a later path can win."""
    for key in list(sys.modules):
        if key == "mozbuild" or key.startswith("mozbuild."):
            del sys.modules[key]
        elif key == "mozpack" or key.startswith("mozpack."):
            del sys.modules[key]


def _import_preprocessor_from_dir(cand):
    """Load Preprocessor from cand/mozbuild. Return True on success."""
    if not cand:
        return False
    cand = os.path.abspath(cand)
    loc = os.path.join(cand, "mozbuild", "preprocessor.py")
    if not os.path.isfile(loc):
        return False
    if cand in sys.path:
        sys.path.remove(cand)
    sys.path.insert(0, cand)
    _evict_mozbuild()
    try:
        from mozbuild.preprocessor import Preprocessor
        import mozbuild.preprocessor as _mpp

        _record_preprocessor(Preprocessor, os.path.abspath(_mpp.__file__))
        return True
    except ImportError:
        if cand in sys.path:
            sys.path.remove(cand)
        return False


def _try_import_preprocessor():
    """Import order: $DANE_ESR_MOZBUILD, then sys.path, then the boxed ESR tree."""
    global _PREPROCESSOR_CLS, _PARSER_KIND, _PARSER_SOURCE
    env = os.environ.get("DANE_ESR_MOZBUILD")
    if env and _import_preprocessor_from_dir(env):
        return
    try:
        from mozbuild.preprocessor import Preprocessor

        try:
            import mozbuild.preprocessor as _mpp
            loc = os.path.abspath(_mpp.__file__)
        except Exception:
            loc = None
        _record_preprocessor(Preprocessor, loc)
        return
    except ImportError:
        pass
    if _import_preprocessor_from_dir(_DEFAULT_ESR_MOZBUILD):
        return
    _PREPROCESSOR_CLS = None
    _PARSER_KIND = "minimal-reimplementation"
    _PARSER_SOURCE = (
        "minimal reimplementation of create_rc.parse_module_ver "
        "(pre-release esr153 snapshot 3bd39ccf6a config/create_rc.py:89-97); only %define / %include"
    )


_try_import_preprocessor()


def module_ver_parser_kind():
    return _PARSER_KIND


def module_ver_parser_report():
    return "%s: %s" % (_PARSER_KIND, _PARSER_SOURCE)


def module_ver_preprocessor_sha256():
    """sha256 of the preprocessor.py actually imported, or None on the fallback path."""
    return _PARSER_FILE_SHA256


def module_ver_preprocessor_sha_ok():
    """True when the imported file's sha256 matches the 3bd39ccf6a preprocessor (same digest as the 153.7.0esr tag)."""
    return _PARSER_FILE_SHA256 == UPSTREAM_PREPROCESSOR_SHA256


def _expand_at(text, defines, *, require_defined=False):
    def repl(m):
        key = m.group(1)
        if key in defines:
            return str(defines[key])
        if require_defined:
            raise ModuleVerError("undefined @%s@" % key)
        return m.group(0)

    return _AT_SUBST.sub(repl, text)


def _preprocess_module_ver(path, defines):
    """Expand %define / %include and @KEY@. Any other % directive fails."""
    defines = dict(defines)
    path = os.fspath(path)
    out_lines = []
    with open(path, encoding="latin1") as fh:
        for lineno, line in enumerate(fh, 1):
            stripped = line.lstrip()
            if stripped.startswith("%define"):
                rest = stripped[len("%define") :].strip()
                name, _, val = rest.partition(" ")
                if name:
                    defines[name] = _expand_at(val.strip(), defines, require_defined=True)
                continue
            if stripped.startswith("%include"):
                inc = stripped[len("%include") :].strip().strip('"').strip("'")
                inc_path = inc if os.path.isabs(inc) else os.path.join(os.path.dirname(path), inc)
                more, defines = _preprocess_module_ver(inc_path, defines)
                out_lines.extend(more)
                continue
            if stripped.startswith("%"):
                directive = stripped.split()[0] if stripped.split() else "%"
                raise ModuleVerError(
                    "%s:%s: forbidden %% directive %s (only %%define and %%include are allowed)"
                    % (path, lineno, directive)
                )
            out_lines.append(_expand_at(line, defines, require_defined=False))
    return out_lines, defines


def _preprocess_module_ver_upstream(path, defines):
    """Run the ESR Preprocessor(marker='%') over path; return output lines."""
    pp = _PREPROCESSOR_CLS(defines=defines, marker="%")
    pp.context.update(defines)
    pp.out = io.StringIO()
    pp.do_filter("substitution")
    try:
        with open(path, encoding="latin1") as fh:
            pp.do_include(fh)
    except Exception as exc:
        # Preprocessor.Error str() is a tuple repr such as
        # ('file', 1, 'UNDEFINED_VAR', 'NOPE') — rewrite so callers can
        # match "undefined" case-insensitively.
        key = getattr(exc, "key", None)
        detail = str(exc)
        if key == "UNDEFINED_VAR" or "UNDEFINED_VAR" in detail:
            name = exc.args[0][3] if getattr(exc, "args", None) and exc.args and isinstance(exc.args[0], tuple) and len(exc.args[0]) >= 4 else key
            raise ModuleVerError(
                "%s: undefined substitution @%s@" % (path, name or "X")
            ) from exc
        raise ModuleVerError("%s: preprocessor error: %s" % (path, detail)) from exc
    pp.out.seek(0)
    return pp.out.readlines()


def parse_module_ver(path, defines=None):
    """Parse module.ver. Raises ModuleVerError on forbidden % or undefined @X@
    in company or copyright values."""
    merged = dict(MODULE_VER_BUILD_PLACEHOLDERS)
    merged.update(defines or {})
    result = {}
    if _PREPROCESSOR_CLS is not None:
        lines = _preprocess_module_ver_upstream(os.fspath(path), merged)
    else:
        lines, _defs = _preprocess_module_ver(path, merged)
    for line in lines:
        content, *_comment = line.split("#", 1)
        if not content.strip():
            continue
        if "=" not in content:
            continue
        entry, value = content.split("=", 1)
        result[entry.strip()] = value.strip()
    for key in ("WIN32_MODULE_COMPANYNAME", "WIN32_MODULE_COPYRIGHT"):
        val = result.get(key)
        if val and _AT_SUBST.search(val):
            raise ModuleVerError(
                "%s: undefined substitution in %s: %r" % (path, key, val)
            )
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
# NSIS: allowlist branding.nsi and its includes, then makensis -PPO
# ---------------------------------------------------------------------------

_PPO_COMPANY = re.compile(r'^!echo "PPO_CompanyName=(.*)"\s*$')
_PPO_ARP = re.compile(r'^!echo "PPO_ARPPublisher=(.*)"\s*$')

# Optional trailing ; or # comment on an otherwise-valid line.
_TRAIL_COMMENT = r'(?:\s*(?:;|#).*)?'
# Simple !define NAME value — no /redef, /file, /ifndef, or other flags.
# Value is a double- or single-quoted string, or a bare token (numbers, 0x hex).
_DEFINE_RE = re.compile(
    r'^!define\s+([A-Za-z_][A-Za-z0-9_]*)\s+'
    r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|(?:0x[0-9A-Fa-f]+|[A-Za-z0-9_.+-]+))'
    + _TRAIL_COMMENT
    + r'$',
    re.IGNORECASE,
)
_INCLUDE_RE = re.compile(
    r'^!include\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))'
    + _TRAIL_COMMENT
    + r'$',
    re.IGNORECASE,
)


_ASCII_CONTINUE_STRIP = " \t\r"


def _ends_with_continuation(line):
    """True when the last character after stripping ASCII space, tab, and CR is \\."""
    return line.rstrip(_ASCII_CONTINUE_STRIP).endswith("\\")


def _drop_continuation_backslash(line):
    return line.rstrip(_ASCII_CONTINUE_STRIP)[:-1]


def _forbidden_line_reason(line):
    """Return a short reason if the physical line has NUL, a non-tab C0 control, or non-ASCII whitespace."""
    for ch in line:
        if ch == "\t":
            continue
        o = ord(ch)
        if o == 0:
            return "NUL"
        if o < 32:
            return "control character U+%04X" % o
        if o > 127 and ch.isspace():
            return "non-ASCII whitespace U+%04X" % o
    return None


def check_physical_lines(text, path):
    """Refuse a file whose physical lines contain NUL, non-tab C0 controls, or non-ASCII whitespace."""
    for lineno, line in enumerate(text.splitlines(), 1):
        reason = _forbidden_line_reason(line)
        if reason:
            raise MakensisError(
                "refused to invoke makensis: %s:%s: line contains %s"
                % (path, lineno, reason)
            )


def logical_lines(text):
    """Yield (lineno, logical_line) after joining backslash continuations.

    lineno is 1-based and points at the first physical line of the logical
    line. A physical line is continued only when its last character, after
    stripping ASCII space, tab, and CR, is `\\`. Unicode whitespace is
    not stripped for this test. Joining does not insert a space (so
    `!sys\\` + `tem` is `!system`).
    """
    physical = text.splitlines()
    i = 0
    n = len(physical)
    while i < n:
        start = i + 1
        part = physical[i]
        while _ends_with_continuation(part):
            part = _drop_continuation_backslash(part)
            i += 1
            if i >= n:
                break
            part = part + physical[i]
        yield start, part
        i += 1


def _include_path_token(match):
    return match.group(1) or match.group(2) or match.group(3) or ""


def _is_allowed_sibling_include(raw, including_path):
    """Relative bare filename, no wildcard, no `..`, existing same-directory sibling."""
    if not raw or raw in (".", ".."):
        return False
    if any(ch in raw for ch in "*?[]"):
        return False
    if raw.startswith("/") or raw.startswith("\\") or re.match(r"^[A-Za-z]:[\\/]", raw):
        return False
    if "/" in raw or "\\" in raw or ".." in raw:
        return False
    parent = Path(including_path).resolve().parent
    candidate = parent / raw
    try:
        if not candidate.is_file():
            return False
        if candidate.resolve().parent != parent:
            return False
    except OSError:
        return False
    return True


def classify_nsis_line(logical, path, lineno):
    """Return ('comment'|'blank'|'define'|'include', detail) or raise MakensisError."""
    stripped = logical.strip()
    if not stripped:
        return "blank", None
    if stripped.startswith("#") or stripped.startswith(";"):
        return "comment", None
    m = _DEFINE_RE.match(stripped)
    if m:
        return "define", m.group(1)
    m = _INCLUDE_RE.match(stripped)
    if m:
        raw = _include_path_token(m)
        if not _is_allowed_sibling_include(raw, path):
            raise MakensisError(
                "refused to invoke makensis: %s:%s: !include is not a relative "
                "sibling (no wildcard, no '..'): %r"
                % (path, lineno, stripped)
            )
        return "include", raw
    raise MakensisError(
        "refused to invoke makensis: %s:%s: line not on the allowlist: %r"
        % (path, lineno, stripped)
    )


def include_set(branding_path):
    """branding file plus the relative siblings it !includes (allowlisted only).

    A standalone *.branding.nsi fixture is the only member unless it has an
    allowed sibling !include. Other fixtures in a shared directory are not
    copied in. Files are not added until their !include line is accepted.
    """
    branding_path = Path(branding_path).resolve()
    files = []
    seen = set()
    queue = [branding_path]
    while queue:
        path = queue.pop(0)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        files.append(resolved)
        text = resolved.read_text(encoding="utf-8", errors="replace")
        check_physical_lines(text, resolved)
        for lineno, logical in logical_lines(text):
            stripped = logical.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(";"):
                continue
            m = _INCLUDE_RE.match(stripped)
            if not m:
                continue
            raw = _include_path_token(m)
            if _is_allowed_sibling_include(raw, resolved):
                queue.append((resolved.parent / raw).resolve())
    return files


def refuse_unsafe_nsis(branding_path):
    """Raise MakensisError unless every logical line is on the allowlist."""
    branding_path = Path(branding_path).resolve()
    if not branding_path.is_file():
        raise MakensisError("branding file not found: %s" % branding_path)
    seen = set()
    queue = [branding_path]
    while queue:
        path = queue.pop(0)
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        text = resolved.read_text(encoding="utf-8", errors="replace")
        check_physical_lines(text, resolved)
        for lineno, logical in logical_lines(text):
            kind, detail = classify_nsis_line(logical, resolved, lineno)
            if kind == "include":
                queue.append((resolved.parent / detail).resolve())


def prepare_4l_bypass_payloads(fixture_dir):
    """Place include payloads under /tmp so a missed refusal would write sentinels."""
    fixture_dir = Path(fixture_dir)
    src = fixture_dir / "G2-outside.nsh"
    if src.is_file():
        shutil.copy2(src, G2_OUTSIDE_TMP)
    src = fixture_dir / "G3-x.nsh"
    if src.is_file():
        Path(G3_INCLUDEDIR_TMP).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, Path(G3_INCLUDEDIR_TMP) / "x.nsh")
    src = fixture_dir / "G10-wild.nsh"
    if src.is_file():
        Path(G10_INCLUDEDIR_TMP).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, Path(G10_INCLUDEDIR_TMP) / "w1.nsh")


def cleanup_4l_bypass_payloads():
    """Remove /tmp include payloads this helper created (not used as sentinels)."""
    for path in (G2_OUTSIDE_TMP,):
        try:
            os.remove(path)
        except OSError:
            pass
    for d in (G3_INCLUDEDIR_TMP, G10_INCLUDEDIR_TMP):
        shutil.rmtree(d, ignore_errors=True)


def sentinels_that_exist():
    return [p for p in ALL_COMMAND_SENTINELS if os.path.exists(p)]


def remove_command_sentinels():
    """Manual cleanup only. The check must not call this before a run:
    a pre-existing sentinel is evidence of an earlier escape and must FAIL.
    """
    for path in ALL_COMMAND_SENTINELS:
        try:
            os.remove(path)
        except OSError:
            pass


def resolve_branding_nsi(branding_path):
    """Return (company, arp_publisher, ppo_stdout) from makensis -PPO."""
    path, _version, _label = makensis_choice()
    if not path:
        raise MakensisMissing(
            "no makensis found ($MAKENSISU, ~/.mozbuild/nsis/bin/makensis, or PATH)"
        )
    branding_path = Path(branding_path).resolve()
    if not branding_path.is_file():
        raise MakensisError("branding file not found: %s" % branding_path)
    refuse_unsafe_nsis(branding_path)
    with tempfile.TemporaryDirectory(prefix="dane-ppo-") as td:
        td = Path(td)
        for src in include_set(branding_path):
            shutil.copy2(src, td / src.name)
        if branding_path.name != "branding.nsi":
            shutil.copy2(branding_path, td / "branding.nsi")
        wrapper = td / "wrapper.nsi"
        # Unicode true plus installer.nsi's pre-branding defines (ESR
        # 153.7.0 browser/installer/windows/nsis/installer.nsi lines
        # 34, 74, 78, 80). Not a full build-environment mirror.
        wrapper.write_text(
            "Unicode true\n"
            "!define NO_STARTMENU_DIR\n"
            "!define NONADMIN_ELEVATE\n"
            '!define AbortSurveyURL "http://www.kampyle.com/feedback_form/ff-feedback-form.php?site_code=8166124&form_id=12116&url="\n'
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
