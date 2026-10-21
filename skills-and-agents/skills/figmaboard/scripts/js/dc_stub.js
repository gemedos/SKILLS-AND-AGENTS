// figmaboard: local stand-in for a Claude Design canvas runtime (support.js).
// Renders a .dc.html artboard to static DOM so it can be measured.
// It resolves {{holes}}, <sc-for>, <sc-if> and <dc-import> using data-props defaults.
// Rendered elements keep their data-fb ids; elements repeated by <sc-for> get "@<index>" appended.
(function () {
  window.DCLogic = class {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(s) { Object.assign(this.state, typeof s === 'function' ? s(this.state, this.props) : s); }
    forceUpdate() {}
  };
  const FILES = window.__DC_FILES__ || {};
  const HOLE = /\{\{\s*([^}]+?)\s*\}\}/g;

  function literal(p) {
    if (p === 'true') return [true, true];
    if (p === 'false') return [true, false];
    if (p === 'null') return [true, null];
    if (/^-?\d+(\.\d+)?$/.test(p)) return [true, Number(p)];
    const m = p.match(/^(['"])(.*)\1$/);
    if (m) return [true, m[2]];
    return [false];
  }
  function lookup(path, scope) {
    const lit = literal(path);
    if (lit[0]) return lit[1];
    let cur = scope;
    for (const part of path.split('.')) {
      if (cur == null) return undefined;
      cur = cur[part];
    }
    return cur;
  }
  function interp(str, scope) {
    return str.replace(HOLE, (_, p) => {
      const v = lookup(p, scope);
      return v == null || typeof v === 'function' ? '' : String(v);
    });
  }
  function wholeHole(str) {
    const m = str.match(/^\s*\{\{\s*([^}]+?)\s*\}\}\s*$/);
    return m ? m[1] : null;
  }

  function runLogic(doc, props) {
    const sc = doc.querySelector('script[data-dc-script]');
    let defs = {};
    if (sc) {
      try { defs = JSON.parse(sc.getAttribute('data-props') || '{}'); } catch (e) { defs = {}; }
    }
    const p = {};
    for (const k of Object.keys(defs)) {
      if (k[0] !== '$' && defs[k] && 'default' in defs[k]) p[k] = defs[k].default;
    }
    Object.assign(p, props || {});
    let vals = {};
    if (sc) {
      try {
        const Comp = new Function(sc.textContent + '\n;return Component;')();
        const inst = new Comp(p);
        inst.props = p;
        vals = (inst.renderVals && inst.renderVals()) || {};
      } catch (e) { window.__DC_ERRORS__ = (window.__DC_ERRORS__ || []).concat(String(e)); }
    }
    return { vals, props: p, defs };
  }

  function camel(s) { return s.replace(/-([a-z])/g, (_, c) => c.toUpperCase()); }

  function renderChildren(src, out, scope, rep, ctx) {
    for (const ch of Array.from(src.childNodes)) renderNode(ch, out, scope, rep, ctx);
  }

  function renderNode(src, out, scope, rep, ctx) {
    if (src.nodeType === 3) {
      const t = src.nodeValue;
      const h = wholeHole(t);
      if (h && out.nodeType === 1 && /^[A-Za-z_$][\w$]*$/.test(h) && ctx.defs[h] && ctx.defs[h].editor === 'text') {
        out.setAttribute('data-fb-textprop', ctx.file + '#' + h);
      }
      out.appendChild(document.createTextNode(interp(t, scope)));
      return;
    }
    if (src.nodeType !== 1) return;
    const tag = src.tagName.toLowerCase();
    if (tag === 'helmet') {
      for (const ch of Array.from(src.childNodes)) document.head.appendChild(ch.cloneNode(true));
      return;
    }
    if (tag === 'sc-if') {
      const v = lookup((wholeHole(src.getAttribute('value') || '') || 'false'), scope);
      if (v) renderChildren(src, out, scope, rep, ctx);
      return;
    }
    if (tag === 'sc-for') {
      const list = lookup(wholeHole(src.getAttribute('list') || '') || '', scope) || [];
      const as = src.getAttribute('as') || 'item';
      (Array.isArray(list) ? list : []).forEach((item, i) => {
        const s2 = Object.assign({}, scope, { [as]: item, $index: i });
        renderChildren(src, out, s2, rep + '@' + i, ctx);
      });
      return;
    }
    if (tag === 'dc-import') {
      const name = src.getAttribute('name');
      const html = FILES[name + '.dc.html'];
      if (!html) return;
      const props = {};
      for (const a of Array.from(src.attributes)) {
        if (a.name === 'name' || a.name.startsWith('hint-')) continue;
        const h = wholeHole(a.value);
        props[camel(a.name)] = h ? lookup(h, scope) : interp(a.value, scope);
      }
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const lg = runLogic(doc, props);
      const root = doc.querySelector('x-dc');
      if (root) renderChildren(root, out, Object.assign({}, lg.vals), rep + '>' + name, { file: name + '.dc.html', defs: lg.defs });
      return;
    }
    const SVGNS = 'http://www.w3.org/2000/svg';
    const inSvg = tag === 'svg' || (out.namespaceURI === SVGNS);
    const el = inSvg ? document.createElementNS(SVGNS, src.localName) : document.createElement(tag);
    for (const a of Array.from(src.attributes)) {
      if (/^on[A-Z]/.test(a.name) || /^on[a-z]+$/.test(a.name)) continue;
      let name = a.name === 'classname' ? 'class' : a.name === 'htmlfor' ? 'for' : a.name;
      const h = wholeHole(a.value);
      let val;
      if (h) {
        const v = lookup(h, scope);
        if (typeof v === 'function' || (v && typeof v === 'object')) continue;
        val = v == null ? '' : String(v);
      } else val = interp(a.value, scope);
      try { el.setAttribute(name, val); } catch (e) {}
    }
    if (rep && el.hasAttribute('data-fb')) {
      el.setAttribute('data-fb', el.getAttribute('data-fb') + rep);
      el.setAttribute('data-fb-templated', '1');
    }
    const st = src.getAttribute('style');
    if (st && HOLE.test(st)) {
      HOLE.lastIndex = 0;
      const holes = {};
      st.split(';').forEach(decl => {
        const i = decl.indexOf(':');
        if (i < 0) return;
        const h = wholeHole(decl.slice(i + 1));
        if (h && ctx.defs[h]) holes[decl.slice(0, i).trim()] = ctx.file + '#' + h;
      });
      if (Object.keys(holes).length) el.setAttribute('data-fb-styleprops', JSON.stringify(holes));
    }
    HOLE.lastIndex = 0;
    out.appendChild(el);
    if (tag === 'template' || tag === 'script') return;
    renderChildren(src, el, scope, rep, ctx);
  }

  function main() {
    const tpl = document.querySelector('x-dc');
    if (!tpl) { window.__DC_DONE__ = true; return; }
    const lg = runLogic(document, {});
    const holder = document.createElement('div');
    holder.setAttribute('data-fb-dcroot', '1');
    holder.style.display = 'contents';
    renderChildren(tpl, holder, Object.assign({}, lg.vals), '', { file: window.__DC_SELF__ || '', defs: lg.defs });
    tpl.replaceWith(holder);
    window.__DC_DONE__ = true;
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main);
  else main();
})();
