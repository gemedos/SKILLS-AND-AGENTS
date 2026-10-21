// figmaboard: walk a rendered artboard and emit an fbspec node tree.
// Called by render_board.py via page.evaluate(EXTRACT, opts).
// opts = { root: CSS selector of the artboard root, name: artboard name }
(opts) => {
  const R = v => Math.round(v * 10) / 10;
  const toHex = (str) => {
    const m = str && str.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    const a = p.length > 3 ? p[3] : 1;
    if (a === 0) return null;
    const h = n => Math.round(n).toString(16).padStart(2, '0');
    return '#' + h(p[0]) + h(p[1]) + h(p[2]) + (a < 1 ? h(a * 255) : '');
  };
  const px = v => parseFloat(v) || 0;
  const SKIP = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'TITLE', 'HEAD', 'TEMPLATE', 'NOSCRIPT', 'BR', 'WBR']);
  const INLINE_TEXT = new Set(['A', 'SPAN', 'B', 'STRONG', 'I', 'EM', 'U', 'S', 'SMALL', 'MARK', 'CODE', 'SUB', 'SUP', 'ABBR', 'TIME', 'LABEL', 'Q', 'CITE', 'DEL', 'INS', 'KBD', 'BR', 'WBR']);
  const images = {};
  const warnings = [];

  function visible(el, cs) {
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    return true;
  }
  function isTextOnly(el) {
    // true if every descendant is text or an inline text element
    for (const n of el.childNodes) {
      if (n.nodeType === 3) continue;
      if (n.nodeType !== 1) continue;
      if (!INLINE_TEXT.has(n.tagName)) return false;
      const cs = getComputedStyle(n);
      if (cs.display !== 'inline' && n.tagName !== 'BR') return false;
      if (!isTextOnly(n)) return false;
    }
    return true;
  }
  function hasText(el) { return (el.textContent || '').trim().length > 0 || el.querySelector('br'); }

  function paintsOf(cs) {
    const f = [];
    const bg = toHex(cs.backgroundColor);
    if (bg) f.push(bg);
    const bi = cs.backgroundImage;
    if (bi && bi !== 'none') {
      const g = bi.match(/linear-gradient\((.*)\)$/);
      const u = bi.match(/url\(["']?([^"')]+)["']?\)/);
      if (g) {
        const parts = g[1].split(/,(?![^(]*\))/).map(s => s.trim());
        let a = 180;
        if (/deg$/.test(parts[0])) a = parseFloat(parts.shift());
        else if (/^to /.test(parts[0])) {
          const d = parts.shift();
          a = { 'to top': 0, 'to right': 90, 'to bottom': 180, 'to left': 270, 'to top right': 45, 'to right top': 45, 'to bottom right': 135, 'to right bottom': 135, 'to bottom left': 225, 'to left bottom': 225, 'to top left': 315, 'to left top': 315 }[d] ?? 180;
        }
        const st = parts.map((p, i) => {
          const c = p.match(/rgba?\([^)]*\)/);
          const pos = p.match(/(-?[\d.]+)%\s*$/);
          return [pos ? R(parseFloat(pos[1]) / 100) : R(i / Math.max(1, parts.length - 1)), c ? (toHex(c[0]) || '#00000000') : '#000000'];
        });
        f.push({ g: 'L', a, st });
      } else if (u) {
        const key = u[1];
        images[key] = 1;
        f.push({ img: key, fit: cs.backgroundSize === 'contain' ? 'FIT' : 'FILL' });
      }
    }
    return f;
  }
  function strokeOf(cs) {
    const w = ['Top', 'Right', 'Bottom', 'Left'].map(s => cs['border' + s + 'Style'] === 'none' ? 0 : px(cs['border' + s + 'Width']));
    if (!w.some(Boolean)) return null;
    const side = ['Top', 'Right', 'Bottom', 'Left'][w.findIndex(Boolean)];
    const c = toHex(cs['border' + side + 'Color']);
    if (!c) return null;
    return { c, w };
  }
  function radiusOf(cs, w, h) {
    const r = ['TopLeft', 'TopRight', 'BottomRight', 'BottomLeft'].map(k => {
      const v = cs['border' + k + 'Radius'];
      if (/%/.test(v)) return R(Math.min(w, h) * parseFloat(v) / 100);
      return px(v);
    });
    if (!r.some(Boolean)) return 0;
    return r.every(x => x === r[0]) ? r[0] : r;
  }
  function effectsOf(cs) {
    const s = cs.boxShadow;
    if (!s || s === 'none') return null;
    const out = [];
    s.split(/,(?![^(]*\))/).forEach(part => {
      const c = part.match(/rgba?\([^)]*\)/);
      const nums = part.replace(/rgba?\([^)]*\)/, '').replace('inset', '').trim().split(/\s+/).map(px);
      out.push([/inset/.test(part) ? 'I' : 'D', nums[0] || 0, nums[1] || 0, nums[2] || 0, nums[3] || 0, c ? (toHex(c[0]) || '#00000000') : '#00000040']);
    });
    return out;
  }
  function fontOf(cs) {
    const lh = cs.lineHeight === 'normal' ? 0 : R(px(cs.lineHeight));
    const ls = cs.letterSpacing === 'normal' ? 0 : R(px(cs.letterSpacing));
    const al = { left: 'L', start: 'L', center: 'C', right: 'R', end: 'R', justify: 'J' }[cs.textAlign] || 'L';
    const tc = { uppercase: 'U', lowercase: 'L', capitalize: 'T' }[cs.textTransform];
    const d = /underline/.test(cs.textDecorationLine) ? 'U' : /line-through/.test(cs.textDecorationLine) ? 'S' : undefined;
    const o = { f: cs.fontFamily, w: parseInt(cs.fontWeight) || 400, i: cs.fontStyle === 'italic' ? 1 : 0, s: R(px(cs.fontSize)), lh, ls, al };
    if (tc) o.tc = tc;
    if (d) o.d = d;
    return o;
  }
  function collapse(t, ws) {
    if (/pre/.test(ws)) return ws === 'pre-line' ? t.replace(/[ \t]+/g, ' ') : t;
    return t.replace(/\s+/g, ' ');
  }
  // Build characters + style runs for a text-only element
  function textOf(el, baseCs) {
    let chars = '';
    const runs = [];
    const base = fontOf(baseCs);
    const baseColor = toHex(baseCs.color);
    function walk(n, cs) {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) {
          let t = collapse(c.nodeValue, cs.whiteSpace);
          if (!/pre/.test(cs.whiteSpace) && (chars.endsWith(' ') || chars.endsWith('\n') || chars === '') && t.startsWith(' ')) t = t.slice(1);
          if (!t) continue;
          const start = chars.length;
          chars += t;
          const f = fontOf(cs);
          const r = {};
          if (f.w !== base.w) r.w = f.w;
          if (f.i !== base.i) r.i = f.i;
          if (f.s !== base.s) r.s = f.s;
          if (f.f !== base.f) r.f = f.f;
          if ((f.d || '') !== (base.d || '')) r.d = f.d || 'N';
          const col = toHex(cs.color);
          if (col !== baseColor) r.fc = col;
          const a = c.parentElement.closest('a[href]');
          if (a && el.contains(a)) r.href = a.getAttribute('href');
          if (Object.keys(r).length) runs.push([start, chars.length, r]);
        } else if (c.nodeType === 1) {
          if (c.tagName === 'BR') { chars += '\n'; continue; }
          walk(c, getComputedStyle(c));
        }
      }
    }
    walk(el, baseCs);
    chars = chars.replace(/ +\n/g, '\n').replace(/\n +/g, '\n');
    const trimmed = chars.replace(/\s+$/, '');
    const lead = chars.length - chars.replace(/^\s+/, '').length;
    const outRuns = runs.map(([s, e, r]) => [Math.max(0, s - lead), Math.min(trimmed.length - lead, e - lead), r]).filter(r => r[1] > r[0]);
    return { tx: trimmed.slice(lead), rn: outRuns.length ? outRuns : undefined, base, color: baseColor };
  }
  function textBox(el) {
    const rg = document.createRange();
    rg.selectNodeContents(el);
    const rects = Array.from(rg.getClientRects()).filter(r => r.width > 0 && r.height > 0);
    if (!rects.length) return null;
    const l = Math.min(...rects.map(r => r.left)), t = Math.min(...rects.map(r => r.top));
    const r = Math.max(...rects.map(r => r.right)), b = Math.max(...rects.map(r => r.bottom));
    const lines = new Set(rects.map(r => Math.round(r.top))).size;
    return { left: l, top: t, width: r - l, height: b - t, lines };
  }
  function nameOf(el) {
    const tag = el.tagName.toLowerCase();
    const lab = el.getAttribute('aria-label') || el.getAttribute('alt') || el.getAttribute('title');
    if (lab) return tag + ': ' + lab.slice(0, 40);
    if (el.id) return tag + '#' + el.id;
    const cl = (el.getAttribute('class') || '').trim().split(/\s+/)[0];
    return cl ? tag + '.' + cl : tag;
  }
  function textName(s) { const t = s.replace(/\s+/g, ' ').trim(); return t.length > 40 ? t.slice(0, 37) + '...' : t || 'Text'; }

  function svgOf(el) {
    const clone = el.cloneNode(true);
    const cs = getComputedStyle(el);
    const col = cs.color;
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const b = el.getBoundingClientRect();
    if (!clone.getAttribute('width')) clone.setAttribute('width', R(b.width));
    if (!clone.getAttribute('height')) clone.setAttribute('height', R(b.height));
    clone.removeAttribute('data-fb');
    let s = clone.outerHTML.replace(/currentColor/g, col).replace(/ data-fb="[^"]*"/g, '');
    // computed stroke/fill on the root when set by CSS
    return s;
  }

  // Decide layout for a container from its in-flow children boxes
  function layoutOf(el, cs, kids, box) {
    const pad = [px(cs.paddingTop) + px(cs.borderTopWidth), px(cs.paddingRight) + px(cs.borderRightWidth), px(cs.paddingBottom) + px(cs.borderBottomWidth), px(cs.paddingLeft) + px(cs.borderLeftWidth)].map(R);
    const flow = kids.filter(k => !k.abs);
    if (cs.display === 'flex' || cs.display === 'inline-flex') {
      const dir = /column/.test(cs.flexDirection) ? 'V' : 'H';
      const rev = /reverse/.test(cs.flexDirection);
      if (rev) return null;
      const jc = { 'flex-start': 'MIN', start: 'MIN', normal: 'MIN', left: 'MIN', center: 'CENTER', 'flex-end': 'MAX', end: 'MAX', right: 'MAX', 'space-between': 'SPACE_BETWEEN' }[cs.justifyContent] || 'MIN';
      const ai = { 'flex-start': 'MIN', start: 'MIN', center: 'CENTER', 'flex-end': 'MAX', end: 'MAX', baseline: 'BASELINE', stretch: 'MIN', normal: 'MIN' }[cs.alignItems] || 'MIN';
      const gap = dir === 'H' ? px(cs.columnGap) : px(cs.rowGap);
      const wrap = cs.flexWrap === 'wrap' && dir === 'H' ? 1 : 0;
      return { d: dir, gap: R(gap === 0 && cs.columnGap === 'normal' ? 0 : gap), pad, pa: jc, ca: ai, wrap, cgap: wrap ? R(px(cs.rowGap)) : 0, stretch: cs.alignItems === 'stretch' || cs.alignItems === 'normal' };
    }
    if (cs.display === 'grid' || cs.display === 'inline-grid') {
      // equal tracks -> wrapping horizontal auto layout
      const gai = { center: 'CENTER', end: 'MAX', 'flex-end': 'MAX' }[cs.alignItems] || 'MIN';
      return { d: 'H', gap: R(px(cs.columnGap)), pad, pa: 'MIN', ca: gai, wrap: 1, cgap: R(px(cs.rowGap)), stretch: false, grid: 1 };
    }
    // block flow: vertical stack with equal gaps -> auto layout, otherwise absolute
    if (flow.length === 0) return null;
    let ok = true, gaps = [];
    for (let i = 0; i < flow.length; i++) {
      const b = flow[i].box;
      if (i > 0) {
        const p = flow[i - 1].box;
        if (b.top < p.top + p.height - 1) { ok = false; break; }
        gaps.push(b.top - (p.top + p.height));
      }
    }
    if (ok && gaps.length && Math.max(...gaps) - Math.min(...gaps) > 1.5) ok = false;
    if (!ok) return null;
    const first = flow[0].box;
    const topPad = R(first.top - box.top);
    return { d: 'V', gap: R(gaps.length ? gaps[0] : 0), pad: [topPad, pad[1], pad[2], pad[3]], pa: 'MIN', ca: cs.textAlign === 'center' ? 'CENTER' : 'MIN', wrap: 0, cgap: 0, stretch: cs.textAlign !== 'center', block: 1 };
  }

  function fbid(el) { return el.getAttribute('data-fb') || null; }

  // returns spec node or null
  function walk(el, parentBox) {
    const cs = getComputedStyle(el);
    if (!visible(el, cs)) return null;
    if (cs.display === 'contents') {
      const out = [];
      for (const c of el.children) { const r = walk(c, parentBox); if (r) out.push(...(Array.isArray(r) ? r : [r])); }
      return out;
    }
    const b = el.getBoundingClientRect();
    const box = { left: b.left, top: b.top, width: b.width, height: b.height };
    const tag = el.tagName;
    const node = { i: fbid(el), n: nameOf(el), x: R(b.left - parentBox.left), y: R(b.top - parentBox.top), w: R(b.width), h: R(b.height) };
    const abs = cs.position === 'absolute' || cs.position === 'fixed';
    const extras = {};
    if (el.hasAttribute('data-fb-templated')) extras.tp = 1;
    if (el.hasAttribute('data-fb-textprop')) extras.tprop = el.getAttribute('data-fb-textprop');
    if (el.hasAttribute('data-fb-styleprops')) extras.sprops = JSON.parse(el.getAttribute('data-fb-styleprops'));
    Object.assign(node, extras);
    const op = parseFloat(cs.opacity);
    if (op < 1) node.o = R(op);

    if (tag === 'IMG') {
      if (b.width === 0 || b.height === 0) return null;
      const src = el.getAttribute('src') || '';
      node.t = 'I';
      if (/\.svg(\?|$)/i.test(src) && el.__fbsvg) { node.t = 'S'; node.svg = el.__fbsvg; }
      else { node.src = src; node.fit = cs.objectFit === 'contain' ? 'FIT' : 'FILL'; images[src] = 1; }
      const r = radiusOf(cs, b.width, b.height); if (r) node.r = r;
      const ef = effectsOf(cs); if (ef) node.e = ef;
      return { node, box, abs, cs, el };
    }
    if (tag === 'svg' || tag === 'SVG') {
      if (b.width === 0 || b.height === 0) return null;
      node.t = 'S';
      node.svg = svgOf(el);
      return { node, box, abs, cs, el };
    }
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      node.t = 'F';
      const f = paintsOf(cs); if (f.length) node.f = f;
      const s = strokeOf(cs); if (s) node.s = s;
      const r = radiusOf(cs, b.width, b.height); if (r) node.r = r;
      const val = el.value || el.getAttribute('placeholder') || '';
      const pad = [px(cs.paddingTop) + px(cs.borderTopWidth), px(cs.paddingRight) + px(cs.borderRightWidth), px(cs.paddingBottom) + px(cs.borderBottomWidth), px(cs.paddingLeft) + px(cs.borderLeftWidth)].map(R);
      node.L = ['H', 0, ...pad, 'MIN', 'CENTER', 0, 0];
      node.sz = 'XX';
      if (val) {
        const pcs = el.value ? cs : getComputedStyle(el, '::placeholder');
        const fo = fontOf(cs);
        node.k = [{ i: node.i ? node.i + '~t' : null, t: 'T', n: textName(val), x: pad[3], y: pad[0], w: R(b.width - pad[1] - pad[3]), h: R(b.height - pad[0] - pad[2]), tx: val, ft: fo, fc: toHex(pcs.color) || toHex(cs.color), ar: 'H', sz: 'FX' }];
      }
      return { node, box, abs, cs, el };
    }

    const f = paintsOf(cs); if (f.length) node.f = f;
    const s = strokeOf(cs); if (s) node.s = s;
    const r = radiusOf(cs, b.width, b.height); if (r) node.r = r;
    const e = effectsOf(cs); if (e) node.e = e;
    if (cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.overflow === 'clip') node.c = 1;

    // Text-only element
    if (hasText(el) && isTextOnly(el)) {
      const t = textOf(el, cs);
      const tb = textBox(el) || box;
      const decorated = f.length || s || e || px(cs.paddingTop) + px(cs.paddingLeft) + px(cs.paddingRight) + px(cs.paddingBottom) > 0 || (cs.display !== 'inline' && Math.abs(tb.width - b.width) > 2 && /flex|inline-block/.test(cs.display));
      const textNode = { t: 'T', tx: t.tx, ft: t.base, fc: t.color };
      if (t.rn) textNode.rn = t.rn;
      if (!decorated) {
        Object.assign(node, textNode);
        node.n = textName(t.tx);
        const single = tb.lines <= 1 && !/\n/.test(t.tx);
        node.ar = single ? 'WH' : 'H';
        if (/nowrap|pre$/.test(cs.whiteSpace)) node.ar = 'WH';
        return { node, box, abs, cs, el, text: true, single };
      }
      // decorated text: auto-layout frame + text child
      node.t = 'F';
      const pad = [px(cs.paddingTop) + px(cs.borderTopWidth), px(cs.paddingRight) + px(cs.borderRightWidth), px(cs.paddingBottom) + px(cs.borderBottomWidth), px(cs.paddingLeft) + px(cs.borderLeftWidth)].map(R);
      const isFlex = /flex/.test(cs.display);
      const pa = isFlex ? ({ center: 'CENTER', 'flex-end': 'MAX', end: 'MAX', 'space-between': 'SPACE_BETWEEN' }[cs.justifyContent] || 'MIN') : ({ C: 'CENTER', R: 'MAX' }[t.base.al] || 'MIN');
      const ca = isFlex ? ({ center: 'CENTER', 'flex-end': 'MAX', end: 'MAX' }[cs.alignItems] || 'MIN') : 'CENTER';
      node.L = ['H', 0, ...pad, pa, ca, 0, 0];
      const innerW = b.width - pad[1] - pad[3];
      const hugW = Math.abs(tb.width + pad[1] + pad[3] - b.width) < 2;
      const hugH = Math.abs(tb.height + pad[0] + pad[2] - b.height) < 2;
      node.sz = (hugW ? 'H' : 'X') + (hugH ? 'H' : 'X');
      const single = tb.lines <= 1 && !/\n/.test(t.tx);
      const child = Object.assign({ i: node.i ? node.i + '~t' : null, n: textName(t.tx), x: R(tb.left - b.left), y: R(tb.top - b.top), w: R(hugW || single ? tb.width : innerW), h: R(tb.height), ar: single ? 'WH' : 'H', sz: single || hugW ? 'HH' : 'FH' }, textNode);
      node.k = [child];
      return { node, box, abs, cs, el };
    }

    // Container
    node.t = 'F';
    const kids = [];
    for (const c of el.childNodes) {
      if (c.nodeType === 3) {
        if (!c.nodeValue.trim()) continue;
        // loose text inside a container with block children
        const rg = document.createRange(); rg.selectNodeContents(c);
        const rects = Array.from(rg.getClientRects()).filter(q => q.width > 0);
        if (!rects.length) continue;
        const l = Math.min(...rects.map(q => q.left)), t = Math.min(...rects.map(q => q.top));
        const rr = Math.max(...rects.map(q => q.right)), bb = Math.max(...rects.map(q => q.bottom));
        const bx = { left: l, top: t, width: rr - l, height: bb - t };
        const tx = collapse(c.nodeValue, cs.whiteSpace).trim();
        kids.push({ node: { i: node.i ? node.i + '~' + kids.length : null, t: 'T', n: textName(tx), x: R(l - b.left), y: R(t - b.top), w: R(rr - l), h: R(bb - t), tx, ft: fontOf(cs), fc: toHex(cs.color), ar: rects.length > 1 ? 'H' : 'WH', loose: 1 }, box: bx, abs: false, cs });
        continue;
      }
      if (c.nodeType !== 1 || SKIP.has(c.tagName)) continue;
      const r = walk(c, box);
      if (!r) continue;
      if (Array.isArray(r)) {
        // display:contents children: re-measure relative to this box
        for (const q of r) kids.push(q);
      } else kids.push(r);
    }
    // re-base display:contents grandchildren coordinates to this box
    for (const k of kids) { k.node.x = R(k.box.left - b.left); k.node.y = R(k.box.top - b.top); }
    const L = layoutOf(el, cs, kids, box);
    if (L) {
      node.L = [L.d, L.gap, ...L.pad, L.pa, L.ca, L.wrap, L.cgap];
      const innerW = b.width - L.pad[1] - L.pad[3];
      const innerH = b.height - L.pad[0] - L.pad[2];
      const flow = kids.filter(k => !k.abs);
      // container sizing: hug if content fits exactly
      let cw = 0, ch = 0;
      if (flow.length) {
        if (L.d === 'H' && !L.wrap) { cw = flow.reduce((a, k) => a + k.box.width, 0) + L.gap * (flow.length - 1); ch = Math.max(...flow.map(k => k.box.height)); }
        else if (L.d === 'V') { ch = flow.reduce((a, k) => a + k.box.height, 0) + L.gap * (flow.length - 1); cw = Math.max(...flow.map(k => k.box.width)); }
      }
      const hugW = flow.length && L.d === 'H' && !L.wrap && Math.abs(cw - innerW) < 1.5 && cs.flexGrow === '0' && !/^\d/.test(el.style.width);
      const hugH = flow.length && Math.abs(ch - innerH) < 1.5 && !/^\d/.test(el.style.height);
      node.sz = (hugW ? 'H' : 'X') + (hugH ? 'H' : 'X');
      for (const k of flow) {
        const kc = k.cs;
        let hs = k.node.sz ? k.node.sz[0] : 'X', vs = k.node.sz ? k.node.sz[1] : 'X';
        const grow = kc && parseFloat(kc.flexGrow) > 0;
        if (L.d === 'H') {
          if (grow && !L.wrap) hs = 'F';
          if (L.stretch && kc && kc.alignSelf !== 'center' && Math.abs(k.box.height - innerH) < 1.5 && !k.single) vs = 'F';
        } else {
          if (grow) vs = 'F';
          if (L.stretch && Math.abs(k.box.width - innerW) < 1.5) hs = 'F';
        }
        if (k.node.t === 'T') {
          if (hs === 'F') k.node.ar = 'H';
          if (k.node.ar === 'WH' && hs !== 'F') hs = 'H';
          if (k.node.ar === 'WH' || k.node.ar === 'H') vs = 'H';
        }
        k.node.sz = hs + vs;
      }
      for (const k of kids) if (k.abs) k.node.a = 1;
    }
    if (kids.length) node.k = kids.map(k => k.node);
    if (!node.k && !node.f && !node.s && !node.e && (b.width === 0 || b.height === 0)) return null;
    return { node, box, abs, cs, el };
  }

  const root = document.querySelector(opts.root);
  if (!root) return { error: 'root not found: ' + opts.root };
  const rb = root.getBoundingClientRect();
  const r = walk(root, { left: rb.left, top: rb.top });
  let node = Array.isArray(r) ? (r[0] && r[0].node) : r && r.node;
  if (!node) return { error: 'empty artboard' };
  node.x = 0; node.y = 0;
  node.n = opts.name || node.n;
  if (!node.f) {
    // artboard background from body/html if the root is transparent
    const bg = toHex(getComputedStyle(document.body).backgroundColor) || toHex(getComputedStyle(document.documentElement).backgroundColor) || '#ffffff';
    node.f = [bg];
  }
  node.c = 1;
  // collect CSS custom properties on :root for token naming
  const vars = {};
  for (const sh of Array.from(document.styleSheets)) {
    let rules; try { rules = sh.cssRules; } catch (e) { continue; }
    for (const ru of Array.from(rules || [])) {
      if (ru.selectorText && /^(:root|html|body)$/.test(ru.selectorText.trim())) {
        for (const p of Array.from(ru.style)) if (p.startsWith('--')) vars[p] = ru.style.getPropertyValue(p).trim();
      }
    }
  }
  const rs = getComputedStyle(document.documentElement);
  const probe = document.createElement('i');
  document.body.appendChild(probe);
  for (const p of Object.keys(vars)) {
    const raw = rs.getPropertyValue(p).trim() || vars[p];
    if (!CSS.supports('color', raw)) { delete vars[p]; continue; }
    probe.style.color = raw;
    vars[p] = toHex(getComputedStyle(probe).color) || null;
    if (!vars[p]) delete vars[p];
  }
  probe.remove();
  return { node, images: Object.keys(images), vars, warnings, size: [R(rb.width), R(rb.height)] };
}
