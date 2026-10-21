#!/usr/bin/env python3
"""Render a board and write figmaboard.spec.json (the layout spec the Figma script is built from).

Board kinds:
  design  a Claude Design canvas folder: <root>/project/canvas.json + <root>/project/*.dc.html
  html    one .html file, or a folder of .html files

What it does:
  1. Adds data-fb="nN" ids to element tags in the source files (in place) so later syncs can
     find each element again. Existing ids are kept.
  2. Renders every artboard in headless Chromium and measures it (scripts/js/extract.js).
  3. Turns repeated colors / spacing / radii into tokens and writes the spec.

Usage:
  python3 render_board.py --board PATH [--state DIR] [--assets DIR] [--width 1440]

  --state   where figmaboard.json and figmaboard.spec.json live (default: next to the board:
            <root>/project/_figmaboard for design canvases, the html folder for html boards)
  --assets  folder holding downloaded canvas uploads named <blob-id>.<ext> (design canvases)

Prints a JSON summary: artboards, changed source files (ids added), images to upload, spec size.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fbcommon as fb  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def discover(board, width):
    """Return (kind, root, title, artboards[]) where each artboard has key, file, x, y, w, h, page."""
    board = os.path.abspath(board)
    canvas = None
    for cand in (os.path.join(board, "project", "canvas.json"), os.path.join(board, "canvas.json")):
        if os.path.exists(cand):
            canvas = cand
    if canvas:
        proj = os.path.dirname(canvas)
        cj = fb.load_json(canvas)
        abs_ = []
        order = cj.get("order") or list(cj.get("boards", {}).keys())
        for key in order:
            b = cj["boards"].get(key)
            if not b or key.startswith("ds/"):
                continue
            abs_.append({"key": key, "file": os.path.join(proj, key), "x": b.get("x", 0), "y": b.get("y", 0),
                         "w": b.get("w", 1280), "h": b.get("h", 800), "page": b.get("expand") == "fill",
                         "title": b.get("title") or os.path.basename(key).replace(".dc.html", "")})
        return "design", os.path.dirname(proj) if os.path.basename(proj) == "project" else proj, cj.get("title") or "Board", abs_
    if os.path.isfile(board):
        files = [board]
        root = os.path.dirname(board)
    else:
        root = board
        files = sorted(os.path.join(board, f) for f in os.listdir(board)
                       if f.endswith(".html") and not f.startswith("_"))
    abs_ = []
    x = 0
    for f in files:
        w, h, page = width, 0, True
        m = re.search(r'<meta\s+name="figmaboard:size"\s+content="(\d+)x(\d+)"', fb.read_text(f))
        if m:
            w, h, page = int(m.group(1)), int(m.group(2)), True
        abs_.append({"key": os.path.relpath(f, root).replace(os.sep, "/"), "file": f, "x": x, "y": 0,
                     "w": w, "h": h, "page": page, "title": os.path.basename(f)[:-5]})
        x += w + 80
    return "html", root, os.path.basename(root.rstrip("/")) or "Board", abs_


def name_colors(specs, preset):
    """preset: {hex: (name, origin)} from CSS vars / data-props. Returns {hex: name}, origins."""
    use = Counter()
    role = {}

    def visit(n):
        for p in n.get("f", []):
            if isinstance(p, str):
                use[p] += 1
                role.setdefault(p, Counter())["bg"] += 1
        if n.get("fc"):
            use[n["fc"]] += 1
            role.setdefault(n["fc"], Counter())["text"] += 1
        for r in n.get("rn", []) or []:
            if r[2].get("fc"):
                use[r[2]["fc"]] += 1
                role.setdefault(r[2]["fc"], Counter())["text"] += 1
        if n.get("s"):
            use[n["s"]["c"]] += 1
            role.setdefault(n["s"]["c"], Counter())["border"] += 1
        for k in n.get("k", []):
            visit(k)

    for s in specs:
        visit(s)
    names, origins, taken, counters = {}, {}, set(), Counter()
    for hexv, pre in preset.items():
        nm, origin = pre[0], pre[1]
        full = pre[2] if len(pre) > 2 and pre[2] else "color/" + nm
        if hexv in use and full not in taken:
            names[hexv] = full
            origins[full] = origin
            taken.add(full)
    for hexv, _ in use.most_common(64):
        if hexv in names:
            continue
        r = role[hexv].most_common(1)[0][0]
        counters[r] += 1
        nm = f"{r}-{counters[r]}"
        names[hexv] = "color/" + nm
        origins["color/" + nm] = {"kind": "literal", "value": hexv}
    return names, origins


def apply_color_refs(n, names):
    if "f" in n:
        n["f"] = [("$" + names[p]) if isinstance(p, str) and p in names else p for p in n["f"]]
    if n.get("fc") in names:
        n["fc"] = "$" + names[n["fc"]]
    for r in n.get("rn", []) or []:
        if r[2].get("fc") in names:
            r[2]["fc"] = "$" + names[r[2]["fc"]]
    if n.get("s") and n["s"]["c"] in names:
        n["s"]["c"] = "$" + names[n["s"]["c"]]
    for k in n.get("k", []):
        apply_color_refs(k, names)


def scale_tokens(specs):
    gaps, rads = Counter(), Counter()

    def visit(n):
        L = n.get("L")
        if L:
            for v in [L[1], *L[2:6], L[9]]:
                if v and v > 0:
                    gaps[v] += 1
        r = n.get("r")
        for v in (r if isinstance(r, list) else [r] if r else []):
            if v and v < 9999:
                rads[v] += 1
        for k in n.get("k", []):
            visit(k)

    for s in specs:
        visit(s)
    fmt = lambda v: str(int(v)) if float(v).is_integer() else str(v).replace(".", "_")
    space = {f"space/{fmt(v)}": v for v, c in gaps.items() if c >= 2}
    radius = {f"radius/{fmt(v)}": v for v, c in rads.items() if c >= 2}
    return space, radius


def dc_color_props(files):
    """Read data-props color defaults from .dc.html files -> {hex: (name, origin)}."""
    out = {}
    for path, key in files:
        src = fb.read_text(path)
        m = re.search(r"data-props='([^']*)'", src)
        if not m:
            continue
        try:
            import html as h
            defs = json.loads(h.unescape(m.group(1)))
        except Exception:
            continue
        for k, d in defs.items():
            if isinstance(d, dict) and d.get("editor") == "color" and isinstance(d.get("default"), str):
                out.setdefault(fb.norm_hex(d["default"]), (k, {"kind": "prop", "file": key, "name": k}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True)
    ap.add_argument("--state")
    ap.add_argument("--assets")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--no-ids", action="store_true", help="do not write data-fb ids into the sources")
    a = ap.parse_args()

    kind, root, title, abs_ = discover(a.board, a.width)
    if not abs_:
        print(json.dumps({"error": "no artboards found in " + a.board}))
        sys.exit(1)
    state = a.state or (os.path.join(root, "project", "_figmaboard") if kind == "design" else root)
    man_path = os.path.join(state, fb.MANIFEST_NAME)
    man = fb.load_json(man_path) or fb.new_manifest(kind, title, root)

    # 1. ids
    changed = []
    nxt = man.get("nextId", 1)
    for ab in abs_:
        nxt = max(nxt, fb.max_fbid(fb.read_text(ab["file"])) + 1)
    if not a.no_ids:
        for ab in abs_:
            src = fb.read_text(ab["file"])
            new, nxt, added = fb.inject_ids(src, ab["file"].endswith(".dc.html"), nxt)
            if added:
                fb.write_text(ab["file"], new)
                changed.append({"file": ab["key"], "idsAdded": added})
    man["nextId"] = nxt

    # 2. render
    tmp = tempfile.mkdtemp(prefix="fbrender_")
    stub = fb.read_text(os.path.join(HERE, "js", "dc_stub.js"))
    extract = fb.read_text(os.path.join(HERE, "js", "extract.js"))
    dc_files = {}
    if kind == "design":
        proj = os.path.join(root, "project")
        for ab in abs_:
            dc_files[ab["key"]] = fb.read_text(ab["file"])
        for dirpath, _, fnames in os.walk(proj):
            for fn in fnames:
                if fn.endswith(".dc.html"):
                    rel = os.path.relpath(os.path.join(dirpath, fn), proj).replace(os.sep, "/")
                    dc_files.setdefault(rel, fb.read_text(os.path.join(dirpath, fn)))
    asset_map = {}
    if a.assets and os.path.isdir(a.assets):
        for fn in os.listdir(a.assets):
            asset_map[os.path.splitext(fn)[0]] = os.path.join(os.path.abspath(a.assets), fn)

    from playwright.sync_api import sync_playwright
    specs, out_abs, images, warnings, all_vars = [], [], set(), [], {}
    with sync_playwright() as p:
        exe = None
        for cand in ("/opt/pw-browsers/chromium", ):
            if os.path.exists(cand) and os.path.isfile(cand):
                exe = cand
        browser = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        for ab in abs_:
            if kind == "design":
                d = os.path.join(tmp, os.path.dirname(ab["key"]))
                os.makedirs(d, exist_ok=True)
                src = dc_files[ab["key"]]
                for bid, path in asset_map.items():
                    src = src.replace("/_blob/" + bid, "file://" + path)
                page_file = os.path.join(tmp, ab["key"].replace(".dc.html", ".render.html"))
                fb.write_text(page_file, src)
                fb.write_text(os.path.join(d, "support.js"), stub)
                w, h = ab["w"], ab["h"]
            else:
                page_file = ab["file"]
                w, h = ab["w"], ab["h"] or 900
            ctx = browser.new_context(viewport={"width": int(w), "height": int(h or 900)}, device_scale_factor=1)
            if kind == "design":
                ctx.add_init_script("window.__DC_FILES__ = %s; window.__DC_SELF__ = %s;" % (
                    json.dumps(dc_files), json.dumps(ab["key"])))
            pg = ctx.new_page()
            pg.goto("file://" + os.path.abspath(page_file), wait_until="load")
            if kind == "design":
                pg.wait_for_function("window.__DC_DONE__ === true", timeout=15000)
            pg.evaluate("document.fonts.ready.then(() => true)")
            pg.wait_for_timeout(150)
            if ab["page"]:
                full_h = pg.evaluate("Math.ceil(document.documentElement.scrollHeight)")
                if kind == "html" or full_h > h:
                    h = full_h
                    pg.set_viewport_size({"width": int(w), "height": int(h)})
                    pg.wait_for_timeout(100)
            if kind == "design":
                root_sel = "[data-fb-dcroot] > *"
            else:
                only = pg.evaluate("(() => { const k = Array.from(document.body.children).filter(e => !['SCRIPT','STYLE','LINK','TEMPLATE'].includes(e.tagName)); return k.length === 1 && k[0].hasAttribute('data-fb'); })()")
                root_sel = "body > [data-fb]" if only else "body"
            res = pg.evaluate(extract, {"root": root_sel, "name": ab["title"]})
            errs = pg.evaluate("window.__DC_ERRORS__ || []")
            ctx.close()
            if res.get("error"):
                warnings.append(f"{ab['key']}: {res['error']}")
                continue
            node = res["node"]
            node["w"], node["h"] = w, h
            node["sz"] = "XX"  # the artboard keeps its canvas size
            if errs:
                warnings.append(f"{ab['key']}: logic errors {errs}")
            specs.append(node)
            images.update(res["images"])
            all_vars.update(res.get("vars") or {})
            out_abs.append({"key": ab["key"], "x": ab["x"], "y": ab["y"], "w": w, "h": h, "node": node})
        browser.close()
    shutil.rmtree(tmp, ignore_errors=True)

    # 3. tokens
    preset = {}
    by_var = {o["name"]: t for t, o in (man.get("origins") or {}).items() if o.get("kind") == "cssvar"}
    for var, hexv in all_vars.items():
        tname = by_var.get(var)
        nm = tname[len("color/"):] if tname and tname.startswith("color/") else (tname or var.lstrip("-"))
        preset.setdefault(fb.norm_hex(hexv), (nm, {"kind": "cssvar", "name": var}, tname))
    if kind == "design":
        preset.update(dc_color_props([(ab["file"], ab["key"]) for ab in abs_]))
    names, origins = name_colors(specs, preset)
    for s in specs:
        apply_color_refs(s, names)
    space, radius = scale_tokens(specs)
    tokens = {"color": {v: k for k, v in names.items()}, "space": space, "radius": radius}

    img_list = sorted(images)
    spec = {"v": 1, "board": {"kind": kind, "title": title}, "tokens": tokens, "origins": origins,
            "artboards": out_abs, "images": img_list}
    os.makedirs(state, exist_ok=True)
    spec_path = os.path.join(state, fb.SPEC_NAME + ".pending")
    fb.save_json(spec_path, spec, compact=True)
    man["board"].update({"kind": kind, "title": title, "root": root})
    man["origins"] = origins
    fb.save_json(man_path, man)
    size = os.path.getsize(spec_path)
    print(json.dumps({"kind": kind, "title": title, "root": root, "state": state,
                      "artboards": [{"key": x["key"], "w": x["w"], "h": x["h"]} for x in out_abs],
                      "sourcesChanged": changed, "images": img_list,
                      "tokens": {k: len(v) for k, v in tokens.items()},
                      "spec": spec_path, "specBytes": size, "warnings": warnings}, indent=1))


if __name__ == "__main__":
    main()
