#!/usr/bin/env python3
"""Self-test — what an htm template renders from its OWN text is translated, or is a name that never is.

Text written straight into an html`` template reaches the screen as written, in every language. Two ways it went wrong:

  1. A JavaScript comment inside the template is not a comment there: it is markup, and it renders. One did, in the
     csqtt / WDTT interface page's header — "// i18n-keys: product names, the same in every language", written as a
     note for the i18n audit at the end of a template line (08e569c) and seen by the operator in the 1.8.8
     qualification.
  2. English written as template text, or handed to it as a bare value — "0 / 4 online" in every interface header,
     the whole "The panel is now reached at …" notice after an address change, the Revoke confirmation, "Download
     .conf", "1–10 of 50", "updating…", "up 3d", `${e.obf || "plain"}`. The Russian panel showed all of them in English
     and every audit stayed green: the catalogue audit skips a lone lowercase word as "probably a class name" and
     never reads a template's own text, and the bare-string audit needs a T() in the same expression to call a
     literal display text. Found by a Russian sweep of every screen plus this scan (1.8.8 qualification).

A small tokenizer walks every shipped SPA file (js/*.js, sub.js, turn-artifacts.js, app.js): code, its strings and
comments, regular-expression literals, and template literals with their `${…}` expressions nested to any depth. For
each html`` template it keeps track of whether it is inside a tag, and so reads:

  · comment-shaped text — a `//` or `/*` that starts a line or follows whitespace (never a URL: `https://` has a
    colon before its slashes);
  · every run of visible TEXT between tags and expressions that has a Latin letter in it — each must be one of the
    ALLOWED chunks below (product and protocol names, commands and paths the operator types, key names);
  · every string literal a text-position `${…}` can render as it is — the whole expression, or a branch of `?:`,
    `||`, `??`, `+` — each must be one of the ALLOWED values (type chips, ids handed to a function, colours).
    A literal that is compared, called on, used as a key or passed as an argument is not rendered and not read.
    An expression with a function body is left to the templates it returns, which are scanned on their own.

Anything else is English on a Russian screen: wrap it in T() / Trich() and give it a Russian line, or, if it really
is a name, add it here with the reason. An allowed entry that no longer occurs fails too, so the list stays exactly
what the code needs.

Run: python3 tests/spa_template_text_selftest.py      (0 = pass)
     --perturb         puts the rendered note back into js/iface.js's header → RED
     --perturb-word    puts "online" back as bare text in the interface header's online count → RED
     --perturb-value   puts `|| "plain"` back into Settings' fork bubble → RED
"""
import glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PERTURB = [a for a in sys.argv[1:] if a.startswith("--perturb")]
FAILS = []


def check(name, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + name + (("  — " + str(detail)[:1500]) if not ok else ""))
    if not ok:
        FAILS.append(name)


# Visible text that is the same in every language. Each group says why.
ALLOWED_CHUNKS = {
    "product, protocol and parameter names": {
        "AmneziaWG", "WireGuard", "WDTT", "CSQTT", "wdtt", "wg", "awg", "WG", "AWG 2.0", "AWG 3.1", "RAW", "VK", "QR",
        "DNS", "MTU", "IP", "AS", "HeaderProtectionKey", "RandomTrailers", "nginx", "Caddy", "amurcanov",
        "swg", "Panel",                                   # the brand, "swgPanel", split for its two colours
        "docker",                                         # the run-model tag beside a node's name (log budget table)
    },
    "commands, paths and files the operator types or greps": {
        "docker compose up -d", "systemctl status", "journalctl -u", "-e", "dkms status", "modprobe amneziawg",
        "swg-passwd", "swg-noded", "swg-node → ports:", "wg-keys.dat", "https://vk.ru/call/join/…",
        "ssh_user", "server_ip", "GET", "/metrics", "/api/v1/health", "/api/v1/servers", "/api/v1/servers/{id}/peers",
        "/api/v1/peers", "/api/v1/summary",
    },
    "keys and symbols": {
        "Ctrl", "Shift", "R",                               # the reload shortcut
        "v",                                                # a version's prefix: v1.8.8-beta
        "+n", "+y", "+x",                                   # the roster legend's markers
        "&nbsp;",
    },
}
ALLOWED_VALUES = {
    "type chips and product names": {"wg", "wg?", "awg", "awg?", "wdtt", "csqtt", "WDTT", "turn", "t", "raw TUN", "CLI"},
    "values handed to a function, not rendered by the template": {
        "user",                                             # a noun for plural() / pluralWord()
        "empty", "unassigned",                              # status ids for lifecycleIcon() / badgeWithReason()
        "baremetal", "docker", "#60a5fa", "#c084e8",        # a run kind and its colour for runLabel() / kindLabel()
        "amurcanov",                                        # a fork id for forkLabel()
        "auto",                                             # `(ps.mesh_mode || "auto") === "auto"` — compared
    },
    "text of a file, a command or an address": {"conf", "PORT", '/udp"', "http://127.0.0.1:"},
}

REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
KEYWORDS = ("return", "typeof", "case", "in", "of", "delete", "void", "throw", "else", "do")


def walk(src):
    """→ (comments, chunks, spans) of every html`` template: comment-shaped text, visible text runs, and the source of
    each `${…}` in a TEXT position (not inside a tag), each with its line."""
    comments, chunks, spans = [], [], []
    i, n = 0, len(src)
    stack = ["code"]          # "code" | "tpl"; each ${ pushes code, its } pops back to the template
    depth = [0]               # brace depth per code frame (to find the } that closes a ${)
    is_html, tag, cur = [], [], []   # per template: html``?  tag state (None | "tag" | a quote)  the text run so far
    starts = [None]           # per code frame: where a text-position ${ began (None = not a text position)
    last_sig, last_word = "", ""     # last significant code token (regex vs division)

    def flush():
        if cur and cur[-1][1].strip():
            chunks.append((cur[-1][0], cur[-1][1]))
        if cur:
            cur[-1] = [None, ""]

    def line_at(k):
        return src.count("\n", 0, k) + 1

    while i < n:
        c = src[i]
        if stack[-1] == "tpl":
            st = tag[-1]
            if c == "\\":
                if is_html[-1] and st is None:
                    cur[-1][0] = cur[-1][0] or line_at(i)
                    cur[-1][1] += src[i:i + 2]
                i += 2; continue
            if c == "`":
                flush(); cur.pop(); stack.pop(); is_html.pop(); tag.pop()
                last_sig = "`"; i += 1; continue
            if c == "$" and src.startswith("${", i):
                text_pos = is_html[-1] and st is None
                if text_pos:
                    flush()
                stack.append("code"); depth.append(0); starts.append(i + 2 if text_pos else None)
                last_sig = "{"; i += 2; continue
            if is_html[-1]:
                if st is None:
                    if c == "<":
                        flush(); tag[-1] = "tag"
                    else:
                        if c == "/" and i + 1 < n and src[i + 1] in "/*" and (src[i - 1] if i else "\n") in " \t\n":
                            comments.append((line_at(i), src[i:src.find("\n", i)].strip()[:90]))
                        if not c.isspace():
                            cur[-1][0] = cur[-1][0] or line_at(i)
                        cur[-1][1] += c
                elif st == "tag":
                    if c in "\"'":
                        tag[-1] = c
                    elif c == ">":
                        tag[-1] = None
                elif c == st:
                    tag[-1] = "tag"
            i += 1; continue
        # code
        if c in " \t\r\n":
            i += 1; continue
        if src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j; continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2); i = n if j < 0 else j + 2; continue
        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            i = j + 1; last_sig = c; continue
        if c == "`":
            stack.append("tpl"); is_html.append(last_word == "html"); tag.append(None); cur.append([None, ""])
            i += 1; continue
        if c == "/":
            if last_sig in REGEX_AFTER or last_sig == "" or last_word in KEYWORDS:
                j, cls = i + 1, False       # a regular-expression literal
                while j < n:
                    ch = src[j]
                    if ch == "\\":
                        j += 2; continue
                    if ch == "[":
                        cls = True
                    elif ch == "]":
                        cls = False
                    elif ch == "/" and not cls:
                        break
                    elif ch == "\n":
                        break
                    j += 1
                i = j + 1
                while i < n and src[i].isalpha():
                    i += 1
                last_sig = "r"; last_word = ""; continue
            last_sig = "/"; i += 1; continue
        if c == "{":
            depth[-1] += 1; last_sig = "{"; i += 1; last_word = ""; continue
        if c == "}":
            if depth[-1] == 0 and len(stack) > 1:      # closes a ${ … } → back to the template text
                s0 = starts.pop()
                if s0 is not None:
                    spans.append((line_at(s0), src[s0:i]))
                stack.pop(); depth.pop(); i += 1; continue
            depth[-1] -= 1; last_sig = "}"; i += 1; last_word = ""; continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            last_word = src[i:j]; last_sig = "a"; i = j; continue
        last_sig = c; last_word = ""; i += 1
    return comments, chunks, spans


def lex(expr):
    """Tokens of one `${…}`: ("s", text) a string, ("t", "") a nested template (skipped whole), ("w", word), ("o", op)."""
    toks, i, n = [], 0, len(expr)

    def skip_str(j):
        q = expr[j]; j += 1
        while j < n and expr[j] != q:
            j += 2 if expr[j] == "\\" else 1
        return j + 1

    def skip_tpl(j):
        j += 1
        while j < n:
            ch = expr[j]
            if ch == "\\":
                j += 2; continue
            if ch == "`":
                return j + 1
            if expr.startswith("${", j):
                d = 0; j += 2
                while j < n:
                    c2 = expr[j]
                    if c2 in "'\"":
                        j = skip_str(j); continue
                    if c2 == "`":
                        j = skip_tpl(j); continue
                    if c2 == "{":
                        d += 1
                    elif c2 == "}":
                        if d == 0:
                            j += 1; break
                        d -= 1
                    j += 1
                continue
            j += 1
        return n

    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1; continue
        if expr.startswith("//", i):
            k = expr.find("\n", i); i = n if k < 0 else k; continue
        if expr.startswith("/*", i):
            k = expr.find("*/", i + 2); i = n if k < 0 else k + 2; continue
        if c in "'\"":
            j = skip_str(i); toks.append(("s", expr[i + 1:j - 1])); i = j; continue
        if c == "`":
            i = skip_tpl(i); toks.append(("t", "")); continue
        m = re.match(r"===|!==|==|!=|\|\||\?\?|&&|=>|\?\.", expr[i:])
        if m:
            toks.append(("o", m.group(0))); i += len(m.group(0)); continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (expr[j].isalnum() or expr[j] in "_$"):
                j += 1
            toks.append(("w", expr[i:j])); i = j; continue
        toks.append(("o", c)); i += 1
    return toks


def rendered_literals(expr):
    """The string literals a text-position `${…}` can put on the page as they are."""
    if re.search(r"=>\s*\{|\bfunction\b", expr):
        return []           # a function body: what it renders is its own templates, scanned on their own
    toks, out = lex(expr), []
    for k, (kind, text) in enumerate(toks):
        if kind != "s" or not re.search(r"[A-Za-z]", text):
            continue
        prev = toks[k - 1][1] if k else "("
        nxt = toks[k + 1][1] if k + 1 < len(toks) else ")"
        if nxt in ("===", "!==", "==", "!=", ".", "?.", "[") or (nxt == ":" and prev != "?"):
            continue        # compared, called on, or an object key
        if prev in ("===", "!==", "==", "!=", ",", "["):
            continue        # compared, a later argument or an array item
        if prev == "(" and k >= 2 and (toks[k - 2][0] == "w" or toks[k - 2][1] in (")", "]")):
            continue        # a call's first argument
        if prev == ":" and k >= 2 and toks[k - 2][0] in ("w", "s") and (k < 3 or toks[k - 3][1] in ("{", ",")):
            continue        # an object property's value (a translate call's vars)
        if prev in ("?", ":", "||", "??", "(", "+") or k == 0:
            out.append(text)
    return out


def scan(srcs):
    comments, chunk_hits, value_hits, seen_chunks, seen_values = [], [], [], set(), set()
    allowed_c = set().union(*ALLOWED_CHUNKS.values())
    allowed_v = set().union(*ALLOWED_VALUES.values())
    for f, s in srcs.items():
        rel = os.path.relpath(f, ROOT)
        cm, ch, sp = walk(s)
        comments += ["%s:%d  %s" % (rel, l, t) for l, t in cm]
        for l, t in ch:
            t = " ".join(t.split())
            if not re.search(r"[A-Za-z]", t):
                continue
            seen_chunks.add(t)
            if t not in allowed_c:
                chunk_hits.append("%s:%d  %r" % (rel, l, t))
        for l, e in sp:
            for v in rendered_literals(e):
                seen_values.add(v)
                if v not in allowed_v:
                    value_hits.append("%s:%d  %r" % (rel, l, v))
    return comments, chunk_hits, value_hits, allowed_c - seen_chunks, allowed_v - seen_values


files = sorted(glob.glob(os.path.join(ROOT, "js", "*.js"))
               + [os.path.join(ROOT, f) for f in ("sub.js", "turn-artifacts.js", "app.js")])
files = [f for f in files if os.path.exists(f) and "/js/lang/" not in f]
srcs = {f: open(f, encoding="utf-8").read() for f in files}


def plant(rel, anchor, new):
    f = os.path.join(ROOT, rel)
    assert srcs[f].count(anchor) == 1, "perturbation anchor missing in %s — would FALSE-PASS" % rel
    srcs[f] = srcs[f].replace(anchor, new)


if "--perturb" in PERTURB:
    f = os.path.join(ROOT, "js", "iface.js")
    a = '${kindLabel}</span>'
    assert srcs[f].count(a) == 1, "perturbation anchor missing — would FALSE-PASS"
    k = srcs[f].index(a)
    e = srcs[f].index("\n", k)
    srcs[f] = srcs[f][:e] + "   // i18n-keys: product names, the same in every language" + srcs[f][e:]
if "--perturb-word" in PERTURB:
    plant("js/views.js", '${(total != null ? " / " + total : "") + " " + T("val|online")}`',
          '${total != null ? " / " + total : ""} online`')
if "--perturb-value" in PERTURB:
    plant("js/screen-settings.js", '${p.obfLabel || T("tag|plain")}', '${p.obfLabel || "plain"}')

print("[the tokenizer sees what it must]")
probe = ('const a = html`<div>${x ? html`<b>${y}</b>` : null}</div>   // a note`;\n'
         'const u = html`<a href="https://x/y">z</a>`;\n'
         'const r = /\\/\\//g; const s = "//";\n'
         'const w = html`<span class="on">${n} online</span><b>WDTT</b>${T("Save")}`;\n'
         'const v = html`<i>${on ? "active" : T("idle")}</i>${st === "up" ? T("up") : "—"}${plural(n, "user")}${f(() => { return "x"; })}`;\n'
         'const p = `plain ${text} here`;\n')
cm, ch, sp = walk(probe)
check("a comment-shaped `//` in template text is found, through a nested template and its ${}", [l for l, _ in cm] == [1], cm)
check("…while a URL in an attribute, a regex of slashes and a string are not", len(cm) == 1, cm)
texts = [" ".join(t.split()) for _, t in ch]
check("visible text runs are read between tags and expressions — and only in html`` templates",
      "online" in texts and "WDTT" in texts and "z" in texts and not any("plain" in t or "here" in t for t in texts), texts)
check("…never from inside a tag (a class name, an attribute value)", not any("on" == t or "https" in t for t in texts), texts)
vals = [v for _, e in sp for v in rendered_literals(e)]
check("a branch of a ternary is a rendered value; compared, argument and function-body literals are not",
      vals == ["active"], vals)

print("\n[the shipped SPA]")
comments, chunk_hits, value_hits, stale_c, stale_v = scan(srcs)
check("no `//` or `/*` comment inside an html`` template in %d files" % len(srcs), not comments, comments)
check("every visible text run with a Latin letter is an allowed name / command / symbol", not chunk_hits, chunk_hits)
check("every literal a text ${} renders as it is is an allowed name / id", not value_hits, value_hits)
check("every allowed entry still occurs (the lists hold exactly what the code needs)", not stale_c and not stale_v,
      sorted(stale_c) + sorted(stale_v))

print("\nFAIL (%d)" % len(FAILS) if FAILS else "\nALL PASS" + (" — but a perturbation was planted and should have gone RED" if PERTURB else ""))
sys.exit(1 if FAILS else (2 if PERTURB else 0))
