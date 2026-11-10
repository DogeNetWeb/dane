#!/usr/bin/env python3
"""Guard (round 4 L-a, round 4c L1/L2): keep the retired legacy Mac signing mode out of the tree.

    python3 greatdane/tests/no_legacy_deep_sign_check.py [--root DIR] [-v]      (default root: the tree root)

It flags:
  1. The deep flag outside a pure verify command. A verify command has --verify (or -v) and no sign flag
     (--sign/-s/--force/-f). A --verify anywhere in a command that also signs does not exempt it.
     Shell:
     - line continuations are joined first. Commands are split on ; && || | ( ) and newlines.
     - variables assigned in the same file are expanded before checking (`F=--de` ... `${F}ep`).
     - wrapper and flag variables are flagged: `$CS --deep`, `DEEP=--deep`, `$DEEP`, `${deep_flag}`.
     - in a codesign command (including one run through an unresolved `$CS` wrapper), ANY token containing
       "deep" (any case) is flagged. So is a token that glues an unresolved expansion to a fragment of the
       flag (`${F}ep`, `--de$X`).
     - eval, and bash/sh/zsh/dash -c strings, are parsed as shell and checked the same strict way.
     Python (string expressions are folded: constants, `+`, `*`, f-strings, and names assigned to a
     foldable value anywhere in the file):
     - `D = "--deep"`, `"-" * 2 + "deep"`, `f"{P}deep"`, `CS + " --deep"`, a list/tuple/call/dict element, or
       a command string. An expression with unknown parts is flagged when a known part is the flag or glues a
       fragment of it to an unknown part.
     - Comparisons (`"--deep" not in line`) and docstrings are not commands.
  2. The blanket browser.entitlements.plist, in code.
  3. A legacy script name:
     - sign-only.sh unless it is the in-tree one. The in-tree path is `$TREE/greatdane/tools/sign-only.sh` (or
       `${TREE}/...`), a relative `greatdane/tools/sign-only.sh` (resolved against $TREE), or an absolute path
       equal to this checkout's greatdane/tools/sign-only.sh. Variables are expanded first (except TREE).
       A glob that can match the name (`sign-o*.sh`), a bare call, ./ or $G paths, and a fake path that only
       ends in .../tools/sign-only.sh are all flagged.
     - build-universal.sh anywhere (also via a glob).
     - notarize.sh or notarize.next*.sh used without --submit-existing (the legacy re-sign mode).
     In Python, a bare "sign-only.sh" is accepted only as an os.path.join() part that follows "tools".
  4. YAML (*.yml, *.yaml, and taskcluster/config.yml), with or without PyYAML:
     - `deep: true` (also True/yes/on/y, quoted keys, flow style);
     - values behind anchors (`&a true`) or tags (`!!bool true`), and aliases (`deep: *a`) resolved to an
       anchored scalar;
     - plain values and block scalars (`run: |`) are checked with the shell rules.
     With PyYAML, every parsed `deep` truthy value is also reported. No line, comment or other text can
     suppress a hit.

Scope: every text file under greatdane/ (including greatdane/tests and non-.sh/.py files) plus
taskcluster/config.yml. Binary files are skipped.
- Shell rules apply to *.sh, files with a shell shebang, and other text files.
- In Markdown, fenced code blocks and indented code blocks (4+ spaces past any list indentation, after a
  blank line) are checked; prose may name the legacy scripts.
- Shell comments are not commands and are skipped (quote-aware).
There is no opt-out (round 4c L1): the old `nolegacy:` waiver comment is gone, and a line carrying one is
checked like any other. Code that has to name a flag (the selftest's must-not-match regex) builds it at
runtime. Limits: values the folder cannot evaluate statically (str.join, %, .format, environment input) are
not resolved. Exit 1 on any hit.
"""
import ast, fnmatch, os, re, shlex, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if "--root" in sys.argv:
    ROOT = os.path.abspath(sys.argv[sys.argv.index("--root") + 1])
VERBOSE = "-v" in sys.argv
# Built with str.join (which the folder does not evaluate), so this file's own constants are not commands.
D = "".join(["-", "-", "de", "ep"])
V = "".join(["-", "-", "ver", "ify"])
SO, BU = "".join(["sign-", "only.sh"]), "".join(["build-", "universal.sh"])
NO = "".join(["notar", "ize"])
BEP = ".".join(["browser", "entitlements", "plist"])
NOTE = "legacy %s.sh mode (no --submit-existing)" % NO
SIGN_FLAGS = ("--sign", "-s", "--force", "-f")
UNK = "\x00"                                   # stands for a part whose value is unknown
SHELLS = ("bash", "sh", "zsh", "dash", "ksh")
hits = []


def hit(path, n, msg, line=""):
    hits.append("%s:%d: %s" % (os.path.relpath(path, ROOT), n, msg))


def is_fragment(rem):
    """A literal piece that, glued to an unknown part, could complete the deep flag."""
    rem = rem.lower()
    return len(rem) >= 2 and rem not in ("--",) and (D.startswith(rem) or D.endswith(rem)) and rem != D


def glued_fragment(tok):
    """True if tok contains an unknown part (UNK or an unresolved $X) next to a fragment of the flag."""
    parts = re.split(UNK + r"|\$\{[^}]*\}|\$\w+", tok)
    if len(parts) < 2:
        return False
    return any(is_fragment(p) for p in parts if p)


def verify_only(toks):
    return any(t in (V, "-v") or t.startswith(V + "=") for t in toks) and not any(
        t in SIGN_FLAGS or t.startswith("--sign=") for t in toks)


def deep_tok(t):
    return t == D or t.lower().startswith(D + "=") or bool(re.fullmatch(r"\w+=" + re.escape(D), t))


# ---------------------------------------------------------------- legacy script names
def in_tree_so(t):
    for pre in ("$TREE/", "${TREE}/"):
        if t.startswith(pre):
            return os.path.normpath(t[len(pre):]) == os.path.join("greatdane", "tools", SO)
    if "$" in t or UNK in t:
        return False
    if os.path.isabs(t):
        return os.path.normpath(t) == os.path.join(ROOT, "greatdane", "tools", SO)
    return "/" in t and not t.startswith("./") and os.path.normpath(t) == os.path.join("greatdane", "tools", SO)


def glob_names(base, name):
    """base is a glob (*, ?, [..]) that can match name and has at least 4 literal characters besides .sh."""
    if not any(c in base for c in "*?["):
        return False
    lit = re.sub(r"\[[^\]]*\]|[*?]", "", base)
    lit = lit[:-3] if lit.endswith(".sh") else lit
    return len(lit) >= 4 and fnmatch.fnmatchcase(name, base)


def legacy_name(tok):
    """Reason string if a single token/path names a legacy script outside the in-tree tools, else None."""
    t = tok.strip().strip("'\"")
    m = re.match(r"^\w+=(.*)$", t)
    if m:
        t = m.group(1)
    base = t.rstrip("/").rsplit("/", 1)[-1]
    if base == BU or glob_names(base, BU):
        return "legacy %s: %s" % (BU, t)
    if base == SO or glob_names(base, SO):
        if base != SO:
            return "legacy %s named through a glob: %s" % (SO, t)
        if not in_tree_so(t):
            return "legacy %s outside greatdane/tools/: %s (in-tree is $TREE/greatdane/tools/%s)" % (SO, t, SO)
    return None


def notarize_tok(tok):
    t = tok.strip().strip("'\"")
    base = t.rsplit("/", 1)[-1]
    if re.fullmatch(NO + r"(?:\.next[\w.-]*)?\.sh", base):
        return True
    return glob_names(base, NO + ".sh") or glob_names(base, NO + ".next.sh")


# ---------------------------------------------------------------- shell
def strip_sh_comment(line):
    out, q = [], None
    for i, c in enumerate(line):
        if q:
            if c == q and not (q == '"' and i > 0 and line[i - 1] == "\\"):
                q = None
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t;&|("):
            break
        out.append(c)
    return "".join(out)


def split_words(buf):
    try:
        lx = shlex.shlex(buf, posix=True, punctuation_chars=";&|()")
        lx.whitespace_split = True
        lx.commenters = ""
        return list(lx)
    except ValueError:
        return buf.split()


def sh_segments(text):
    """Yield (start_line, segment_tokens, raw_line) per simple command; continuations joined, comments stripped."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        start, buf = i + 1, strip_sh_comment(lines[i])
        while buf.rstrip().endswith("\\") and i + 1 < len(lines):
            i += 1
            buf = buf.rstrip()[:-1] + " " + strip_sh_comment(lines[i])
        i += 1
        seg = []
        for t in split_words(buf) + [";"]:
            if t and set(t) <= set(";&|()"):
                if seg:
                    yield start, seg, lines[start - 1]
                seg = []
            else:
                seg.append(t)


def sh_vars(text):
    """NAME=value assignments in a shell text (last one wins); values are kept unexpanded."""
    out = {}
    for _, seg, _ in sh_segments(text):
        for t in seg:
            m = re.fullmatch(r"(\w+)=(.*)", t, re.S)
            if m and m.group(1) not in ("TREE",):
                out[m.group(1)] = m.group(2)
            elif t in ("export", "local", "readonly", "declare") or m:
                continue
            else:
                break
    return out


def expand(tok, env, depth=0):
    """Expand $NAME / ${NAME} / ${NAME:-x} from env; TREE and unknown names are left as written."""
    if depth > 6 or "$" not in tok:
        return tok

    def sub(m):
        name = m.group(1) or m.group(2)
        if name == "TREE" or name not in env:
            return m.group(0)
        return expand(env[name], env, depth + 1)
    return re.sub(r"\$\{(\w+)(?::?[-=+?][^}]*)?\}|\$(\w+)", sub, tok)


def command_word(toks):
    k = 0
    while k < len(toks) and (re.fullmatch(r"\w+=.*", toks[k], re.S) or toks[k] in (
            "env", "sudo", "command", "exec", "time", "nohup", "xcrun", "builtin")):
        k += 1
    return k


def check_shell_text(path, text, base_line=0, strict=False, env=None, depth=0):
    """strict: every command is treated like a codesign command (used for eval and sh -c strings)."""
    env = dict(env or {})
    env.update(sh_vars(text))
    for n, seg, raw in sh_segments(text):
        n += base_line
        ex = []
        for t in seg:
            e = expand(t, env)
            # an unquoted expansion word-splits; a value with spaces (CS="codesign --force") becomes words
            ex += e.split() if (e != t and re.fullmatch(r"\$\{?\w+\}?", t)) else [e]
        k = command_word(ex)
        cmd = ex[k] if k < len(ex) else ""
        args = ex[k + 1:]
        base = os.path.basename(cmd)
        codesign = strict or base == "codesign" or (cmd.startswith("$") and k < len(ex))
        verify = verify_only(ex)
        if not verify:
            deep = any(deep_tok(t) for t in ex)
            deepvar = any(re.search(r"\$\{?\w*deep\w*", t, re.I) for t in seg)
            if codesign:
                deep = deep or any("deep" in t.lower() or glued_fragment(t) for t in ex[k:])
            if deep or deepvar:
                hit(path, n, "codesign %s (or a deep flag variable/fragment) used outside a verify-only command: %s"
                    % (D, " ".join(seg)[:120]), raw)
        if any(BEP in t for t in ex):
            hit(path, n, "blanket " + BEP, raw)
        for t in ex:
            why = legacy_name(t)
            if why:
                hit(path, n, why, raw)
        if any(notarize_tok(t) for t in ex) and "--submit-existing" not in ex:
            hit(path, n, NOTE, raw)
        # eval / sh -c: the string is shell, checked strictly
        inner = None
        if base == "eval":
            inner = " ".join(args)
        elif base in SHELLS:
            for j, a in enumerate(args):
                if re.fullmatch(r"-[a-z]*c[a-z]*", a) and j + 1 < len(args):
                    inner = args[j + 1]
                    break
        if inner is not None and depth < 4:
            check_shell_text(path, inner, base_line=n - 1, strict=True, env=env, depth=depth + 1)


# ---------------------------------------------------------------- Python
def fold(node, env, partial=False):
    """String value of a constant-ish expression. With partial=True, unknown parts become UNK."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        return UNK if partial else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = fold(node.left, env, partial), fold(node.right, env, partial)
        if a is not None and b is not None:
            return a + b
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        for s_, n_ in ((node.left, node.right), (node.right, node.left)):
            sv = fold(s_, env, partial) if not (isinstance(s_, ast.Constant) and isinstance(s_.value, int)) else None
            if sv is not None:
                if isinstance(n_, ast.Constant) and isinstance(n_.value, int) and 0 <= n_.value <= 64:
                    return sv * n_.value
                return (sv + UNK) if partial else None
        return None
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                x = fold(v.value, env, partial)
                if x is None:
                    if not partial:
                        return None
                    x = UNK
                out.append(x)
        return "".join(out)
    return UNK if partial and isinstance(node, (ast.Attribute, ast.Subscript, ast.Call)) else None


STRINGY = (ast.Constant, ast.BinOp, ast.JoinedStr)


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
                and isinstance(p.body[0], ast.Expr) and isinstance(p.body[0].value, ast.Constant) \
                and isinstance(p.body[0].value.value, str):
            docs.add(p.body[0].value)
    # names assigned to a foldable value anywhere in the file (two passes for chains)
    env = {}
    for _ in range(3):
        for st in ast.walk(tree):
            if isinstance(st, ast.Assign):
                tg, val = st.targets, st.value
            elif isinstance(st, ast.AnnAssign) and st.value is not None:
                tg, val = [st.target], st.value
            else:
                continue
            v = fold(val, env)
            if v is not None:
                for t in tg:
                    if isinstance(t, ast.Name):
                        env[t.id] = v

    def stmt_of(n):
        while n in parents and not isinstance(n, ast.stmt):
            n = parents[n]
        return n

    seen = set()
    for node in ast.walk(tree):
        if node in docs or node in seen or not isinstance(node, STRINGY):
            continue
        if isinstance(node, ast.Constant) and not isinstance(node.value, str):
            continue
        par = parents.get(node)
        if isinstance(par, (ast.BinOp, ast.JoinedStr, ast.FormattedValue)) and fold(par, env, True) is not None:
            continue  # the outer expression is handled as one string
        s = fold(node, env, partial=True)
        if s is None:
            continue
        for sub in ast.walk(node):
            seen.add(sub)
        n = getattr(node, "lineno", 0)
        raw = lines[n - 1] if 0 < n <= len(lines) else ""
        st = stmt_of(node)
        strs = [fold(x, env, True) for x in ast.walk(st) if isinstance(x, STRINGY)]
        stoks = []
        for x in strs:
            if x:
                try:
                    stoks += shlex.split(x)
                except ValueError:
                    stoks += x.split()
        verify = any(t == V for t in stoks) and not any(t in SIGN_FLAGS for t in stoks)
        in_compare = isinstance(par, ast.Compare)
        try:
            toks = shlex.split(s)
        except ValueError:
            toks = s.split()
        if not verify and not in_compare:
            if s == D or any(deep_tok(t) or (UNK in t and glued_fragment(t)) for t in toks):
                hit(path, n, "%s in a Python string outside --verify: %r" % (D, s.replace(UNK, "{?}")[:100]), raw)
        if BEP in s and not in_compare:
            hit(path, n, "blanket " + BEP, raw)
        for t in (toks if len(toks) > 1 else [s]):
            why = legacy_name(t)
            if not why:
                continue
            if t == SO and isinstance(par, ast.Call):
                args = [fold(a, env) for a in par.args]
                if node in par.args:
                    k = par.args.index(node)
                    if k > 0 and args[k - 1] == "tools":
                        continue
            if not in_compare:
                hit(path, n, why, raw)
        if any(notarize_tok(t) for t in toks) and "--submit-existing" not in toks and not in_compare:
            hit(path, n, NOTE, raw)


# ---------------------------------------------------------------- YAML
TRUTHY = ("true", "yes", "on", "y")


def strip_yaml_comment(line):
    out, q = [], None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out)


def yaml_scalar(v, anchors):
    """Plain value of a YAML scalar text: anchors/tags stripped, quotes removed, aliases resolved."""
    v = v.strip()
    while True:
        m = re.match(r"(&[^\s,{}\[\]]+|![^\s,{}\[\]]*|!<[^>]*>)\s*(.*)$", v, re.S)
        if not m:
            break
        v = m.group(2).strip()
    m = re.fullmatch(r"\*([^\s,{}\[\]]+)", v)
    if m:
        v = anchors.get(m.group(1), "")
    return v.strip().strip("'\"").strip()


KEYVAL = re.compile(r"""(?:^|[\s{,\-?])(["']?)([\w.-]+)\1\s*:(?:\s+|$)(.*)$""")


def check_yaml(path, text):
    lines = text.split("\n")
    anchors = {}
    i = 0
    while i < len(lines):
        n, line = i + 1, lines[i]
        code = strip_yaml_comment(line)
        for m in re.finditer(r"&([^\s,{}\[\]]+)\s+([^\s,{}\[\]#][^,{}\[\]#]*)", code):
            anchors[m.group(1)] = m.group(2).strip().strip("'\"")
        # every key: value pair on the line, including flow style {a: b, deep: yes}
        for piece in re.split(r"[{},\[\]]", code):
            m = KEYVAL.search(piece)
            if not m:
                continue
            key, val = m.group(2), m.group(3)
            if key.lower() == "deep" and yaml_scalar(val, anchors).lower() in TRUTHY:
                hit(path, n, "YAML deep: true", line)
        # block scalar: key: | / >- / |2 ... collect the more-indented lines and check them as shell
        bm = re.match(r"^(\s*)(?:-\s+)?(?:[\"']?[\w.-]+[\"']?\s*:\s*)?(?:&\S+\s+|!\S*\s+)*[|>][-+0-9]*\s*$", code)
        if bm and code.strip() not in ("|", ">"):
            ind = len(bm.group(1))
            j = i + 1
            body = []
            while j < len(lines) and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > ind):
                body.append(lines[j])
                j += 1
            check_shell_text(path, "\n".join(body), base_line=i + 1)
            i = j
            continue
        # plain scalar values (key: value or - value) are checked as shell too
        vm = re.match(r"^\s*(?:-\s+)?(?:[\"']?[\w.-]+[\"']?\s*:\s+)?(.+)$", code)
        if vm:
            val = yaml_scalar(vm.group(1), anchors)
            if re.search(r"deep|" + re.escape(SO) + "|" + re.escape(BU) + "|" + NO, val, re.I):
                check_shell_text(path, val, base_line=n - 1)
                for q in re.findall(r"\"([^\"]*)\"|'([^']*)'", vm.group(1)):
                    qq = q[0] or q[1]
                    if qq and qq != val:
                        check_shell_text(path, qq, base_line=n - 1)
        i += 1
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
                if str(k).lower() == "deep" and (v is True or str(v).lower() in TRUTHY):
                    hit(path, 0, "YAML deep: true at %s (PyYAML)" % "/".join(trail + [str(k)]))
                walk(v, trail + [str(k)])
        elif isinstance(o, list):
            for i_, v in enumerate(o):
                walk(v, trail + [str(i_)])
        elif isinstance(o, str) and re.search(r"deep|" + re.escape(SO) + "|" + re.escape(BU) + "|" + NO, o, re.I):
            check_shell_text(path, o)
    for d in docs:
        walk(d, [])


# ---------------------------------------------------------------- Markdown
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)")


def check_markdown(path, text):
    lines, i = text.split("\n"), 0
    list_indent = 0          # content indent of the list we are in (0 = not in a list)
    prev_blank = True
    while i < len(lines):
        line = lines[i]
        if re.match(r"\s*(```|~~~)", line):
            j = i + 1
            while j < len(lines) and not re.match(r"\s*(```|~~~)", lines[j]):
                j += 1
            check_shell_text(path, "\n".join(lines[i + 1:j]), base_line=i + 1)
            i, prev_blank = j + 1, False
            continue
        if not line.strip():
            prev_blank = True
            i += 1
            continue
        ind = len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())
        if prev_blank and ind >= list_indent + 4:
            j, block = i, []
            while j < len(lines) and (not lines[j].strip() or
                                      len(lines[j].expandtabs(4)) - len(lines[j].expandtabs(4).lstrip()) >= list_indent + 4):
                block.append(lines[j])
                j += 1
            check_shell_text(path, "\n".join(block), base_line=i)
            i, prev_blank = j, False
            continue
        m = LIST_ITEM.match(line.expandtabs(4))
        if m:
            list_indent = len(m.group(1)) + len(m.group(2)) + len(m.group(3))
        elif ind == 0:
            list_indent = 0
        prev_blank = False
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
    for h in sorted(set(hits), key=hits.index):
        print("FAIL " + h)
    if VERBOSE:
        print("scanned %d files under %s" % (len(files), ROOT))
    nh = len(set(hits))
    print("legacy-signing check: %s (%d hit%s, %d files)" % (
        "FAIL" if nh else "PASS", nh, "" if nh == 1 else "s", len(files)))
    sys.exit(1 if nh else 0)


if __name__ == "__main__":
    main()
