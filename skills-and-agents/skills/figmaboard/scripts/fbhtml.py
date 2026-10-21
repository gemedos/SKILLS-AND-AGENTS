"""fbspec -> HTML/CSS. Used for Figma-first boards and for elements added in Figma.

Also holds the CSS mapping used when patching existing elements (css_for_props), so both
directions share one definition of how a spec property becomes CSS.
"""
import html as htmlmod
import re

import fbcommon as fb

GENERIC_FALLBACK = {"serif": "serif", "mono": "monospace"}


def css_var(token):
    """'color/bg-1' -> '--color-bg-1'"""
    return "--" + re.sub(r"[^A-Za-z0-9_-]+", "-", token).strip("-").lower()


def paint_css(p, ctx):
    """Return a CSS color/background value for a spec paint."""
    if isinstance(p, str):
        if p.startswith("$"):
            name = p[1:]
            origin = ctx.get("origins", {}).get(name, {})
            val = ctx.get("tokens", {}).get("color", {}).get(name)
            if origin.get("kind") == "cssvar":
                return f"var({origin['name']}{', ' + fb.hex_to_css(val) if val else ''})"
            if ctx.get("use_vars"):
                return f"var({css_var(name)})"
            return fb.hex_to_css(val) if val else "inherit"
        return fb.hex_to_css(p)
    if isinstance(p, dict) and p.get("g"):
        stops = ", ".join(f"{fb.hex_to_css(c)} {round(pos * 100, 1)}%" for pos, c in p["st"])
        return f"linear-gradient({p['a']}deg, {stops})"
    if isinstance(p, dict) and p.get("img"):
        src = ctx.get("images", {}).get(p["img"])
        return f"url('{src}')" if src else None
    return None


def font_css(f, ctx):
    fam = f.get("f") or "Inter"
    if "," in fam:
        return fam
    first = fam.strip("'\"")
    generic = "serif" if re.search(r"serif|garamond|playfair|fraunces|lora|merriweather|georgia|times", first, re.I) and not re.search(r"sans", first, re.I) else \
        "monospace" if re.search(r"mono|code|courier", first, re.I) else "sans-serif"
    ctx.setdefault("fonts", set()).add((first, f.get("w", 400), f.get("i", 0)))
    return f"'{first}', {generic}"


def box_css(n, ctx, parent_L, is_root=False):
    """CSS declarations (ordered list of (prop, value)) for a frame/image/svg/text node."""
    d = []
    L = n.get("L")
    sz = n.get("sz", "XX")
    in_al = bool(parent_L) and not n.get("a")
    if is_root:
        d += [("position", "relative"), ("width", f"{n['w']}px"), ("min-height", f"{n['h']}px")]
    elif n.get("a") or (parent_L is None and not is_root):
        d += [("position", "absolute"), ("left", f"{n['x']}px"), ("top", f"{n['y']}px")]
    if not is_root:
        hz, vt = sz[0], sz[1]
        horiz = parent_L and parent_L[0] == "H"
        for axis, mode, dim in (("w", hz, "width"), ("h", vt, "height")):
            primary = in_al and ((axis == "w") == bool(horiz))
            if mode == "F" and in_al:
                if primary:
                    d += [("flex", "1 1 0"), ("min-" + dim, "0")]
                else:
                    d += [("align-self", "stretch")]
            elif mode == "H" or (n.get("t") == "T" and n.get("ar") == "WH") or (n.get("t") == "T" and axis == "h" and n.get("ar") == "H"):
                pass
            else:
                d.append((dim, f"{n[axis]}px"))
                if primary:
                    d.append(("flex-shrink", "0"))
    if n.get("t") != "T":
        bg = []
        colors = [p for p in n.get("f", []) or [] if isinstance(p, str)]
        layers = [p for p in n.get("f", []) or [] if not isinstance(p, str)]
        if colors:
            d.append(("background-color", paint_css(colors[-1], ctx)))
        for p in reversed(layers):
            v = paint_css(p, ctx)
            if v:
                bg.append(v)
        if bg:
            d.append(("background-image", ", ".join(bg)))
            if any(isinstance(p, dict) and p.get("img") for p in layers):
                fit = next(p.get("fit") for p in layers if p.get("img"))
                d += [("background-size", "contain" if fit == "FIT" else "cover"), ("background-position", "center"), ("background-repeat", "no-repeat")]
        s = n.get("s")
        if s:
            col = paint_css(s["c"], ctx)
            w = s["w"]
            if all(x == w[0] for x in w):
                d.append(("border", f"{w[0]}px solid {col}"))
            else:
                for side, x in zip(("top", "right", "bottom", "left"), w):
                    if x:
                        d.append((f"border-{side}", f"{x}px solid {col}"))
        r = n.get("r")
        if n.get("el"):
            d.append(("border-radius", "50%"))
        elif r:
            d.append(("border-radius", " ".join(f"{x}px" for x in r) if isinstance(r, list) else f"{r}px"))
        if n.get("e"):
            d.append(("box-shadow", ", ".join(f"{'inset ' if e[0] == 'I' else ''}{e[1]}px {e[2]}px {e[3]}px {e[4]}px {fb.hex_to_css(e[5])}" for e in n["e"])))
        if n.get("c"):
            d.append(("overflow", "hidden"))
    if n.get("o") is not None and n.get("o") < 1:
        d.append(("opacity", str(n["o"])))
    if L:
        bw = (n.get("s") or {}).get("w", [0, 0, 0, 0])
        pad = [max(0, round(L[2 + i] - bw[i], 1)) for i in range(4)]
        jc = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "SPACE_BETWEEN": "space-between"}.get(L[6], "flex-start")
        ai = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "BASELINE": "baseline"}.get(L[7], "flex-start")
        d += [("display", "flex"), ("flex-direction", "row" if L[0] == "H" else "column"), ("gap", f"{L[1]}px"),
              ("padding", " ".join(f"{x}px" for x in pad)), ("justify-content", jc), ("align-items", ai)]
        if L[8]:
            d += [("flex-wrap", "wrap"), ("row-gap", f"{L[9]}px")]
    kids = n.get("k") or []
    if kids and n.get("t") == "F" and (not L or any(k.get("a") for k in kids)):
        if not any(k == "position" for k, _ in d):
            d.append(("position", "relative"))
    return d


def text_css(n, ctx):
    f = n.get("ft") or {}
    d = [("margin", "0"), ("font-family", font_css(f, ctx)), ("font-size", f"{f.get('s', 16)}px"),
         ("font-weight", str(f.get("w", 400)))]
    if f.get("i"):
        d.append(("font-style", "italic"))
    d.append(("line-height", f"{f['lh']}px" if f.get("lh") else "normal"))
    if f.get("ls"):
        d.append(("letter-spacing", f"{f['ls']}px"))
    al = {"C": "center", "R": "right", "J": "justify"}.get(f.get("al"))
    if al:
        d.append(("text-align", al))
    tc = {"U": "uppercase", "L": "lowercase", "T": "capitalize"}.get(f.get("tc"))
    if tc:
        d.append(("text-transform", tc))
    if f.get("d"):
        d.append(("text-decoration", "underline" if f["d"] == "U" else "line-through"))
    if n.get("fc"):
        d.append(("color", paint_css(n["fc"], ctx)))
    d.append(("white-space", "pre-wrap" if n.get("ar") != "WH" else "pre"))
    return d


def runs_html(n, ctx):
    """Inner HTML for a text node, applying style runs as <span>/<a>."""
    tx = n.get("tx", "")
    runs = sorted(n.get("rn") or [], key=lambda r: r[0])
    out, pos = [], 0

    def esc(s):
        return htmlmod.escape(s).replace("\n", "<br>")
    for a, b, r in runs:
        if a < pos:
            continue
        out.append(esc(tx[pos:a]))
        st = []
        if r.get("w"):
            st.append(f"font-weight: {r['w']}")
        if r.get("i") is not None:
            st.append("font-style: " + ("italic" if r["i"] else "normal"))
        if r.get("s"):
            st.append(f"font-size: {r['s']}px")
        if r.get("f"):
            st.append(f"font-family: {font_css({'f': r['f']}, ctx)}")
        if r.get("fc"):
            st.append(f"color: {paint_css(r['fc'], ctx)}")
        if r.get("d"):
            st.append("text-decoration: " + {"U": "underline", "S": "line-through", "N": "none"}[r["d"]])
        inner = esc(tx[a:b])
        sty = f' style="{"; ".join(st)}"' if st else ""
        if r.get("href"):
            out.append(f'<a href="{htmlmod.escape(r["href"], quote=True)}"{sty}>{inner}</a>')
        else:
            out.append(f"<span{sty}>{inner}</span>")
        pos = b
    out.append(esc(tx[pos:]))
    return "".join(out)


def style_attr(decls):
    return fb.join_style(decls).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def node_html(n, ctx, parent_L, new_id, indent=0, is_root=False):
    """Render a spec subtree. new_id(node) -> data-fb id string (and records the mapping)."""
    pad = "  " * indent
    fid = new_id(n)
    attr = f' data-fb="{fid}"' if fid else ""
    t = n.get("t")
    if t == "T":
        d = box_css(n, ctx, parent_L, is_root) + text_css(n, ctx)
        return f'{pad}<p{attr} style="{style_attr(d)}">{runs_html(n, ctx)}</p>'
    if t == "S":
        d = box_css(n, ctx, parent_L, is_root)
        svg = n.get("svg")
        if svg:
            svg = re.sub(r"<script[\s\S]*?</script>", "", svg, flags=re.I)
            svg = re.sub(r"\son\w+=\"[^\"]*\"", "", svg)
            svg = re.sub(r"^<svg\b", f'<svg{attr} style="{style_attr(d)}"', svg.strip(), count=1)
            return pad + svg
        return f'{pad}<div{attr} style="{style_attr(d + [("background", "#eee")])}" title="vector (export too large)"></div>'
    if t == "I":
        d = box_css(n, ctx, parent_L, is_root) + [("object-fit", "contain" if n.get("fit") == "FIT" else "cover"), ("display", "block")]
        r = n.get("r")
        if r:
            d.append(("border-radius", " ".join(f"{x}px" for x in r) if isinstance(r, list) else f"{r}px"))
        src = ctx.get("images", {}).get(n.get("src"))
        alt = htmlmod.escape(n.get("n", ""), quote=True)
        if src:
            return f'{pad}<img{attr} src="{htmlmod.escape(src, quote=True)}" alt="{alt}" style="{style_attr(d)}">'
        return f'{pad}<img{attr} data-figma-image="{n.get("src")}" alt="{alt}" style="{style_attr(d + [("background", "#e5e5e5")])}">'
    d = box_css(n, ctx, parent_L, is_root)
    kids = n.get("k") or []
    if not kids:
        return f'{pad}<div{attr} style="{style_attr(d)}"></div>'
    inner = "\n".join(node_html(k, ctx, n.get("L"), new_id, indent + 1) for k in kids)
    return f'{pad}<div{attr} style="{style_attr(d)}">\n{inner}\n{pad}</div>'


def tree_from_entries(entries, root_id):
    """Rebuild nested spec nodes from flat pull/dump entries ({id,p,ix,...})."""
    by = {e["id"]: dict(e) for e in entries}
    for e in by.values():
        e["k"] = []
    for e in sorted(by.values(), key=lambda x: x.get("ix", 0)):
        if e["id"] != root_id and e.get("p") in by:
            by[e["p"]]["k"].append(e)
    for e in by.values():
        if not e["k"]:
            del e["k"]
    return by.get(root_id), by


def page_html(title, body, ctx, tokens_css_href=None):
    fonts = sorted(ctx.get("fonts", set()))
    fams = {}
    for fam, w, i in fonts:
        fams.setdefault(fam, set()).add((i, w))
    links = ""
    if fams:
        q = "&".join("family=" + fam.replace(" ", "+") + ":ital,wght@" + ";".join(f"{i},{w}" for i, w in sorted(v)) for fam, v in fams.items()
                     if fam.lower() not in ("inter",) or True)
        links = f'<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{q}&display=swap">\n'
    tok = f'<link rel="stylesheet" href="{tokens_css_href}">\n' if tokens_css_href else ""
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{htmlmod.escape(title)}</title>\n{links}{tok}<style>\n*, *::before, *::after {{ box-sizing: border-box; }}\nbody {{ margin: 0; }}\n</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n")
