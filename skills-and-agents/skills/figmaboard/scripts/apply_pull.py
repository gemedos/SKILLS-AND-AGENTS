#!/usr/bin/env python3
"""Apply what came back from Figma to the board.

pull results (board <-> Figma already linked):
  python3 apply_pull.py --state DIR --result pull.result.json [more results...] [--images DIR] [--dry-run]
  Patches only the elements that changed in Figma (inline styles, text, added/removed elements,
  token values), records the new hashes, and re-renders the board so the baseline matches.

dump results (start from Figma):
  python3 apply_pull.py --dump --out NEW_BOARD_DIR --file-key KEY --result dump.result.json [--images DIR] [--single]
  Writes one .html file per Figma frame + tokens.css + figmaboard.json into NEW_BOARD_DIR.

--images: folder of images saved from download_assets, named <imageHash>.<ext> or <nodeId with - instead of :>.<ext>
Prints a JSON report: applied changes, things that need a decision, and images still missing.
"""
import argparse
import datetime
import html as htmlmod
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbcommon as fb  # noqa: E402
import fbhtml  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GEOM = ["position", "left", "top", "width", "height", "min-width", "min-height", "flex", "flex-shrink", "align-self"]
BG = ["background", "background-color", "background-image", "background-size", "background-position", "background-repeat"]
BORDER = ["border", "border-top", "border-right", "border-bottom", "border-left", "border-width", "border-color", "border-style"]
LAYOUT = ["display", "flex-direction", "gap", "padding", "justify-content", "align-items", "flex-wrap", "row-gap",
          "padding-top", "padding-right", "padding-bottom", "padding-left", "column-gap", "grid-template-columns"]
TEXT = ["font-family", "font-size", "font-weight", "font-style", "line-height", "letter-spacing", "text-align",
        "text-transform", "text-decoration", "white-space"]


def load_results(paths):
    out = []
    for p in paths:
        r = fb.load_json(p)
        if isinstance(r, list):
            r = r[0]
        if isinstance(r, dict) and isinstance(r.get("result"), dict):
            r = r["result"]
        out.append(r)
    return out


def image_index(d):
    idx = {}
    if d and os.path.isdir(d):
        for fn in os.listdir(d):
            idx[os.path.splitext(fn)[0]] = os.path.join(os.path.abspath(d), fn)
    return idx


def slug(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or "Frame"


# ------------------------------------------------------------------ comparison
def num_eq(a, b, tol=0.6):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return a == b


def resolve_paint(p, tokens):
    if isinstance(p, str) and p.startswith("$"):
        return fb.norm_hex(tokens.get("color", {}).get(p[1:], p))
    return fb.norm_hex(p) if isinstance(p, str) else json.dumps(p, sort_keys=True)


def paints_eq(a, b, tokens, images):
    a, b = a or [], b or []
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if isinstance(x, dict) and isinstance(y, dict) and x.get("img") and y.get("img"):
            known = images.get(x["img"])
            if known and known != y["img"]:
                return False
            if not known:
                images[x["img"]] = y["img"]
            continue
        if isinstance(x, dict) and isinstance(y, dict) and x.get("g") and y.get("g"):
            if abs(x["a"] - y["a"]) > 1 or len(x["st"]) != len(y["st"]):
                return False
            if any(fb.norm_hex(c1) != fb.norm_hex(c2) or not num_eq(p1, p2, 0.02) for (p1, c1), (p2, c2) in zip(x["st"], y["st"])):
                return False
            continue
        if resolve_paint(x, tokens) != resolve_paint(y, tokens):
            return False
    return True


def family_eq(base_stack, actual, font_map):
    fams = [s.strip().strip("'\"") for s in (base_stack or "").split(",") if s.strip()]
    cands = {f.lower() for f in fams}
    for f in fams:
        if font_map.get(f):
            cands.add(font_map[f].lower())
    generic = {"sans-serif": "inter", "system-ui": "inter", "serif": "noto serif", "monospace": "roboto mono"}
    for f in fams:
        if f.lower() in generic:
            cands.add(generic[f.lower()])
    return (actual or "").lower() in cands or (fams and font_map.get(fams[0], "").lower() == (actual or "").lower())


def diff(base, ent, parent_al, ctx):
    """Return set of changed property groups between baseline spec node and Figma entry."""
    ch = set()
    t = ent.get("t")
    tokens, images, fmap = ctx["tokens"], ctx["images"], ctx["fontMap"]
    if base.get("t") != t and not (base.get("t") == "F" and t == "S"):
        ch.add("type")
    abs_now = bool(ent.get("a"))
    if not ctx.get("root") and (not parent_al or abs_now):
        if not num_eq(base.get("x"), ent.get("x")) or not num_eq(base.get("y"), ent.get("y")):
            ch.add("pos")
    esz = ent.get("sz") or "XX"
    if t == "T":
        if ent.get("ar") not in ("WH",) and esz[0] == "X" and not num_eq(base.get("w"), ent.get("w"), 1.5):
            ch.add("size")
    else:
        if esz[0] == "X" and not num_eq(base.get("w"), ent.get("w"), 1.5):
            ch.add("size")
        if esz[1] == "X" and not num_eq(base.get("h"), ent.get("h"), 1.5):
            ch.add("size")

        def norm_sz(sz, is_al, in_al):
            out = ""
            for c in (sz or "XX"):
                if c == "H" and not is_al:
                    c = "X"
                if c == "F" and not in_al:
                    c = "X"
                out += c
            return out
        in_al = parent_al and not abs_now
        if norm_sz(base.get("sz"), bool(base.get("L")), in_al) != norm_sz(esz, bool(ent.get("L")), in_al):
            ch.add("size")
    if not num_eq(base.get("o", 1), ent.get("o", 1), 0.02):
        ch.add("opacity")
    if t == "T":
        if base.get("tx") != ent.get("tx") or json.dumps(base.get("rn") or []) != json.dumps(ent.get("rn") or []):
            if base.get("tx") != ent.get("tx") or len(base.get("rn") or []) != len(ent.get("rn") or []):
                ch.add("text")
        bf, ef = base.get("ft") or {}, ent.get("ft") or {}
        if not family_eq(bf.get("f"), ef.get("f"), fmap) or bf.get("w") != ef.get("w") or bool(bf.get("i")) != bool(ef.get("i")) \
                or not num_eq(bf.get("s"), ef.get("s"), 0.1) or not num_eq(bf.get("lh", 0), ef.get("lh", 0)) \
                or not num_eq(bf.get("ls", 0), ef.get("ls", 0), 0.05) or (bf.get("al") or "L") != (ef.get("al") or "L") \
                or bf.get("tc") != ef.get("tc") or bf.get("d") != ef.get("d"):
            ch.add("font")
        if resolve_paint(base.get("fc"), tokens) != resolve_paint(ent.get("fc"), tokens):
            ch.add("color")
        return ch
    if t == "S":
        if ch - {"pos", "size"} == set() and ent.get("svg"):
            ch.add("svg")
        return ch
    if t == "I":
        known = images.get(base.get("src"))
        if known and known != ent.get("src"):
            ch.add("image")
        elif not known and base.get("src"):
            images[base["src"]] = ent.get("src")
    elif not paints_eq(base.get("f"), ent.get("f"), tokens, images):
        ch.add("fill")
    bs, es = base.get("s"), ent.get("s")
    if bool(bs) != bool(es) or (bs and (resolve_paint(bs["c"], tokens) != resolve_paint(es["c"], tokens) or any(not num_eq(x, y, 0.1) for x, y in zip(bs["w"], es["w"])))):
        ch.add("stroke")
    br, er = base.get("r") or 0, ent.get("r") or 0
    if json.dumps(br) != json.dumps(er) and not (isinstance(br, (int, float)) and isinstance(er, (int, float)) and num_eq(br, er, 0.1)):
        ch.add("radius")
    if json.dumps(base.get("e") or []) != json.dumps(ent.get("e") or []):
        be, ee = base.get("e") or [], ent.get("e") or []
        if len(be) != len(ee) or any(any(not num_eq(x, y, 0.2) for x, y in zip(a[1:5], b[1:5])) or fb.norm_hex(a[5]) != fb.norm_hex(b[5]) for a, b in zip(be, ee)):
            ch.add("effects")
    if bool(base.get("c")) != bool(ent.get("c")) and not ctx.get("root"):
        ch.add("clip")
    bl, el = base.get("L"), ent.get("L")
    if bool(bl) != bool(el):
        ch.add("layout")
    elif bl and el:
        if bl[0] != el[0] or bl[6] != el[6] or bl[7] != el[7] or bool(bl[8]) != bool(el[8]) or \
                any(not num_eq(x, y) for x, y in zip(bl[1:6], el[1:6])) or not num_eq(bl[9], el[9]):
            if bl[6] == "BASELINE" and el[6] == "MIN" and not any(not num_eq(x, y) for x, y in zip(bl[1:6], el[1:6])):
                pass
            else:
                ch.add("layout")
    return ch


# ------------------------------------------------------------------ source editing
class Board:
    def __init__(self, man, state):
        self.man, self.state = man, state
        self.root = man["board"]["root"]
        self.kind = man["board"]["kind"]
        self.base_dir = os.path.join(self.root, "project") if self.kind == "design" else self.root
        self.files = {}
        for dp, _, fns in os.walk(self.base_dir):
            if "_figmaboard" in dp or "_figmaboard_out" in dp:
                continue
            for fn in fns:
                if fn.endswith((".html", ".css")):
                    p = os.path.join(dp, fn)
                    self.files[p] = fb.read_text(p)
        self.dirty = set()
        self._index()

    def _index(self):
        self.where = {}
        for p, s in self.files.items():
            for m in re.finditer(r'data-fb="([^"]+)"', s):
                self.where[m.group(1)] = p

    def tok(self, fid):
        p = self.where.get(fid)
        if not p:
            return None, None
        t = fb.find_by_fbid(self.files[p], fid)
        return p, t

    def set_style(self, fid, decls):
        p, t = self.tok(fid)
        if not t:
            return False
        self.files[p] = fb.set_style(self.files[p], t, decls)
        self.dirty.add(p)
        return True

    def inner(self, fid):
        p, t = self.tok(fid)
        if not t:
            return None, None, None
        r = fb.element_range(self.files[p], t)
        return p, r, self.files[p][r[1]:r[2]]

    def set_inner(self, fid, html):
        p, r, _ = self.inner(fid)
        if p is None:
            return False
        s = self.files[p]
        self.files[p] = s[:r[1]] + html + s[r[2]:]
        self.dirty.add(p)
        return True

    def remove(self, fid):
        p, r, _ = self.inner(fid)
        if p is None:
            return False
        s = self.files[p]
        a, b = r[0], r[3]
        ls = s.rfind("\n", 0, a)
        if s[ls + 1:a].strip() == "" and (b >= len(s) or s[b] == "\n"):
            a, b = ls + 1, b + 1 if b < len(s) else b
        self.files[p] = s[:a] + s[b:]
        self.dirty.add(p)
        self._index()
        return True

    def insert_child(self, parent_fid, after_fid, html):
        p, r, _ = self.inner(parent_fid)
        if p is None:
            return False
        s = self.files[p]
        pos = r[1]
        if after_fid and self.where.get(after_fid) == p:
            t = fb.find_by_fbid(s, after_fid)
            if t:
                pos = fb.element_range(s, t)[3]
        self.files[p] = s[:pos] + "\n" + html + s[pos:]
        self.dirty.add(p)
        self._index()
        return True

    def set_prop_default(self, ref, value):
        """ref = 'File.dc.html#prop' -> update data-props default."""
        fname, prop = ref.split("#", 1)
        path = os.path.join(self.base_dir, fname)
        s = self.files.get(path)
        if s is None:
            return False
        m = re.search(r"data-props='([^']*)'", s)
        if not m:
            return False
        defs = json.loads(htmlmod.unescape(m.group(1)))
        if prop not in defs:
            return False
        defs[prop]["default"] = value
        enc = json.dumps(defs, ensure_ascii=False, separators=(",", ":")).replace("&", "&amp;").replace("'", "&#39;")
        self.files[path] = s[:m.start(1)] + enc + s[m.end(1):]
        self.dirty.add(path)
        return True

    def retint(self, fids, old, new):
        """Replace a literal color inside the start tags of the given elements only."""
        n = 0
        pat = re.compile(re.escape(old) + r"(?![0-9a-f])", re.I)
        for fid in sorted(fids):
            p, t = self.tok(fid)
            if not t:
                continue
            s = self.files[p]
            tag = s[t[2]:t[3]]
            tag2, k = pat.subn(new, tag)
            if k:
                self.files[p] = s[:t[2]] + tag2 + s[t[3]:]
                self.dirty.add(p)
                n += k
        return n

    def replace_everywhere(self, pattern, repl, flags=0):
        n = 0
        for p, s in list(self.files.items()):
            s2, k = re.subn(pattern, repl, s, flags=flags)
            if k:
                self.files[p] = s2
                self.dirty.add(p)
                n += k
        return n

    def save(self):
        for p in self.dirty:
            fb.write_text(p, self.files[p])
        return sorted(os.path.relpath(p, self.root).replace(os.sep, "/") for p in self.dirty)


def decls_for(groups, ent, parent_L, ctx, is_root=False, base=None):
    """Map changed groups to CSS changes {prop: value|None}."""
    out = {}
    box = dict(fbhtml.box_css(ent, ctx, parent_L, is_root))
    if groups & {"pos", "size"}:
        for k in GEOM:
            out[k] = box.get(k)
        if is_root:
            for k in ("position", "left", "top", "flex", "flex-shrink", "align-self"):
                out.pop(k, None)
    if "fill" in groups:
        for k in BG:
            out[k] = box.get(k)
        out["background"] = None
        if not box.get("background-color"):
            out["background-color"] = "transparent"
        if not box.get("background-image"):
            out["background-image"] = None
    if "stroke" in groups:
        for k in BORDER:
            out[k] = box.get(k)
        if not any(box.get(k) for k in BORDER):
            out["border"] = "none"
    if "radius" in groups:
        out["border-radius"] = box.get("border-radius", "0")
    if "effects" in groups:
        out["box-shadow"] = box.get("box-shadow", "none")
    if "opacity" in groups:
        out["opacity"] = box.get("opacity")
    if "clip" in groups:
        out["overflow"] = box.get("overflow", "visible")
    if "layout" in groups:
        bl, el = (base or {}).get("L"), ent.get("L")
        if bl and el and bl[0] == el[0]:
            if not num_eq(bl[1], el[1]):
                out["gap"] = box.get("gap")
            if any(not num_eq(x, y) for x, y in zip(bl[2:6], el[2:6])):
                out["padding"] = box.get("padding")
                for k in ("padding-top", "padding-right", "padding-bottom", "padding-left"):
                    out[k] = None
            if bl[6] != el[6]:
                out["justify-content"] = box.get("justify-content")
            if bl[7] != el[7]:
                out["align-items"] = box.get("align-items")
            if bool(bl[8]) != bool(el[8]) or not num_eq(bl[9], el[9]):
                out["flex-wrap"] = box.get("flex-wrap", "nowrap")
                out["row-gap"] = box.get("row-gap")
        else:
            for k in LAYOUT:
                out[k] = box.get(k)
            if not el:
                out["display"] = "block"
    if "font" in groups or "color" in groups:
        tc = dict(fbhtml.text_css(ent, ctx))
        bf, ef = (base or {}).get("ft") or {}, ent.get("ft") or {}
        if "font" in groups:
            fields = {"f": "font-family", "w": "font-weight", "i": "font-style", "s": "font-size", "lh": "line-height",
                      "ls": "letter-spacing", "al": "text-align", "tc": "text-transform", "d": "text-decoration"}
            for key, prop in fields.items():
                same = family_eq(bf.get("f"), ef.get("f"), ctx.get("fontMap", {})) if key == "f" else \
                    (num_eq(bf.get(key) or 0, ef.get(key) or 0, 0.05) if key in ("s", "lh", "ls") else
                     (bf.get(key) or ("L" if key == "al" else 0)) == (ef.get(key) or ("L" if key == "al" else 0)))
                if not same:
                    out[prop] = tc.get(prop) or {"font-style": "normal", "letter-spacing": "0", "text-align": "left",
                                                  "text-transform": "none", "text-decoration": "none"}.get(prop)
        if "color" in groups:
            out["color"] = tc.get("color")
    return out


# ------------------------------------------------------------------ pull
def bound_elements(base, ref):
    """Source element ids whose baseline paints reference a token (loop copies collapse to their template)."""
    out = set()

    def visit(n, parent_id):
        fid = n.get("i")
        uses = ref in [p for p in n.get("f", []) or [] if isinstance(p, str)] or n.get("fc") == ref or \
            (n.get("s") or {}).get("c") == ref or any(r[2].get("fc") == ref for r in n.get("rn") or [])
        if uses and fid:
            src = fid.split("@")[0]
            if src.endswith("~t"):
                src = src[:-2]
            if "~" not in src:
                out.add(src)
        for k in n.get("k", []) or []:
            visit(k, fid)
    for ab in base.get("artboards", []):
        visit(ab["node"], None)
    return out


def apply_pull(a):
    man = fb.load_json(os.path.join(a.state, fb.MANIFEST_NAME))
    base = fb.load_json(os.path.join(a.state, fb.SPEC_NAME))
    results = load_results(a.result)
    board = Board(man, a.state)
    imgs = image_index(a.images)
    rel_img = lambda pth: os.path.relpath(pth, board.base_dir).replace(os.sep, "/")
    ctx = {"tokens": man.get("tokens", {}), "origins": man.get("origins", {}), "images": man.setdefault("images", {}),
           "fontMap": man.get("fontMap", {})}
    html_ctx = {"tokens": ctx["tokens"], "origins": ctx["origins"], "images": {}}
    report = {"applied": [], "needsDecision": [], "imagesNeeded": [], "newArtboards": [], "tokens": [], "unchanged": []}
    next_id = [man.get("nextId", 1)]

    def new_id_factory(nodes_map):
        def f(n):
            fid = f"n{next_id[0]}"
            next_id[0] += 1
            if n.get("id"):
                nodes_map[n["id"]] = fid
            return fid
        return f

    base_by_key = {ab["key"]: ab for ab in base["artboards"]}
    for res in results:
        for key, r in (res.get("abs") or {}).items():
            mab = man["artboards"].get(key)
            if r.get("same"):
                report["unchanged"].append(key)
                continue
            if r.get("gone"):
                report["needsDecision"].append({"artboard": key, "issue": "frame deleted in Figma",
                                                "options": ["delete the artboard from the board", "keep it and push it again"]})
                continue
            bab = base_by_key.get(key)
            # baseline index
            idx, parent_of, children_of = {}, {}, {}

            def index(n, parent):
                fid = n.get("i")
                if fid:
                    idx[fid] = n
                    parent_of[fid] = parent
                    children_of[fid] = [k.get("i") for k in n.get("k", []) or []]
                for k in n.get("k", []) or []:
                    index(k, n)
            index(bab["node"], None)
            nodes = mab["nodes"]
            fp = os.path.join(board.base_dir, key)
            if mab.get("boardHash") and os.path.exists(fp) and fb.file_hash(fp) != mab["boardHash"]:
                report["needsDecision"].append({"artboard": key, "issue": "changed on the board AND in Figma since the last sync",
                                                "action": "Figma changes were merged property by property; review the result"})
            entries = {e["id"]: e for e in r.get("ch", [])}
            new_nodes = [e for e in r.get("ch", []) if e["id"] not in nodes]
            new_ids = {e["id"] for e in new_nodes}
            for e in r.get("ch", []):
                if e["id"] in new_ids:
                    continue
                fid = nodes.get(e["id"])
                mab["hs"][e["id"]] = e["hh"]
                if not fid:
                    report["needsDecision"].append({"artboard": key, "node": e.get("n"), "issue": "changed node has no board element (anonymous)"})
                    continue
                b = idx.get(fid)
                if not b:
                    continue
                par = parent_of.get(fid)
                parent_L = par.get("L") if par else None
                is_root = par is None
                groups = diff(b, e, bool(parent_L), dict(ctx, root=is_root))
                if not groups:
                    continue
                target = fid
                if fid.endswith("~t"):
                    target = fid[:-2]
                    groups -= {"pos", "size"}
                elif "~" in fid:
                    report["needsDecision"].append({"artboard": key, "element": fid, "issue": "loose text edited in Figma", "figma": e.get("tx")})
                    continue
                if "@" in target or b.get("tp"):
                    report["needsDecision"].append({"artboard": key, "element": target, "issue": "element is generated by a <sc-for> loop; edit its data in renderVals()",
                                                    "changes": sorted(groups), "figma": {k: e.get(k) for k in ("tx", "f", "fc", "ft") if e.get(k) is not None}})
                    continue
                done = []
                if "type" in groups:
                    report["needsDecision"].append({"artboard": key, "element": target, "issue": f"layer type changed in Figma ({b.get('t')} -> {e.get('t')})"})
                    groups.discard("type")
                if "text" in groups:
                    p_, r_, inner = board.inner(target)
                    if inner is not None and "{{" in inner:
                        if b.get("tprop") and not e.get("rn"):
                            board.set_prop_default(b["tprop"], e["tx"])
                            done.append("text (prop default)")
                        else:
                            report["needsDecision"].append({"artboard": key, "element": target, "issue": "text comes from a template value", "figma": e["tx"]})
                    else:
                        board.set_inner(target, fbhtml.runs_html(e, html_ctx))
                        done.append("text")
                    groups.discard("text")
                if "svg" in groups:
                    p_, r_, _ = board.inner(target)
                    if p_ and e.get("svg"):
                        s = board.files[p_]
                        svg = re.sub(r"^<svg\b", f'<svg data-fb="{target}"', e["svg"].strip(), count=1)
                        board.files[p_] = s[:r_[0]] + svg + s[r_[3]:]
                        board.dirty.add(p_)
                        board._index()
                        done.append("svg")
                    groups.discard("svg")
                if "image" in groups:
                    pth = imgs.get(e["src"]) or imgs.get(e["id"].replace(":", "-"))
                    if pth:
                        p_, t_ = board.tok(target)
                        board.files[p_] = fb.set_attr(board.files[p_], t_, "src", rel_img(pth))
                        board.dirty.add(p_)
                        ctx["images"][e["src"]] = e["src"]
                        done.append("image")
                    else:
                        report["imagesNeeded"].append({"nodeId": e["id"], "imageHash": e["src"], "element": target})
                    groups.discard("image")
                if groups:
                    css = decls_for(groups, e, parent_L, dict(html_ctx, fontMap=ctx["fontMap"]), is_root, base=b)
                    # style values bound to Design-canvas props go to data-props defaults
                    for prop, ref in (b.get("sprops") or {}).items():
                        if prop in css and css[prop] is not None:
                            board.set_prop_default(ref, css.pop(prop))
                            done.append(f"{prop} (prop default)")
                    if css:
                        board.set_style(target, css)
                    done += sorted(groups)
                if done:
                    report["applied"].append({"artboard": key, "element": target, "changed": done})
            # new nodes
            tops = [e for e in new_nodes if e.get("p") not in new_ids]
            for top in tops:
                sub, _ = fbhtml.tree_from_entries([x for x in new_nodes], top["id"])
                pfid = nodes.get(top["p"])
                if not pfid:
                    report["needsDecision"].append({"artboard": key, "issue": "layer added in Figma under an unmapped parent", "node": top.get("n")})
                    continue
                pfid_el = pfid[:-2] if pfid.endswith("~t") else pfid
                par_entry = entries.get(top["p"]) or idx.get(pfid) or {}
                sibs = children_of.get(pfid, [])
                after = sibs[top["ix"] - 1] if 0 < top["ix"] <= len(sibs) else None
                html = fbhtml.node_html(sub, html_ctx, par_entry.get("L"), new_id_factory(nodes))
                for x in new_nodes:
                    mab["hs"][x["id"]] = x["hh"]
                if "@" in pfid_el:
                    report["needsDecision"].append({"artboard": key, "issue": "layer added inside a templated element", "html": html})
                    continue
                board.insert_child(pfid_el, after, html)
                report["applied"].append({"artboard": key, "element": pfid_el, "changed": [f"added {sub.get('n')}"]})
                if any(x.get("t") == "I" for x in new_nodes):
                    for x in new_nodes:
                        if x.get("t") == "I":
                            report["imagesNeeded"].append({"nodeId": x["id"], "imageHash": x.get("src")})
            for did in r.get("del", []):
                fid = nodes.pop(did, None)
                mab["hs"].pop(did, None)
                if not fid or "~" in fid or "@" in fid:
                    if fid and "@" in fid:
                        report["needsDecision"].append({"artboard": key, "element": fid, "issue": "deleted in Figma but generated by a loop"})
                    continue
                if board.remove(fid):
                    report["applied"].append({"artboard": key, "element": fid, "changed": ["removed"]})
            mab["fh"] = r.get("fh", mab["fh"])
        # frames added in Figma
        for nf in res.get("nf", []) or []:
            report["newArtboards"].append(add_artboard(board, man, nf, html_ctx, new_id_factory))
        # token values
        for name, val in (res.get("vars") or {}).items():
            group = name.split("/")[0]
            if group == "color":
                old = fb.norm_hex(ctx["tokens"].get("color", {}).get(name))
                new = fb.norm_hex(val)
                if old and old != new:
                    o = ctx["origins"].get(name, {"kind": "literal"})
                    n = 0
                    if o.get("kind") == "cssvar":
                        n += board.replace_everywhere(r"(" + re.escape(o["name"]) + r"\s*:\s*)([^;}\n]+)", lambda m: m.group(1) + fb.hex_to_css(new))
                    elif o.get("kind") == "prop":
                        n += int(board.set_prop_default(o["file"] + "#" + o["name"], new))
                    # elements whose paint is bound to this token in Figma: swap the literal value in their own tag
                    n += board.retint(bound_elements(base, "$" + name), old, new)
                    ctx["tokens"]["color"][name] = new
                    report["tokens"].append({"token": name, "from": old, "to": new, "edits": n})
            elif group in ("space", "radius"):
                old = ctx["tokens"].get(group, {}).get(name)
                if old is not None and not num_eq(old, val, 0.01):
                    ctx["tokens"][group][name] = val
                    report["tokens"].append({"token": name, "from": old, "to": val, "note": "applied through the elements bound to it"})
    if a.dry_run:
        report["dryRun"] = True
        print(json.dumps(report, indent=1))
        return
    changed = board.save()
    man["nextId"] = next_id[0]
    man["tokens"] = ctx["tokens"]
    man["lastSync"] = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "dir": "figma->board"}
    fb.save_json(os.path.join(a.state, fb.MANIFEST_NAME), man)
    report["filesChanged"] = changed
    # re-render so the baseline matches the patched board (local only, no Figma call)
    if changed or report["newArtboards"]:
        rebaseline(man, a.state, report)
    print(json.dumps(report, indent=1))


def rebaseline(man, state, report):
    board_arg = man["board"]["root"]
    r = subprocess.run([sys.executable, os.path.join(HERE, "render_board.py"), "--board", board_arg, "--state", state],
                       capture_output=True, text=True)
    if r.returncode != 0:
        report["rebaseline"] = "failed: " + r.stderr[-500:]
        return
    pending = fb.load_json(os.path.join(state, fb.SPEC_NAME + ".pending"))
    base = fb.load_json(os.path.join(state, fb.SPEC_NAME)) or {"artboards": []}
    keep = {ab["key"] for ab in base["artboards"]}
    base["artboards"] = [ab for ab in pending["artboards"] if ab["key"] in keep or ab["key"] in man["artboards"]]
    base["tokens"], base["origins"] = man.get("tokens", pending["tokens"]), pending.get("origins", {})
    fb.save_json(os.path.join(state, fb.SPEC_NAME), base, compact=True)
    m2 = fb.load_json(os.path.join(state, fb.MANIFEST_NAME))
    root = m2["board"]["root"]
    for key, ab in m2["artboards"].items():
        f = os.path.join(root, "project", key) if m2["board"]["kind"] == "design" else os.path.join(root, key)
        if os.path.exists(f):
            ab["boardHash"] = fb.file_hash(f)
    fb.save_json(os.path.join(state, fb.MANIFEST_NAME), m2)
    report["rebaseline"] = "ok"


def add_artboard(board, man, nf, ctx, new_id_factory):
    """A frame added in Figma becomes a new artboard file."""
    root_entry, _ = fbhtml.tree_from_entries(nf["nodes"], nf["id"])
    nodes_map = {}
    body = fbhtml.node_html(root_entry, ctx, None, new_id_factory(nodes_map), is_root=True)
    name = slug(nf["name"])
    hs = {e["id"]: e["hh"] for e in nf["nodes"]}
    if man["board"]["kind"] == "design":
        key = name + ".dc.html"
        path = os.path.join(board.base_dir, key)
        doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>%s</title>\n<script src="./support.js"></script>\n</head>\n<body>\n<x-dc>\n<helmet>\n<style>\nbody{margin:0}\n</style>\n</helmet>\n%s\n</x-dc>\n'
               '<script type="text/x-dc" data-dc-script data-props=\'{"$preview":{"width":%s,"height":%s}}\'>\nclass Component extends DCLogic {\nrenderVals() {\nreturn {};\n}\n}\n</script>\n</body>\n</html>\n') % (
            htmlmod.escape(nf["name"]), body, int(root_entry["w"]), int(root_entry["h"]))
        cj_path = os.path.join(board.base_dir, "canvas.json")
        cj = fb.load_json(cj_path)
        mx = max([b["x"] + b["w"] for b in cj["boards"].values()] or [0])
        cj["boards"][key] = {"x": mx + 80, "y": 0, "w": int(root_entry["w"]), "h": int(root_entry["h"]), "title": nf["name"]}
        cj.setdefault("order", []).append(key)
        fb.save_json(cj_path, cj)
    else:
        key = name + ".html"
        path = os.path.join(board.base_dir, key)
        doc = fbhtml.page_html(nf["name"], body, ctx).replace("<head>\n", f'<head>\n<meta name="figmaboard:size" content="{int(root_entry["w"])}x{int(root_entry["h"])}">\n', 1)
    fb.write_text(path, doc)
    man["artboards"][key] = {"frameId": nf["id"], "fh": None, "nodes": nodes_map, "hs": hs, "boardHash": None}
    return {"artboard": key, "file": path}


# ------------------------------------------------------------------ dump (Figma-first)
def apply_dump(a):
    results = load_results(a.result)
    out = os.path.abspath(a.out)
    os.makedirs(out, exist_ok=True)
    first = results[0]
    vars_ = {}
    for r in results:
        vars_.update(r.get("vars") or {})
    colors = {k: fb.norm_hex(v) for k, v in vars_.items() if isinstance(v, str)}
    origins = {k: {"kind": "cssvar", "name": fbhtml.css_var(k)} for k in colors}
    imgs = image_index(a.images)
    man = fb.new_manifest("html", first.get("page", {}).get("name") or "Figma board", out)
    man["figma"].update({"fileKey": a.file_key, "pageId": first["page"]["id"], "collection": first.get("coll"),
                         "noNew": bool(a.single)})
    man["tokens"] = {"color": colors, "space": {}, "radius": {}}
    man["origins"] = origins
    ctx = {"tokens": man["tokens"], "origins": origins, "images": {}}
    next_id = [1]
    report = {"files": [], "imagesNeeded": [], "frames": 0}
    sections = set()
    used = set()
    for r in results:
        for fr in r.get("frames", []):
            root, _ = fbhtml.tree_from_entries(fr["nodes"], fr["id"])
            for e in fr["nodes"]:
                if e.get("t") == "I" or any(isinstance(p, dict) and p.get("img") for p in e.get("f", []) or []):
                    h = e.get("src") or next(p["img"] for p in e["f"] if isinstance(p, dict) and p.get("img"))
                    pth = imgs.get(h) or imgs.get(e["id"].replace(":", "-"))
                    if pth:
                        dst = os.path.join(out, "assets", os.path.basename(pth))
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if not os.path.exists(dst):
                            with open(pth, "rb") as s, open(dst, "wb") as d:
                                d.write(s.read())
                        ctx["images"][h] = "assets/" + os.path.basename(pth)
                    else:
                        report["imagesNeeded"].append({"nodeId": e["id"], "imageHash": h})
            nodes_map = {}

            def nid(n):
                fid = f"n{next_id[0]}"
                next_id[0] += 1
                nodes_map[n["id"]] = fid
                return fid
            body = fbhtml.node_html(root, ctx, None, nid, is_root=True)
            key = slug(fr["name"]) + ".html"
            while key in used:
                key = key[:-5] + "-2.html"
            used.add(key)
            doc = fbhtml.page_html(fr["name"], body, ctx, "tokens.css" if colors else None)
            doc = doc.replace("<head>\n", f'<head>\n<meta name="figmaboard:size" content="{int(root["w"])}x{int(root["h"])}">\n', 1)
            fb.write_text(os.path.join(out, key), doc)
            man["artboards"][key] = {"frameId": fr["id"], "fh": fr["fh"], "nodes": nodes_map,
                                     "hs": {e["id"]: e["hh"] for e in fr["nodes"]}, "boardHash": None, "x": fr["x"], "y": fr["y"]}
            if fr.get("parent"):
                sections.add(fr["parent"])
            report["files"].append(key)
            report["frames"] += 1
    if colors:
        fb.write_text(os.path.join(out, "tokens.css"), ":root {\n" + "".join(f"  {fbhtml.css_var(k)}: {fb.hex_to_css(v)};\n" for k, v in colors.items()) + "}\n")
        report["files"].append("tokens.css")
    if len(sections) == 1 and not a.single:
        man["figma"]["sectionId"] = sections.pop()
    elif not a.single:
        man["figma"]["sectionId"] = None
    man["nextId"] = next_id[0]
    man["lastSync"] = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "dir": "figma->board"}
    fb.save_json(os.path.join(out, fb.MANIFEST_NAME), man)
    rebaseline(man, out, report)
    if any(r.get("more") for r in results):
        report["more"] = [r["more"] for r in results if r.get("more")]
    print(json.dumps(report, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state")
    ap.add_argument("--result", required=True, nargs="+")
    ap.add_argument("--images")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--file-key")
    ap.add_argument("--single", action="store_true", help="dump target was a single frame (don't watch the page for new frames)")
    a = ap.parse_args()
    if a.dump:
        apply_dump(a)
    else:
        apply_pull(a)


if __name__ == "__main__":
    main()
