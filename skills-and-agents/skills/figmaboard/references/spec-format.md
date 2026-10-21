# fbspec: the layout format shared by both directions

`render_board.py` writes it (`figmaboard.spec.json.pending`, which becomes `figmaboard.spec.json`
after a push). The Figma runtime builds from it and reads Figma back into the same shape.
`apply_pull.py` compares the two. Keys are short to fit more board into one 50,000-character call.

## File
```json
{"v": 1, "board": {"kind": "design|html", "title": "..."},
 "tokens": {"color": {"color/accent": "#d97757"}, "space": {"space/24": 24}, "radius": {"radius/12": 12}},
 "origins": {"color/accent": {"kind": "prop|cssvar|literal", ...}},
 "artboards": [{"key": "Main.dc.html", "x": 0, "y": 0, "w": 880, "h": 560, "node": {...}}],
 "images": ["img/hero.png"]}
```

## Node
| key | meaning |
|---|---|
| `i` | board element id (`data-fb`): `n12`, `n12@0` loop copy, `n12~t` text inside a styled element, `n12~3` loose text |
| `t` | `F` frame, `T` text, `I` image, `S` vector/SVG |
| `n` | layer name |
| `x y w h` | box relative to the parent, px |
| `L` | auto layout `[dir H/V, gap, padTop, padRight, padBottom, padLeft, primaryAlign, counterAlign, wrap 0/1, rowGap]` (padding includes border width, because Figma strokes sit inside) |
| `sz` | sizing per axis: `X` fixed, `H` hug, `F` fill (`"FH"` = fill width, hug height) |
| `a` | 1 = absolutely positioned inside an auto-layout parent |
| `f` | fills: `"#rrggbb[aa]"`, `"$color/name"` (token), `{"g":"L","a":deg,"st":[[pos,"#hex"]]}`, `{"img":key,"fit":"FILL/FIT"}` |
| `s` | stroke `{"c": paint, "w": [top, right, bottom, left]}` |
| `r` | radius, a number or `[tl, tr, br, bl]` |
| `e` | shadows `[["D"/"I", x, y, blur, spread, "#rrggbbaa"]]` |
| `o` | opacity (when < 1) |
| `c` | 1 = clip content |
| `tx` | text characters |
| `ft` | font `{"f": family or CSS stack, "w": weight, "i": italic, "s": size, "lh": px (0 = auto), "ls": px, "al": L/C/R/J, "tc": U/L/T, "d": U/S}` |
| `fc` | text color (paint string) |
| `rn` | style runs `[[start, end, {"w","i","s","f","fc","d","href"}]]` |
| `ar` | text auto-resize `WH` (one line, hugs), `H` (wraps, fixed width), `N` (fixed box) |
| `src`, `fit` | image source (board path, or Figma image hash when read back) |
| `svg` | SVG markup |
| `k` | children |
| `tp`, `tprop`, `sprops` | canvas-only: loop copy, text bound to a prop, style values bound to props (never sent to Figma) |

## Read-back entries (pull/dump)
These are the same node keys plus `id` (Figma node id), `p` (parent id), `ix` (index in the
parent) and `hh` (hash). The hash covers what a person can edit on that layer (not layout-driven
positions or sizes), so reflow alone doesn't show up as a change.

## Hashes
`figmaboard.json` stores, per artboard: `frameId`, `fh` (hash of the whole frame), `hs` (node id ->
hash) and `nodes` (node id -> board element id). A pull sends `hs` to Figma and gets back only the
layers whose hash differs. A push compares `fh` first and refuses to overwrite a frame that was
edited in Figma since the last sync (`conflicts`).
