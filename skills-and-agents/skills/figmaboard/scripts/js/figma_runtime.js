// figmaboard runtime for use_figma. build_push.py / build_pull.py prepend `const P = {...};`.
// Modes: push (build/replace artboards), pull (return only what changed), dump (read frames for a new board).
// Follows figma-use rules: return-only output, 0-1 colors, fonts loaded before text edits,
// one page switch per call, HUG/FILL set after appendChild, resize before sizing modes.
const R1 = v => Math.round(v * 10) / 10;
const out = { err: [] };
function rgb(h) {
  h = h.replace('#', '');
  const n = i => parseInt(h.slice(i, i + 2), 16) / 255;
  return { c: { r: n(0), g: n(2), b: n(4) }, a: h.length >= 8 ? Math.round(n(6) * 1000) / 1000 : 1 };
}
function hex(c, a) {
  const t = v => Math.round(v * 255).toString(16).padStart(2, '0');
  const al = a === undefined ? 1 : a;
  return '#' + t(c.r) + t(c.g) + t(c.b) + (al < 0.999 ? t(al) : '');
}
function fnv(s) {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193); }
  return (h >>> 0).toString(36);
}
let VARS = {}, VBYID = {}, SPACE = {}, RAD = {}, COL = null, MODE = null, PENDING = Object.assign({}, P.pending || {});
async function loadVars(create) {
  const cols = await figma.variables.getLocalVariableCollectionsAsync();
  COL = cols.find(c => c.name === P.coll) || null;
  if (!COL && create) COL = figma.variables.createVariableCollection(P.coll);
  const all = await figma.variables.getLocalVariablesAsync();
  for (const v of all) VBYID[v.id] = v;
  if (!COL) return;
  MODE = COL.modes[0].modeId;
  for (const v of all) if (v.variableCollectionId === COL.id) VARS[v.name] = v;
}
function scopeFor(name) {
  if (name.startsWith('space/')) return ['GAP'];
  if (name.startsWith('radius/')) return ['CORNER_RADIUS'];
  if (/^color\/text-/.test(name)) return ['TEXT_FILL'];
  if (/^color\/bg-/.test(name)) return ['FRAME_FILL', 'SHAPE_FILL'];
  if (/^color\/border-/.test(name)) return ['STROKE_COLOR'];
  return ['ALL_FILLS', 'STROKE_COLOR'];
}
function ensureVar(name, type, val) {
  let v = VARS[name];
  if (!v) { v = figma.variables.createVariable(name, COL, type); v.scopes = scopeFor(name); VARS[name] = v; VBYID[v.id] = v; }
  v.setValueForMode(MODE, val);
  return v;
}
// ---------- fonts
let FONTS = null, FCACHE = {};
const WN = { 100: ['Thin', 'Hairline'], 200: ['Extra Light', 'ExtraLight', 'Ultra Light', 'UltraLight'], 300: ['Light'], 400: ['Regular', 'Normal', 'Book', 'Roman'], 500: ['Medium'], 600: ['Semi Bold', 'SemiBold', 'Demi Bold', 'DemiBold'], 700: ['Bold'], 800: ['Extra Bold', 'ExtraBold', 'Ultra Bold', 'UltraBold'], 900: ['Black', 'Heavy'] };
function styleWeight(st) {
  const s = st.replace(/italic|oblique/ig, '').trim().toLowerCase().replace(/\s+/g, '');
  for (const w of Object.keys(WN)) if (WN[w].some(x => x.toLowerCase().replace(/\s+/g, '') === s)) return +w;
  return s === '' ? 400 : 400;
}
const GENERIC = { 'sans-serif': 'Inter', 'system-ui': 'Inter', '-apple-system': 'Inter', 'blinkmacsystemfont': 'Inter', 'ui-sans-serif': 'Inter', 'serif': 'Noto Serif', 'ui-serif': 'Noto Serif', 'monospace': 'Roboto Mono', 'ui-monospace': 'Roboto Mono', 'cursive': 'Inter', 'fantasy': 'Inter', 'segoe ui': 'Inter', 'helvetica': 'Inter', 'helvetica neue': 'Inter', 'arial': 'Inter' };
async function fontFor(ft) {
  const key = ft.f + '|' + (ft.w || 400) + '|' + (ft.i ? 1 : 0);
  if (FCACHE[key]) return FCACHE[key];
  if (!FONTS) {
    FONTS = {};
    for (const f of await figma.listAvailableFontsAsync()) {
      const k = f.fontName.family.toLowerCase();
      (FONTS[k] = FONTS[k] || { family: f.fontName.family, styles: [] }).styles.push(f.fontName.style);
    }
  }
  const fams = String(ft.f || 'Inter').split(',').map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
  let fam = null;
  for (const f of fams) {
    const k = f.toLowerCase();
    if (FONTS[k]) { fam = FONTS[k]; break; }
    if (GENERIC[k] && FONTS[GENERIC[k].toLowerCase()]) { fam = FONTS[GENERIC[k].toLowerCase()]; break; }
  }
  if (!fam) fam = FONTS['inter'];
  const want = ft.w || 400, it = !!ft.i;
  let best = null, bd = 1e9;
  for (const st of fam.styles) {
    const isIt = /italic|oblique/i.test(st);
    const d = Math.abs(styleWeight(st) - want) + (isIt === it ? 0 : 1000);
    if (d < bd) { bd = d; best = st; }
  }
  const fn = { family: fam.family, style: best };
  if (fams[0] && fams[0].toLowerCase() !== fam.family.toLowerCase()) (out.fonts = out.fonts || {})[fams[0]] = fam.family;
  await figma.loadFontAsync(fn);
  FCACHE[key] = fn;
  return fn;
}
// ---------- paints
function solid(p) {
  if (typeof p !== 'string') return null;
  if (p[0] === '$') {
    const v = VARS[p.slice(1)];
    const tok = P.tokens && P.tokens.color[p.slice(1)];
    const c = rgb(tok || '#000000');
    let paint = { type: 'SOLID', color: c.c, opacity: c.a };
    if (v) paint = figma.variables.setBoundVariableForPaint(paint, 'color', v);
    return paint;
  }
  const c = rgb(p);
  return { type: 'SOLID', color: c.c, opacity: c.a };
}
function grad(g) {
  const a = g.a * Math.PI / 180, dx = Math.sin(a), dy = -Math.cos(a), L = Math.abs(dx) + Math.abs(dy) || 1;
  const m = [[dx / L, dy / L, 0.5 - 0.5 * (dx + dy) / L], [-dy / L, dx / L, 0.5 - 0.5 * (dx - dy) / L]];
  return { type: 'GRADIENT_LINEAR', gradientTransform: m, gradientStops: g.st.map(s => { const c = rgb(s[1]); return { position: s[0], color: { r: c.c.r, g: c.c.g, b: c.c.b, a: c.a } }; }) };
}
function paints(arr, node) {
  const res = [];
  for (const p of arr || []) {
    if (typeof p === 'string') res.push(solid(p));
    else if (p.g) res.push(grad(p));
    else if (p.img) {
      const h = (P.imgs || {})[p.img];
      if (h) res.push({ type: 'IMAGE', scaleMode: p.fit || 'FILL', imageHash: h });
      else { (out.img = out.img || []).push([node.id, p.img]); PENDING[node.id] = p.fit || 'FILL'; res.push({ type: 'SOLID', color: { r: 0.88, g: 0.88, b: 0.88 } }); }
    }
  }
  return res;
}
// ---------- text styles
let TSTYLES = null;
async function textStyle(fn, ft) {
  if (!TSTYLES) { TSTYLES = {}; for (const s of await figma.getLocalTextStylesAsync()) if (s.description.startsWith('fb:')) TSTYLES[s.description] = s; }
  const key = 'fb:' + [fn.family, fn.style, ft.s, ft.lh || 0, ft.ls || 0].join('|');
  if (TSTYLES[key]) return TSTYLES[key];
  const s = figma.createTextStyle();
  s.description = key;
  let nm = 'Text/' + ft.s + ' ' + fn.style;
  const used = new Set(Object.values(TSTYLES).map(x => x.name));
  if (used.has(nm)) nm += ' ' + fn.family;
  if (used.has(nm)) nm += ' ' + (ft.lh || 'auto');
  s.name = nm;
  s.fontName = fn; s.fontSize = ft.s;
  s.lineHeight = ft.lh ? { unit: 'PIXELS', value: ft.lh } : { unit: 'AUTO' };
  s.letterSpacing = { unit: 'PIXELS', value: ft.ls || 0 };
  TSTYLES[key] = s;
  return s;
}
// ---------- build
const AL = { MIN: 'MIN', CENTER: 'CENTER', MAX: 'MAX', SPACE_BETWEEN: 'SPACE_BETWEEN', BASELINE: 'BASELINE' };
const SZ = { X: 'FIXED', H: 'HUG', F: 'FILL' };
function bindNum(n, field, val, table) {
  const v = table[val];
  if (v) { try { n.setBoundVariable(field, v); } catch (e) {} }
}
async function mk(s, parent, inAL, ids) {
  let n;
  if (s.t === 'T') n = figma.createText();
  else if (s.t === 'S') {
    try { n = figma.createNodeFromSvg(s.svg); } catch (e) { n = figma.createFrame(); out.err.push('svg ' + s.n + ': ' + e.message); }
  } else if (s.t === 'I') n = figma.createRectangle();
  else n = figma.createFrame();
  ids.push(n.id);
  parent.appendChild(n);
  n.name = s.n || n.name;
  const abs = s.a && inAL;
  if (abs) n.layoutPositioning = 'ABSOLUTE';
  if (s.t !== 'T') n.resize(Math.max(s.w, 0.01), Math.max(s.h, 0.01));
  if (!inAL || abs) { n.x = s.x; n.y = s.y; }
  if (s.o !== undefined) n.opacity = s.o;
  if (s.t === 'T') {
    const fn = await fontFor(s.ft);
    n.fontName = fn;
    n.characters = s.tx;
    const st = await textStyle(fn, s.ft);
    await n.setTextStyleIdAsync(st.id);
    n.textAlignHorizontal = { L: 'LEFT', C: 'CENTER', R: 'RIGHT', J: 'JUSTIFIED' }[s.ft.al] || 'LEFT';
    if (s.ft.tc) n.textCase = { U: 'UPPER', L: 'LOWER', T: 'TITLE' }[s.ft.tc];
    if (s.ft.d) n.textDecoration = s.ft.d === 'U' ? 'UNDERLINE' : 'STRIKETHROUGH';
    if (s.fc) n.fills = [solid(s.fc)];
    for (const [a, b, r] of s.rn || []) {
      if (b <= a || b > n.characters.length) continue;
      if (r.w || r.i !== undefined || r.f) n.setRangeFontName(a, b, await fontFor({ f: r.f || s.ft.f, w: r.w || s.ft.w, i: r.i !== undefined ? r.i : s.ft.i }));
      if (r.s) n.setRangeFontSize(a, b, r.s);
      if (r.fc) n.setRangeFills(a, b, [solid(r.fc)]);
      if (r.d) n.setRangeTextDecoration(a, b, r.d === 'U' ? 'UNDERLINE' : r.d === 'S' ? 'STRIKETHROUGH' : 'NONE');
      if (r.href && /^https?:/.test(r.href)) n.setRangeHyperlink(a, b, { type: 'URL', value: r.href });
    }
    if (s.ar === 'WH') n.textAutoResize = 'WIDTH_AND_HEIGHT';
    else { n.resize(Math.max(s.w, 1), Math.max(s.h, 1)); n.textAutoResize = s.ar === 'N' ? 'NONE' : 'HEIGHT'; }
  } else if (s.t === 'S') {
    // keep imported vector colors as-is
  } else {
    if (s.t === 'I') {
      n.fills = paints([{ img: s.src, fit: s.fit }], n);
    } else n.fills = s.f ? paints(s.f, n) : [];
    if (s.s) {
      n.strokes = [solid(s.s.c)];
      n.strokeAlign = 'INSIDE';
      const w = s.s.w;
      if (w.every(x => x === w[0])) n.strokeWeight = w[0];
      else { n.strokeTopWeight = w[0]; n.strokeRightWeight = w[1]; n.strokeBottomWeight = w[2]; n.strokeLeftWeight = w[3]; }
    }
    if (s.r) {
      if (Array.isArray(s.r)) { n.topLeftRadius = s.r[0]; n.topRightRadius = s.r[1]; n.bottomRightRadius = s.r[2]; n.bottomLeftRadius = s.r[3]; }
      else {
        n.cornerRadius = s.r;
        for (const c of ['topLeftRadius', 'topRightRadius', 'bottomLeftRadius', 'bottomRightRadius']) bindNum(n, c, s.r, RAD);
      }
    }
    if (s.e) n.effects = s.e.map(e => { const c = rgb(e[5]); return { type: e[0] === 'I' ? 'INNER_SHADOW' : 'DROP_SHADOW', color: { r: c.c.r, g: c.c.g, b: c.c.b, a: c.a }, offset: { x: e[1], y: e[2] }, radius: e[3], spread: e[4], visible: true, blendMode: 'NORMAL' }; });
    if (n.type === 'FRAME') n.clipsContent = !!s.c;
    if (s.L && n.type === 'FRAME') {
      const L = s.L;
      n.layoutMode = L[0] === 'H' ? 'HORIZONTAL' : 'VERTICAL';
      n.itemSpacing = L[1]; n.paddingTop = L[2]; n.paddingRight = L[3]; n.paddingBottom = L[4]; n.paddingLeft = L[5];
      n.primaryAxisAlignItems = L[6] === 'BASELINE' ? 'MIN' : (AL[L[6]] || 'MIN');
      n.counterAxisAlignItems = AL[L[7]] || 'MIN';
      if (L[8]) { n.layoutWrap = 'WRAP'; n.counterAxisSpacing = L[9] || 0; }
      bindNum(n, 'itemSpacing', L[1], SPACE);
      ['paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft'].forEach((f, i) => bindNum(n, f, L[2 + i], SPACE));
      if (L[8] && L[9]) bindNum(n, 'counterAxisSpacing', L[9], SPACE);
      n.primaryAxisSizingMode = 'FIXED'; n.counterAxisSizingMode = 'FIXED';
      n.resize(Math.max(s.w, 0.01), Math.max(s.h, 0.01));
    }
    if (s.k && 'appendChild' in n) for (const k of s.k) await mk(k, n, !!(s.L && n.layoutMode !== 'NONE'), ids);
  }
  // sizing
  const sz = s.sz || 'XX';
  const isAL = n.type === 'FRAME' && n.layoutMode !== 'NONE';
  for (const [axis, ch] of [['Horizontal', sz[0]], ['Vertical', sz[1]]]) {
    let m = SZ[ch] || 'FIXED';
    if (m === 'HUG' && !(isAL || n.type === 'TEXT')) m = 'FIXED';
    if (m === 'FILL' && !(inAL && !abs)) m = 'FIXED';
    if (m === 'FIXED' && !(inAL || isAL)) continue;
    if (n.type === 'TEXT' && m === 'FIXED' && s.ar === 'WH') continue;
    try { n['layoutSizing' + axis] = m; } catch (e) { out.err.push(s.n + ' sizing ' + e.message); }
  }
  return n;
}
// ---------- serialize (shared by push hashes, pull and dump)
const VEC = new Set(['VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'POLYGON', 'LINE', 'ELLIPSE', 'RECTANGLE', 'GROUP']);
function hasImage(n) { return 'fills' in n && Array.isArray(n.fills) && n.fills.some(f => f.type === 'IMAGE'); }
function isSvg(n) {
  if (!['FRAME', 'GROUP', 'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'POLYGON', 'LINE'].includes(n.type)) return false;
  if (n.type !== 'FRAME' && n.type !== 'GROUP') return true;
  if (n.type === 'FRAME' && n.layoutMode !== 'NONE') return false;
  let any = false, ok = true;
  (function w(x) {
    for (const c of x.children) {
      if (!VEC.has(c.type) || hasImage(c)) { ok = false; return; }
      if (c.type !== 'RECTANGLE' && c.type !== 'GROUP') any = true;
      if (c.type === 'GROUP') w(c);
    }
  })(n);
  return ok && any;
}
function sp(p) {
  if (p.visible === false) return null;
  if (p.type === 'SOLID') {
    const b = p.boundVariables && p.boundVariables.color;
    if (b && VBYID[b.id]) return '$' + VBYID[b.id].name;
    return hex(p.color, p.opacity);
  }
  if (p.type === 'GRADIENT_LINEAR') {
    const m = p.gradientTransform;
    const a = Math.round(Math.atan2(m[0][0], -m[0][1]) * 180 / Math.PI + 360) % 360;
    return { g: 'L', a, st: p.gradientStops.map(s => [R1(s.position), hex(s.color, s.color.a)]) };
  }
  if (p.type === 'IMAGE') return { img: p.imageHash, fit: p.scaleMode === 'FIT' ? 'FIT' : 'FILL' };
  return null;
}
async function ser(n) {
  const o = {};
  const svg = isSvg(n);
  o.t = n.type === 'TEXT' ? 'T' : svg ? 'S' : (n.type === 'RECTANGLE' && hasImage(n) && n.fills.length === 1) ? 'I' : 'F';
  o.n = n.name;
  const px = n.parent && n.parent.type === 'GROUP' ? n.parent.x : 0, py = n.parent && n.parent.type === 'GROUP' ? n.parent.y : 0;
  o.x = R1(n.x - px); o.y = R1(n.y - py); o.w = R1(n.width); o.h = R1(n.height);
  if ('layoutPositioning' in n && n.layoutPositioning === 'ABSOLUTE') o.a = 1;
  if ('opacity' in n && n.opacity < 1) o.o = R1(n.opacity * 100) / 100;
  const inAL = n.parent && n.parent.type !== 'PAGE' && n.parent.type !== 'SECTION' && 'layoutMode' in n.parent && n.parent.layoutMode !== 'NONE';
  const isAL = 'layoutMode' in n && n.layoutMode !== 'NONE' && n.type !== 'TEXT';
  if (inAL || isAL || n.type === 'TEXT') {
    const m = { FIXED: 'X', HUG: 'H', FILL: 'F' };
    try { o.sz = (m[n.layoutSizingHorizontal] || 'X') + (m[n.layoutSizingVertical] || 'X'); } catch (e) {}
  }
  if (o.t === 'S') {
    try { const s = await n.exportAsync({ format: 'SVG_STRING' }); o.svg = s.length > (P.svgMax || 8000) ? null : s; o.sh = fnv(s); } catch (e) { o.svg = null; }
    return o;
  }
  if (o.t === 'T') {
    o.tx = n.characters;
    const segs = n.getStyledTextSegments(['fontName', 'fontSize', 'fills', 'textDecoration', 'hyperlink', 'fontWeight', 'lineHeight', 'letterSpacing']);
    const b = segs[0];
    o.ft = { f: b.fontName.family, w: b.fontWeight, i: /italic/i.test(b.fontName.style) ? 1 : 0, s: b.fontSize, lh: b.lineHeight.unit === 'PIXELS' ? R1(b.lineHeight.value) : b.lineHeight.unit === 'PERCENT' ? R1(b.lineHeight.value * b.fontSize / 100) : 0, ls: b.letterSpacing.unit === 'PIXELS' ? R1(b.letterSpacing.value) : R1(b.letterSpacing.value * b.fontSize / 100), al: { LEFT: 'L', CENTER: 'C', RIGHT: 'R', JUSTIFIED: 'J' }[n.textAlignHorizontal] };
    const tc = n.textCase; if (tc && tc !== figma.mixed && tc !== 'ORIGINAL') o.ft.tc = { UPPER: 'U', LOWER: 'L', TITLE: 'T' }[tc];
    if (b.textDecoration === 'UNDERLINE') o.ft.d = 'U'; else if (b.textDecoration === 'STRIKETHROUGH') o.ft.d = 'S';
    const bf = b.fills.length ? sp(b.fills[0]) : null; if (bf) o.fc = bf;
    const rn = [];
    for (const g of segs.slice(1).concat(segs.length > 1 ? [] : [])) {
      const r = {};
      if (g.fontWeight !== b.fontWeight) r.w = g.fontWeight;
      const gi = /italic/i.test(g.fontName.style) ? 1 : 0; if (gi !== o.ft.i) r.i = gi;
      if (g.fontName.family !== b.fontName.family) r.f = g.fontName.family;
      if (g.fontSize !== b.fontSize) r.s = g.fontSize;
      const gf = g.fills.length ? sp(g.fills[0]) : null; if (JSON.stringify(gf) !== JSON.stringify(bf)) r.fc = gf;
      if (g.textDecoration !== b.textDecoration) r.d = g.textDecoration === 'UNDERLINE' ? 'U' : g.textDecoration === 'STRIKETHROUGH' ? 'S' : 'N';
      if (g.hyperlink && g.hyperlink.type === 'URL') r.href = g.hyperlink.value;
      if (Object.keys(r).length) rn.push([g.start, g.end, r]);
    }
    if (b.hyperlink && b.hyperlink.type === 'URL') rn.unshift([b.start, b.end, { href: b.hyperlink.value }]);
    if (rn.length) o.rn = rn;
    o.ar = { WIDTH_AND_HEIGHT: 'WH', HEIGHT: 'H', NONE: 'N', TRUNCATE: 'N' }[n.textAutoResize] || 'N';
    return o;
  }
  if (o.t === 'I') { const f = n.fills[0]; o.src = f.imageHash; o.fit = f.scaleMode === 'FIT' ? 'FIT' : 'FILL'; }
  else if ('fills' in n && Array.isArray(n.fills)) { const f = n.fills.map(sp).filter(Boolean); if (f.length) o.f = f; }
  if (n.type === 'ELLIPSE') o.el = 1;
  if ('strokes' in n && n.strokes.length) {
    const s = sp(n.strokes.find(x => x.visible !== false) || n.strokes[0]);
    if (typeof s === 'string') {
      const sw = n.strokeWeight;
      const w = sw === figma.mixed ? [n.strokeTopWeight, n.strokeRightWeight, n.strokeBottomWeight, n.strokeLeftWeight] : [sw, sw, sw, sw];
      if (w.some(Boolean)) o.s = { c: s, w: w.map(R1) };
    }
  }
  if ('cornerRadius' in n) {
    if (n.cornerRadius === figma.mixed) o.r = [n.topLeftRadius, n.topRightRadius, n.bottomRightRadius, n.bottomLeftRadius].map(R1);
    else if (n.cornerRadius > 0) o.r = R1(n.cornerRadius);
  }
  if ('effects' in n && n.effects.length) {
    const e = n.effects.filter(x => x.visible !== false && (x.type === 'DROP_SHADOW' || x.type === 'INNER_SHADOW')).map(x => [x.type === 'INNER_SHADOW' ? 'I' : 'D', R1(x.offset.x), R1(x.offset.y), R1(x.radius), R1(x.spread || 0), hex(x.color, x.color.a)]);
    if (e.length) o.e = e;
  }
  if (n.type === 'FRAME' && n.clipsContent) o.c = 1;
  if (isAL) o.L = [n.layoutMode === 'HORIZONTAL' ? 'H' : 'V', R1(n.itemSpacing), R1(n.paddingTop), R1(n.paddingRight), R1(n.paddingBottom), R1(n.paddingLeft), n.primaryAxisAlignItems, n.counterAxisAlignItems, n.layoutWrap === 'WRAP' ? 1 : 0, n.layoutWrap === 'WRAP' ? R1(n.counterAxisSpacing || 0) : 0];
  return o;
}
function kidsOf(n, o) { return o.t === 'F' && 'children' in n ? n.children : []; }
// Hash input ignores WHICH image fills a node, so the upload_assets step right after a push
// (placeholder -> real image) does not look like a Figma-side edit.
function hnorm(n, o) {
  const c = Object.assign({}, o);
  // geometry decided by auto layout is not an edit of this node
  const inAL = n.parent && 'layoutMode' in n.parent && n.parent.layoutMode !== 'NONE' && n.parent.type !== 'PAGE' && n.parent.type !== 'SECTION';
  if (inAL && !c.a) { delete c.x; delete c.y; }
  const sz = c.sz || 'XX';
  if (sz[0] !== 'X' || (c.t === 'T' && c.ar === 'WH')) delete c.w;
  if (sz[1] !== 'X' || (c.t === 'T' && c.ar !== 'N')) delete c.h;
  if (PENDING[n.id]) {
    if (n.type === 'RECTANGLE') { c.t = 'I'; delete c.f; c.src = 'img'; c.fit = PENDING[n.id]; }
    else c.f = [{ img: 'img', fit: PENDING[n.id] }];
  }
  if (c.t === 'I') c.src = 'img';
  if (c.f) c.f = c.f.map(p => p && p.img ? { img: 'img', fit: p.fit } : p);
  return c;
}
// Walk a subtree: cb(node, ownProps, hash, parentId, index)
async function walk(n, parentId, ix, cb) {
  const o = await ser(n);
  const h = fnv(JSON.stringify([hnorm(n, o), parentId, ix]));
  await cb(n, o, h, parentId, ix);
  const ks = kidsOf(n, o);
  for (let i = 0; i < ks.length; i++) await walk(ks[i], n.id, i, cb);
}
async function frameHashes(f) {
  const hs = {};
  let all = '';
  await walk(f, f.parent ? f.parent.id : null, 0, async (n, o, h) => { hs[n.id] = h; all += h; });
  return { hs, fh: fnv(all) };
}
async function readVars() {
  const v = {};
  if (!COL) return v;
  for (const [name, x] of Object.entries(VARS)) {
    const val = x.valuesByMode[MODE];
    if (val && typeof val === 'object' && 'r' in val) v[name] = hex(val, val.a);
    else if (typeof val === 'number') v[name] = R1(val);
  }
  return v;
}
// ---------- modes
async function push() {
  let page = figma.currentPage;
  if (P.page && P.page.id) { page = await figma.getNodeByIdAsync(P.page.id); await figma.setCurrentPageAsync(page); }
  else if (P.page && P.page.create) { page = figma.createPage(); page.name = P.page.create; await figma.setCurrentPageAsync(page); }
  else if (P.page && P.page.rename) page.name = P.page.rename;
  out.page = page.id;
  await loadVars(true);
  for (const [name, hx] of Object.entries(P.tokens.color)) { const c = rgb(hx); ensureVar(name, 'COLOR', { r: c.c.r, g: c.c.g, b: c.c.b, a: c.a }); }
  for (const [name, v] of Object.entries(P.tokens.space)) SPACE[v] = ensureVar(name, 'FLOAT', v);
  for (const [name, v] of Object.entries(P.tokens.radius)) RAD[v] = ensureVar(name, 'FLOAT', v);
  let sec = P.section && P.section.id ? await figma.getNodeByIdAsync(P.section.id) : null;
  if (!sec) {
    sec = figma.createSection();
    sec.name = P.title;
    let mx = 0;
    for (const c of page.children) if (c.id !== sec.id) mx = Math.max(mx, c.x + c.width);
    sec.x = page.children.length > 1 ? mx + 200 : 0; sec.y = 0;
  }
  out.section = sec.id;
  out.abs = {}; out.conflicts = [];
  for (const ab of P.abs) {
    let old = ab.replace ? await figma.getNodeByIdAsync(ab.replace) : null;
    if (old && ab.expect && !ab.force) {
      const cur = await frameHashes(old);
      if (cur.fh !== ab.expect) { out.conflicts.push(ab.key); continue; }
    }
    const parent = old ? old.parent : sec;
    const ids = [];
    const f = await mk(ab.node, parent, false, ids);
    if (old) {
      f.x = old.x; f.y = old.y;
      parent.insertChild(parent.children.indexOf(old), f);
      old.remove();
    } else { f.x = ab.x + 100; f.y = ab.y + 100; }
    const fh = await frameHashes(f);
    out.abs[ab.key] = { id: f.id, ids, hs: ids.map(i => fh.hs[i] || null), fh: fh.fh };
  }
  let mx = 0, my = 0;
  for (const c of sec.children) { mx = Math.max(mx, c.x + c.width); my = Math.max(my, c.y + c.height); }
  if (sec.children.length) sec.resizeWithoutConstraints(mx + 100, my + 100);
  out.fileKey = figma.fileKey;
  if (P.shot && sec.children.length) await sec.screenshot();
}
async function pull() {
  const page = await figma.getNodeByIdAsync(P.page);
  if (!page) { out.err.push('page not found'); return; }
  await figma.setCurrentPageAsync(page);
  await loadVars(false);
  out.abs = {};
  const keys = Object.keys(P.abs);
  let size = 0;
  const known = new Set(keys.map(k => P.abs[k].id));
  for (let i = P.start || 0; i < keys.length; i++) {
    const k = keys[i], ab = P.abs[k];
    const f = await figma.getNodeByIdAsync(ab.id);
    if (!f) { out.abs[k] = { gone: 1 }; continue; }
    const ch = [], seen = new Set();
    let all = '';
    await walk(f, f.parent.id, 0, async (n, o, h, p, ix) => {
      seen.add(n.id); all += h;
      if (ab.hs[n.id] !== h) { o.id = n.id; o.p = p; o.ix = ix; o.hh = h; ch.push(o); }
    });
    const del = Object.keys(ab.hs).filter(id => !seen.has(id));
    const fh = fnv(all);
    out.abs[k] = fh === ab.fh ? { same: 1 } : { ch, del, fh };
    size += JSON.stringify(out.abs[k]).length;
    if (size > P.max && i < keys.length - 1) { out.more = i + 1; break; }
  }
  // frames added in Figma next to the synced ones
  const sec = (P.section ? await figma.getNodeByIdAsync(P.section) : null) || page;
  if (!out.more && !P.noNew) {
    out.nf = [];
    for (const c of sec.children) {
      if (known.has(c.id) || c.type !== 'FRAME') continue;
      const nodes = [];
      await walk(c, sec.id, 0, async (n, o, h, p, ix) => { o.id = n.id; o.p = p; o.ix = ix; o.hh = h; nodes.push(o); });
      out.nf.push({ id: c.id, name: c.name, nodes });
    }
  }
  out.vars = await readVars();
}
async function dump() {
  let target = P.target ? await figma.getNodeByIdAsync(P.target) : null;
  let page;
  if (target && target.type === 'PAGE') { page = target; target = null; }
  else if (target) { let p = target; while (p.type !== 'PAGE') p = p.parent; page = p; }
  else page = figma.currentPage;
  if (page.id !== figma.currentPage.id) await figma.setCurrentPageAsync(page);
  await loadVars(false);
  if (!COL) {
    const cols = await figma.variables.getLocalVariableCollectionsAsync();
    if (cols.length) { COL = cols[0]; MODE = COL.modes[0].modeId; for (const v of await figma.variables.getLocalVariablesAsync()) if (v.variableCollectionId === COL.id) VARS[v.name] = v; }
  }
  let frames;
  if (target && target.type === 'SECTION') frames = target.children.filter(c => c.type === 'FRAME' || c.type === 'COMPONENT' || c.type === 'INSTANCE');
  else if (target) frames = [target];
  else {
    frames = [];
    for (const c of page.children) {
      if (c.type === 'SECTION') frames.push(...c.children.filter(x => x.type === 'FRAME'));
      else if (c.type === 'FRAME' || c.type === 'COMPONENT') frames.push(c);
    }
  }
  out.page = { id: page.id, name: page.name };
  out.coll = COL ? COL.name : null;
  out.frames = [];
  let size = 0;
  for (let i = P.start || 0; i < frames.length; i++) {
    const fr = frames[i];
    const nodes = [];
    let all = '';
    await walk(fr, fr.parent.id, 0, async (n, o, h, p, ix) => { o.id = n.id; o.p = p; o.ix = ix; o.hh = h; all += h; nodes.push(o); });
    out.frames.push({ id: fr.id, name: fr.name, x: R1(fr.x), y: R1(fr.y), parent: fr.parent.type === 'SECTION' ? fr.parent.id : null, fh: fnv(all), nodes });
    size += JSON.stringify(nodes).length;
    if (size > P.max && i < frames.length - 1) { out.more = i + 1; break; }
  }
  out.total = frames.length;
  out.vars = await readVars();
}
if (P.mode === 'push') await push();
else if (P.mode === 'pull') await pull();
else await dump();
if (!out.err.length) delete out.err;
return out;
