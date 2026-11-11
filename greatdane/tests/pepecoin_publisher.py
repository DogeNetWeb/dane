#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Resolve and normalize Windows publisher/company values (round 4k).

This is test tooling only. It is not shipped in the product.

NSIS values come from makensis -PPO on a tiny wrapper that sets
`Unicode true`, !includes the branding file, and echoes ${CompanyName}
and ${ARPPublisher}. The binary is chosen in this order: $MAKENSISU,
then ~/.mozbuild/nsis/bin/makensis (the bootstrapped build tool), then
PATH as a labelled fallback. If makensis is missing, callers must FAIL
— never PASS. This is not a full build-environment mirror.

Before makensis is invoked, every file in the include set is refused if
it contains !system, !execute, !appendfile, !delfile, !makensis,
!packhdr, !finalize, !uninstfinalize, !getdllversion, or !gettlbversion.
branding.nsi is also refused if it contains any !if / !ifdef / !ifndef
(or other !if* command).

module.ver is parsed by a reimplementation of the small
create_rc.parse_module_ver loop from Firefox ESR 153.7.0
config/create_rc.py (lines 89–97), plus a marker-% expander that only
allows %define and %include. Any other % directive, or an undefined @X@
in a company or copyright value, is a failure. This is not a vendored
copy of mozbuild.preprocessor.

Values are normalized before matching: NFKC, casefold, Cyrillic/Greek
(and common Latin-accent) lookalikes mapped to Latin, then zero-width
and non-letter characters stripped. A company or publisher value must
also be printable ASCII after resolution. A value that contains
"pepecoin" or "mozilla" after the fold is a failure. The official
shared.nsh Publisher "Mozilla" fallback is the exception, and applies
only when ARPPublisher is undefined.
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

# Compile-time NSIS commands that can touch the filesystem or run a process.
# Refuse these in the include set before invoking makensis (F2).
FORBIDDEN_NSIS_COMMANDS = (
    "!system",
    "!execute",
    "!appendfile",
    "!delfile",
    "!makensis",
    "!packhdr",
    "!finalize",
    "!uninstfinalize",
    "!getdllversion",
    "!gettlbversion",
)

# Sentinels used by the F2 fixtures. The check must refuse those fixtures
# and must not create these paths.
F2_SYSTEM_SENTINEL = "/tmp/dane-4k-f2-system-sentinel"
F2_APPENDFILE_SENTINEL = "/tmp/dane-4k-f2-appendfile-sentinel"


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
# module.ver: reimplementation of create_rc.parse_module_ver
# (Firefox ESR 153.7.0 config/create_rc.py lines 89–97), with a marker-%
# expander that only accepts %define / %include. Not a vendored copy of
# mozbuild.preprocessor; %if / %ifdef and friends are a failure, as is an
# undefined @X@ in a company or copyright value.
# ---------------------------------------------------------------------------

_AT_SUBST = re.compile(r"@(\w+)@")


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


def parse_module_ver(path, defines=None):
    """Parse module.ver. Raises ModuleVerError on forbidden % or undefined @X@
    in company or copyright values."""
    defines = dict(defines or {})
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
# NSIS: refuse unsafe commands, then makensis -PPO
# ---------------------------------------------------------------------------

_PPO_COMPANY = re.compile(r'^!echo "PPO_CompanyName=(.*)"\s*$')
_PPO_ARP = re.compile(r'^!echo "PPO_ARPPublisher=(.*)"\s*$')
_FORBIDDEN_SET = {cmd.lower() for cmd in FORBIDDEN_NSIS_COMMANDS}


def _nsis_command(line):
    s = line.strip()
    if not s or s.startswith(";") or s.startswith("#"):
        return None
    if not s.startswith("!"):
        return None
    return s.split()[0].lower()


def include_set(branding_path):
    """Files that would be visible to makensis for this branding input.

    If the file is named branding.nsi, siblings in the same directory are
    part of the set (!include / /file). A standalone *.branding.nsi fixture
    is the only member — other fixtures in a shared directory are not.
    """
    branding_path = Path(branding_path).resolve()
    files = [branding_path]
    if branding_path.name == "branding.nsi":
        for sib in branding_path.parent.iterdir():
            if sib.is_file() and sib.resolve() != branding_path:
                files.append(sib)
    return files


def forbidden_nsis_command_in(path):
    """Return the first forbidden compile-time command in path, or None."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        tok = _nsis_command(line)
        if tok in _FORBIDDEN_SET:
            return tok
    return None


def ifdef_command_in(path):
    """Return the first !if* command in path, or None."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        tok = _nsis_command(line)
        if tok and tok.startswith("!if"):
            return tok
    return None


def refuse_unsafe_nsis(branding_path):
    """Raise MakensisError if the include set must not be handed to makensis."""
    branding_path = Path(branding_path).resolve()
    for path in include_set(branding_path):
        cmd = forbidden_nsis_command_in(path)
        if cmd:
            raise MakensisError(
                "refused to invoke makensis: %s contains %s" % (path, cmd)
            )
    cmd = ifdef_command_in(branding_path)
    if cmd:
        raise MakensisError(
            "refused to invoke makensis: %s contains %s" % (branding_path, cmd)
        )


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
        wrapper.write_text(
            "Unicode true\n"
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
