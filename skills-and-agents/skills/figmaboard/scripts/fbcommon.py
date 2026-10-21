"""Shared helpers for figmaboard scripts: manifest I/O, HTML source scanning and editing.

The HTML helpers edit source text in place (minimal diffs) instead of re-serializing a DOM,
so the user's formatting, comments and Design-canvas template syntax survive.
"""
import hashlib
import html as htmlmod
import json
import os
import re

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW = {"script", "style", "textarea", "title"}
NO_ID = {"html", "head", "meta", "title", "link", "script", "style", "br", "wbr", "sc-for", "sc-if",
         "dc-import", "helmet", "x-dc", "template", "noscript", "base"}
SVG_CHILD_SKIP = True

MANIFEST_NAME = "figmaboard.json"
SPEC_NAME = "figmaboard.spec.json"


# ---------------------------------------------------------------- manifest
def load_json(path, default=None):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data, compact=False):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()[:12]


def new_manifest(kind, title, root):
    return {"v": 1, "board": {"kind": kind, "title": title, "root": root, "url": None},
            "figma": {"fileKey": None, "fileUrl": None, "pageId": None, "sectionId": None, "planKey": None},
            "artboards": {}, "tokens": {}, "origins": {}, "fontMap": {}, "images": {},
            "boardHashes": {}, "nextId": 1, "lastSync": None}


# ---------------------------------------------------------------- colors
def norm_hex(h):
    if not h or not isinstance(h, str) or not h.startswith("#"):
        return h
    h = h.lower()
    if len(h) == 4:
        h = "#" + "".join(c * 2 for c in h[1:])
    if len(h) == 9 and h.endswith("ff"):
        h = h[:7]
    return h


def hex_to_css(h):
    h = norm_hex(h)
    if len(h) == 9:
        r, g, b, a = (int(h[i:i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r}, {g}, {b}, {round(a / 255, 3)})"
    return h


# ---------------------------------------------------------------- HTML scanning
_name_re = re.compile(r"[A-Za-z][\w:.-]*")


def scan_tags(src, start=0, end=None):
    """Yield tag tokens: (kind, name, pos, endpos, selfclose, attr_span).
    kind is 'start' or 'end'. Skips comments and the bodies of raw-text elements."""
    end = len(src) if end is None else end
    i = start
    while i < end:
        lt = src.find("<", i, end)
        if lt < 0:
            return
        if src.startswith("<!--", lt):
            j = src.find("-->", lt + 4)
            i = end if j < 0 else j + 3
            continue
        if src.startswith("<!", lt) or src.startswith("<?", lt):
            j = src.find(">", lt)
            i = end if j < 0 else j + 1
            continue
        closing = src.startswith("</", lt)
        m = _name_re.match(src, lt + (2 if closing else 1))
        if not m:
            i = lt + 1
            continue
        name = m.group(0).lower()
        # find tag end, respecting quotes
        j = m.end()
        q = None
        while j < end:
            c = src[j]
            if q:
                if c == q:
                    q = None
            elif c in "\"'":
                q = c
            elif c == ">":
                break
            j += 1
        tag_end = j + 1
        if closing:
            yield ("end", name, lt, tag_end, False, None)
            i = tag_end
            continue
        selfclose = src[j - 1] == "/"
        yield ("start", name, lt, tag_end, selfclose, (m.end(), j - (1 if selfclose else 0)))
        i = tag_end
        if name in RAW and not selfclose:
            k = src.lower().find("</" + name, tag_end)
            i = end if k < 0 else k


def parse_attrs(s):
    """Parse an attribute string into an ordered list of (name, value or None, (start, end))."""
    out = []
    for m in re.finditer(r"""([^\s=/>"']+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?""", s):
        v = m.group(2)
        if v is not None and v[:1] in "\"'":
            v = v[1:-1]
        out.append((m.group(1).lower(), v, m.span()))
    return out


def get_attr(src, tok, name):
    a0, a1 = tok[5]
    for n, v, _ in parse_attrs(src[a0:a1]):
        if n == name:
            return htmlmod.unescape(v) if v is not None else ""
    return None


def element_range(src, tok):
    """Return (start, inner_start, inner_end, end) for the element whose start tag token is tok."""
    kind, name, pos, tend, selfclose, _ = tok
    if selfclose or name in VOID:
        return pos, tend, tend, tend
    depth = 0
    for t in scan_tags(src, tend):
        if t[1] != name:
            continue
        if t[0] == "start" and not (t[4] or name in VOID):
            depth += 1
        elif t[0] == "end":
            if depth == 0:
                return pos, tend, t[2], t[3]
            depth -= 1
    return pos, tend, len(src), len(src)


def x_dc_region(src):
    """For .dc.html files return (start, end) of the <x-dc> template body, else whole file."""
    m = re.search(r"<x-dc\b[^>]*>", src, re.I)
    if not m:
        return 0, len(src)
    e = src.lower().find("</x-dc>", m.end())
    return m.end(), (len(src) if e < 0 else e)


def find_by_fbid(src, fbid):
    for t in scan_tags(src):
        if t[0] == "start" and get_attr(src, t, "data-fb") == fbid:
            return t
    return None


def inject_ids(src, is_dc, next_id):
    """Add data-fb="nN" to every eligible start tag that lacks one. Returns (new_src, next_id, added)."""
    r0, r1 = x_dc_region(src) if is_dc else (0, len(src))
    edits = []
    svg_depth = 0
    helmet = False
    for t in scan_tags(src, r0, r1):
        kind, name = t[0], t[1]
        if name == "helmet":
            helmet = kind == "start" and not t[4]
            continue
        if name == "svg":
            if kind == "start" and not t[4]:
                if svg_depth == 0 and not helmet and get_attr(src, t, "data-fb") is None:
                    edits.append(t)
                svg_depth += 1
            elif kind == "end":
                svg_depth = max(0, svg_depth - 1)
            continue
        if kind != "start" or helmet or svg_depth or name in NO_ID or name.startswith("sc-"):
            continue
        if not is_dc and name in ("head",):
            continue
        if get_attr(src, t, "data-fb") is None:
            edits.append(t)
    added = 0
    for t in reversed(edits):
        ins = t[5][1]
        src = src[:ins] + f' data-fb="n{next_id + len(edits) - 1 - added}"' + src[ins:]
        added += 1
    return src, next_id + added, added


def max_fbid(src):
    ids = [int(m) for m in re.findall(r'data-fb="n(\d+)"', src)]
    return max(ids) if ids else 0


# ---------------------------------------------------------------- style attribute editing
def split_style(s):
    parts, depth, cur = [], 0, ""
    for c in s or "":
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == ";" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += c
    parts.append(cur)
    out = []
    for p in parts:
        if ":" in p:
            k, v = p.split(":", 1)
            out.append([k.strip().lower(), v.strip()])
    return out


def join_style(decls):
    return "; ".join(f"{k}: {v}" for k, v in decls if v is not None and v != "")


def set_style(src, tok, changes):
    """changes: {prop: value or None(remove)}. Returns new src."""
    a0, a1 = tok[5]
    attrs = parse_attrs(src[a0:a1])
    cur = None
    for n, v, span in attrs:
        if n == "style":
            cur = (v or "", span)
    decls = split_style(cur[0]) if cur else []
    keys = [d[0] for d in decls]
    for k, v in changes.items():
        if k in keys:
            decls[keys.index(k)][1] = v
        elif v is not None:
            decls.append([k, v])
    new = join_style(decls).replace('"', "&quot;")
    if cur:
        s0, s1 = cur[1]
        return src[:a0 + s0] + f'style="{new}"' + src[a0 + s1:]
    return src[:a1] + f' style="{new}"' + src[a1:]


def set_attr(src, tok, name, value):
    a0, a1 = tok[5]
    for n, v, span in parse_attrs(src[a0:a1]):
        if n == name:
            s0, s1 = span
            return src[:a0 + s0] + f'{name}="{htmlmod.escape(value, quote=True)}"' + src[a0 + s1:]
    return src[:a1] + f' {name}="{htmlmod.escape(value, quote=True)}"' + src[a1:]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, s):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(s)


# ---------------------------------------------------------------- Figma runtime
def _strip_js(js):
    return "\n".join(s for s in (ln.strip() for ln in js.splitlines()) if s and not s.startswith("//"))


def runtime_code():
    """JS appended after `const P = {...};`. Uses the terser build when it matches the source."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js")
    src = read_text(os.path.join(here, "figma_runtime.js"))
    mn, sha = os.path.join(here, "figma_runtime.min.js"), os.path.join(here, "figma_runtime.min.sha")
    if os.path.exists(mn) and os.path.exists(sha):
        if read_text(sha).strip() == hashlib.sha1(open(os.path.join(here, "figma_runtime.js"), "rb").read()).hexdigest()[:12]:
            return read_text(mn).strip() + "\nreturn await __fb(P);"
    return _strip_js(src)
