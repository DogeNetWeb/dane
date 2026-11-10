#!/usr/bin/env python3
"""Guard (round 4, L-a): keep the retired legacy Mac signing mode out of the tree.

    python3 greatdane/tests/no_legacy_deep_sign_check.py [--root DIR] [-v]      (default root: the tree root)

It flags:
  1. Any `--deep` that is not part of a `--verify` command. That covers:
     - shell line continuations (joined first);
     - wrapper variables (`$CS --deep`, `"$CODESIGN" --deep`);
     - flag variables (`DEEP=--deep`, `$DEEP`, `${deep_flag}`);
     - one line that both verifies and signs (`codesign --verify --deep a; codesign --deep --sign - b` flags
       the second command; commands are split on ; && || | and newlines);
     - Python string literals, including implicit and `+` concatenation (`"--de" "ep"`, `"--de" + "ep"`).
     In Python, `--deep` is flagged when it is a list or tuple element or a call argument, or a command string
     containing codesign, and no string in the same statement contains `--verify`. Comparisons such as
     `"--deep" not in line` and docstrings are not commands.
  2. The blanket browser.entitlements.plist, in code.
  3. A legacy script name outside greatdane/tools/:
     - sign-only.sh anywhere other than .../greatdane/tools/sign-only.sh (that covers $G/..., absolute and
       relative paths, and a bare call);
     - build-universal.sh anywhere;
     - notarize.sh or notarize.next*.sh used without --submit-existing (the legacy re-sign mode).
     In Python, a bare "sign-only.sh" is accepted only as an os.path.join() part that follows "tools".
  4. YAML (*.yml, *.yaml, and taskcluster/config.yml): `deep: true` (also True/yes/on, quoted keys and flow
     style), with PyYAML if it is installed and a line parser otherwise. YAML string values are checked with
     the shell rules as well.

Scope: every text file under greatdane/ (including greatdane/tests and non-.sh/.py files) plus
taskcluster/config.yml. Binary files are skipped.
- Shell rules apply to *.sh, files with a shell shebang, and other text files.
- In Markdown, only fenced code blocks are checked; prose may name the legacy scripts.
- Shell comments are ignored.
A line may opt out with a trailing `nolegacy: <reason>` comment. Opted-out lines are always listed in the
output, so reviewers see them. Exit 1 on any hit.
"""
import ast, os, re, shlex, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if "--root" in sys.argv:
    ROOT = os.path.abspath(sys.argv[sys.argv.index("--root") + 1])
VERBOSE = "-v" in sys.argv
D = "-" * 2 + "deep"          # built at runtime so this file's own literals are not commands
V = "-" * 2 + "verify"
# Names joined at runtime so this file's own literals never look like calls.
SO, BU, NO = "".join(["sign-", "only.sh"]), "".join(["build-", "universal.sh"]), "".join(["notar", "ize"])
BEP = ".".join(["browser", "entitlements", "plist"])
NOTE = "legacy %s.sh mode (no --submit-existing)" % NO
PRAGMA = re.compile(r"#.*\bnolegacy:\s*\S")
hits, waived = [], []


def hit(path, n, msg, line=""):
    if PRAGMA.search(line):
        waived.append("%s:%d: %s" % (os.path.relpath(path, ROOT), n, msg))
    else:
        hits.append("%s:%d: %s" % (os.path.relpath(path, ROOT), n, msg))


def legacy_name(tok):
    """Reason string if a single token/path names a legacy script outside greatdane/tools/, else None."""
    t = tok.strip().strip("'\"")
    if re.fullmatch(r"(?:.*/)?" + re.escape(SO), t):
        if not re.search(r"(^|/)greatdane/tools/" + re.escape(SO) + "$", t):
            return "legacy %s outside greatdane/tools/: %s" % (SO, t)
    if re.fullmatch(r"(?:.*/)?" + re.escape(BU), t):
        return "legacy %s: %s" % (BU, t)
    return None


def notarize_tok(tok):
    return re.fullmatch(r"(?:.*/)?" + NO + r"(?:\.next[\w.-]*)?\.sh", tok.strip().strip("'\"")) is not None


def strip_sh_comment(line):
    out, q = [], None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
            elif c == "\\" and q == '"':
                pass
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t;&|("):
            break
        out.append(c)
    return "".join(out)


def sh_segments(text):
    """Yield (start_line, segment_tokens) for each simple command; continuations joined, comments stripped."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        start, buf = i + 1, strip_sh_comment(lines[i])
        while buf.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            buf = buf.rstrip()[:-1] + " " + strip_sh_comment(lines[i])
        i += 1
        try:
            lx = shlex.shlex(buf, posix=True, punctuation_chars=";&|()")
            lx.whitespace_split = True
            lx.commenters = ""
            toks = list(lx)
        except ValueError:
            toks = buf.split()
        seg = []
        for t in toks + [";"]:
            if t and set(t) <= set(";&|()"):
                if seg:
                    yield start, seg, lines[start - 1]
                seg = []
            else:
                seg.append(t)


def check_shell_text(path, text, base_line=0):
    for n, seg, raw in sh_segments(text):
        n += base_line
        verify = any(t == V or t.startswith(V + "=") for t in seg)
        deepvar = any(re.search(r"\$\{?\w*deep\w*\}?", t, re.I) for t in seg)
        if not verify and (D in seg or any(re.fullmatch(r"\w+=" + D, t) for t in seg) or deepvar):
            hit(path, n, "codesign %s (or a deep flag variable) used outside --verify: %s" % (D, " ".join(seg)[:120]), raw)
        if any(BEP in t for t in seg):
            hit(path, n, "blanket " + BEP, raw)
        for t in seg:
            why = legacy_name(t)
            if why:
                hit(path, n, why, raw)
        if any(notarize_tok(t) for t in seg) and "--submit-existing" not in seg:
            hit(path, n, NOTE, raw)


def fold(node):
    """Value of a str constant or a +-concatenation of str constants, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = fold(node.left), fold(node.right)
        if a is not None and b is not None:
            return a + b
    return None


def check_python(path, text):
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        hit(path, e.lineno or 0, "Python file does not parse; cannot check it")
        return
    lines = text.split("\n")
    parents = {}
    for p in ast.walk(tree):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    docs = set()
    for p in ast.walk(tree):
        if isinstance(p, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and p.body \
                and isinstance(p.body[0], ast.Expr) and fold(p.body[0].value) is not None:
            docs.add(p.body[0].value)

    def stmt_of(n):
        while n in parents and not isinstance(n, ast.stmt):
            n = parents[n]
        return n

    seen = set()
    for node in ast.walk(tree):
        s = fold(node)
        if s is None or node in docs or node in seen:
            continue
        par = parents.get(node)
        if isinstance(par, ast.BinOp) and fold(par) is not None:
            continue  # the outer concatenation is handled as one string
        for sub in ast.walk(node):
            seen.add(sub)
        n = getattr(node, "lineno", 0)
        raw = lines[n - 1] if 0 < n <= len(lines) else ""
        st = stmt_of(node)
        strs = [fold(x) for x in ast.walk(st)]
        verify = any(x is not None and V in x for x in strs)
        in_compare = isinstance(par, ast.Compare)
        as_arg = isinstance(par, (ast.List, ast.Tuple, ast.Call, ast.Starred, ast.keyword))
        try:
            toks = shlex.split(s)
        except ValueError:
            toks = s.split()
        if not verify and not in_compare:
            if (s == D and as_arg) or (D in toks and "codesign" in s) or re.fullmatch(r"\w+=" + D, s):
                hit(path, n, "%s in a Python string outside --verify: %r" % (D, s[:100]), raw)
        if BEP in s and not in_compare:
            hit(path, n, "blanket " + BEP, raw)
        for t in (toks if len(toks) > 1 else [s]):
            why = legacy_name(t)
            if not why:
                continue
            if t == SO and isinstance(par, ast.Call):
                args = [fold(a) for a in par.args]
                if node in par.args:
                    k = par.args.index(node)
                    if k > 0 and args[k - 1] == "tools":
                        continue
            if not in_compare:
                hit(path, n, why, raw)
        if any(notarize_tok(t) for t in toks) and "--submit-existing" not in toks and not in_compare:
            hit(path, n, NOTE, raw)


YAML_DEEP = re.compile(r"""(^|[\s{,\-])["']?deep["']?\s*:\s*["']?(true|yes|on)["']?\s*($|[,}#\s])""", re.I)


def check_yaml(path, text):
    for n, line in enumerate(text.split("\n"), 1):
        code = re.sub(r"(^|\s)#.*$", "", line)
        if YAML_DEEP.search(code):
            hit(path, n, "YAML deep: true", line)
    try:
        import yaml  # optional; the line parser above always runs
    except ImportError:
        return
    try:
        docs = list(yaml.safe_load_all(text))
    except Exception as e:
        hit(path, 0, "YAML does not parse: %s" % str(e).split("\n")[0])
        return

    def walk(o, trail):
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).lower() == "deep" and (v is True or str(v).lower() in ("true", "yes", "on")):
                    if not any(re.search(r"deep\W+(true|yes|on)", l, re.I) for l in text.split("\n")):
                        hit(path, 0, "YAML deep: true at %s" % "/".join(trail + [str(k)]))
                walk(v, trail + [str(k)])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, trail + [str(i)])
        elif isinstance(o, str) and (D in o or SO in o or BU in o):
            check_shell_text(path, o)
    for d in docs:
        walk(d, [])


def check_markdown(path, text):
    lines, i = text.split("\n"), 0
    while i < len(lines):
        if re.match(r"\s*(```|~~~)", lines[i]):
            j = i + 1
            while j < len(lines) and not re.match(r"\s*(```|~~~)", lines[j]):
                j += 1
            check_shell_text(path, "\n".join(lines[i + 1:j]), base_line=i + 1)
            i = j + 1
        else:
            i += 1


def check_file(path):
    try:
        data = open(path, "rb").read()
    except OSError:
        return
    if b"\0" in data[:8192]:
        return  # binary (icons etc.)
    text = data.decode("utf-8", errors="replace")
    low = path.lower()
    first = text.split("\n", 1)[0]
    if low.endswith(".py") or re.match(r"#!.*python", first):
        check_python(path, text)
    elif low.endswith((".yml", ".yaml")):
        check_yaml(path, text)
    elif low.endswith((".md", ".markdown")):
        check_markdown(path, text)
    else:
        check_shell_text(path, text)


def main():
    files = []
    for dp, dns, fns in os.walk(os.path.join(ROOT, "greatdane")):
        dns[:] = [d for d in dns if d not in (".git", "__pycache__")]
        files += [os.path.join(dp, f) for f in fns]
    cfg = os.path.join(ROOT, "taskcluster", "config.yml")
    if os.path.isfile(cfg):
        files.append(cfg)
    for f in sorted(files):
        check_file(f)
    for w in waived:
        print("WAIVED (nolegacy) " + w)
    for h in hits:
        print("FAIL " + h)
    if VERBOSE:
        print("scanned %d files under %s" % (len(files), ROOT))
    print("legacy-signing check: %s (%d hit%s, %d waived, %d files)" % (
        "FAIL" if hits else "PASS", len(hits), "" if len(hits) == 1 else "s", len(waived), len(files)))
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
