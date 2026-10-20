#!/usr/bin/env python3
"""Stitch HTML -> layout.json + reference screenshot.

Renders the exported Stitch HTML in a real browser engine (system Chrome via
Playwright), then walks the DOM capturing absolute geometry and final computed
styles for every visible element, including per-line text boxes, gradients,
radii, shadows, clip chains, images (object-fit baked) and inline SVG icons
(rasterized). Output feeds the Sketch builder.

Usage:
  extract_layout.py <input.html> [--out DIR] [--type mobile|web]
                    [--width N] [--no-screenshot]
"""
import argparse
import json
import os

WALKER_JS = r"""
async () => {
  const SKIP = new Set(['SCRIPT','STYLE','LINK','META','NOSCRIPT','TITLE','HEAD','TEMPLATE','BR']);
  const SEMANTIC = new Set(['HEADER','MAIN','SECTION','NAV','FOOTER','ASIDE','BUTTON','A','UL','OL','LI','FORM','ARTICLE','TABLE','SELECT','INPUT','TEXTAREA','LABEL']);
  const sx = window.scrollX, sy = window.scrollY;
  const out = { viewport: {w: document.documentElement.clientWidth, h: Math.max(document.documentElement.scrollHeight, window.innerHeight)}, els: [], warnings: [] };
  const els = out.els;
  const bakes = [];
  const px = v => Math.round(parseFloat(v) * 100) / 100;

  function parseColor(c) {
    if (!c) return null;
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    if (p.length < 3) return null;
    const a = p.length > 3 ? Math.round(p[3] * 255) : 255;
    if (a === 0) return null;
    const h = n => n.toString(16).padStart(2, '0');
    return '#' + h(p[0]) + h(p[1]) + h(p[2]) + h(a);
  }
  function firstFont(ff) {
    if (!ff) return null;
    const f = ff.split(',')[0].trim().replace(/["']/g, '');
    return f === '-apple-system' || f === 'system-ui' ? null : f;
  }
  function parseGradient(s) {
    if (!s || s === 'none') return null;
    const g = s.match(/^linear-gradient\(([\s\S]*)\)$/);
    if (!g) return { type: 'other', css: s.slice(0, 200) };
    const parts = []; let depth = 0, cur = '';
    for (const ch of g[1]) {
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { parts.push(cur); cur = ''; } else cur += ch;
    }
    parts.push(cur);
    let angle = 180;
    const head = parts[0].trim();
    if (/^[\d.]+deg$/.test(head)) { angle = parseFloat(head); parts.shift(); }
    else if (/^to /.test(head)) {
      const d = head.slice(3);
      const map = { 'top': 0, 'right': 90, 'bottom': 180, 'left': 270,
        'top right': 45, 'right top': 45, 'bottom right': 135, 'right bottom': 135,
        'bottom left': 225, 'left bottom': 225, 'top left': 315, 'left top': 315 };
      angle = map[d] !== undefined ? map[d] : 180; parts.shift();
    }
    const stops = parts.map(p => {
      const m = p.trim().match(/^(rgba?\([^)]+\)|#[0-9a-f]+|[a-z]+)\s*([\d.]+%)?$/i);
      if (!m) return null;
      return { c: parseColor(m[1]) || m[1], pos: m[2] ? parseFloat(m[2]) / 100 : null };
    }).filter(Boolean);
    if (stops.length < 2) return null;
    if (stops[0].pos === null) stops[0].pos = 0;
    if (stops[stops.length - 1].pos === null) stops[stops.length - 1].pos = 1;
    for (let i = 1; i < stops.length; i++) if (stops[i].pos === null) {
      let j = i; while (j < stops.length && stops[j].pos === null) j++;
      const step = (stops[j].pos - stops[i - 1].pos) / (j - i + 1);
      for (let k = i; k < j; k++) stops[k].pos = stops[k - 1].pos + step;
    }
    return { type: 'linear', angle, stops };
  }
  function parseShadow(s) {
    if (!s || s === 'none') return null;
    const m = s.match(/rgba?\([^)]+\)/);
    let rest = s, color = '#00000059';
    if (m) { color = parseColor(m[0]) || color; rest = s.replace(m[0], ' '); }
    const n = rest.trim().split(/\s+/).filter(t => t && !/^inset$/i.test(t)).map(parseFloat).filter(v => !isNaN(v));
    if (n.length < 4) return null;
    return { x: n[0], y: n[1], blur: n[2], spread: n[3], c: color };
  }
  function radii(el, cs, r) {
    const res = (v) => {
      const m = (v || '').match(/^([\d.]+)(%|px|rem|em)?/);
      if (!m) return 0;
      let val = parseFloat(m[1]);
      if (m[2] === '%') val = Math.min(r.w, r.h) * val / 100;
      else if (m[2] === 'rem' || m[2] === 'em') val *= 16;
      return Math.min(px(val), Math.min(r.width, r.height) / 2);
    };
    return [res(cs.borderTopLeftRadius), res(cs.borderTopRightRadius), res(cs.borderBottomRightRadius), res(cs.borderBottomLeftRadius)];
  }
  function effOpacity(el) {
    let o = 1, n = el;
    while (n && n.nodeType === 1) { o *= parseFloat(getComputedStyle(n).opacity || '1'); n = n.parentElement; }
    return Math.round(o * 100) / 100;
  }
  function clipChain(el) {
    let n = el.parentElement, clip = null;
    while (n && n.nodeType === 1 && n !== document.body) {
      const cs = getComputedStyle(n);
      if (/(hidden|clip)/.test(cs.overflow + cs.overflowX + cs.overflowY)) {
        const r = n.getBoundingClientRect();
        clip = { x: px(r.left + sx), y: px(r.top + sy), w: px(r.width), h: px(r.height), r: radii(n, cs, r) };
        break;
      }
      n = n.parentElement;
    }
    return clip;
  }
  function tokenize(text) {
    // 中英混合切 token：拉丁词保持整词、空白保留、CJK(含全角)逐字切分，
    // 否则中文整段是一个"词"，range 一次性跨整段、切行完全失效
    const out = [];
    const parts = text.split(/(\s+)/);
    for (const w of parts) {
      if (!w) continue;
      if (/^\s+$/.test(w)) { out.push(w); continue; }
      const sub = w.split(/(?=[\u1100-\u11ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef\u3000-\u303f])/);
      for (const c of sub) if (c) out.push(c);
    }
    return out;
  }
  function lineRuns(node, extra) {
    const text = node.nodeValue;
    if (!text || !text.trim()) return [];
    const toks = tokenize(text);
    const range = document.createRange();
    const runs = [];
    let lineStart = -1, lineEnd = -1;   // char range of current line
    let top = null, left = Infinity, right = -Infinity, hgt = 0;
    const flush = () => {
      if (lineStart < 0 || lineEnd <= lineStart) return;
      let shown = text.slice(lineStart, lineEnd);
      if (!shown.trim()) return;
      if (extra.tt === 'uppercase') shown = shown.toUpperCase();
      else if (extra.tt === 'lowercase') shown = shown.toLowerCase();
      else if (extra.tt === 'capitalize') shown = shown.replace(/\b\w/g, c => c.toUpperCase());
      runs.push(Object.assign({ t: shown.replace(/\s+/g, ' '),
        x: px(left + sx), y: px(top + sy), w: px(Math.max(1, right - left)), h: px(Math.max(hgt, 8)) }, extra));
    };
    let pos = 0;
    for (const w of toks) {
      const s = pos, e = pos + w.length;
      pos = e;
      if (/^\s+$/.test(w)) continue;
      range.setStart(node, s); range.setEnd(node, e);
      const r = range.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      if (top === null) {
        top = r.top; left = r.left; right = r.right; hgt = r.height;
        lineStart = s; lineEnd = e;
      } else if (Math.abs(r.top - top) > Math.max(2, r.height * 0.4)) {
        flush();
        top = r.top; left = r.left; right = r.right; hgt = r.height;
        lineStart = s; lineEnd = e;
      } else {
        left = Math.min(left, r.left); right = Math.max(right, r.right);
        hgt = Math.max(hgt, r.height);
        lineEnd = e;
      }
    }
    flush();
    return runs;
  }

  function resolvePaint(v) {
    if (!v || v === 'none') return '';
    const c = parseColor(v);
    if (c) return c;
    const m = ('' + v).match(/url\(["']?#([^)"']+)/);
    if (!m) return '';
    const g = document.getElementById(m[1]);
    if (!g || !g.querySelectorAll) return '';
    const stops = [];
    g.querySelectorAll('stop').forEach(function (st) {
      let pos = parseFloat(st.getAttribute('offset') || '0');
      if (isNaN(pos)) pos = 0;
      if (('' + st.getAttribute('offset')).indexOf('%') >= 0) pos = pos / 100;
      const scs = getComputedStyle(st);
      let scRaw = scs.stopColor || st.getAttribute('stop-color') || '';
      let sc = parseColor(scRaw) || '#000000ff';
      let so = scs.stopOpacity;
      if (so !== null && so !== undefined && so !== '') {
        const a = Math.round(parseFloat(so) * 255);
        sc = sc.slice(0, 7) + (a.toString(16).length < 2 ? '0' : '') + a.toString(16);
      }
      stops.push({ c: sc, pos: pos });
    });
    if (!stops.length) return '';
    if (stops.length === 1) stops.push({ c: stops[0].c, pos: 1 });
    let angle = 180;
    const x1 = parseFloat(g.getAttribute('x1') || '0'), y1 = parseFloat(g.getAttribute('y1') || '0');
    const x2 = parseFloat(g.getAttribute('x2') || '0'), y2 = parseFloat(g.getAttribute('y2') || '1');
    const dx = x2 - x1, dy = y2 - y1;
    if (dx !== 0 || dy !== 0) angle = Math.atan2(dx, -dy) * 180 / Math.PI;
    return { grad: { angle: angle, stops: stops } };
  }
  function collectSvg(el, r) {
    const vbEl = el.viewBox && el.viewBox.baseVal;
    const vb = { w: vbEl && vbEl.width ? vbEl.width : r.width, h: vbEl && vbEl.height ? vbEl.height : r.height };
    const paths = [];
    el.querySelectorAll('path,polyline,line,circle,rect,ellipse,polygon').forEach(function (n) {
      const cs = getComputedStyle(n);
      const tag = n.tagName.toLowerCase();
      const item = { tag: tag,
        fill: resolvePaint(cs.fill),
        stroke: resolvePaint(cs.stroke),
        sw: parseFloat(cs.strokeWidth) || 1, op: Math.round((parseFloat(cs.opacity) || 1) * 100) / 100 };
      try { const bb = n.getBBox(); item.bbox = { x: bb.x, y: bb.y, w: bb.width, h: bb.height }; } catch (e) {}
      if (tag === 'path') item.d = n.getAttribute('d') || '';
      if (tag === 'polyline' || tag === 'polygon') item.points = n.getAttribute('points') || '';
      if (tag === 'line') { item.x1 = n.x1.baseVal.value; item.y1 = n.y1.baseVal.value; item.x2 = n.x2.baseVal.value; item.y2 = n.y2.baseVal.value; }
      if (tag === 'circle') { item.cx = n.cx.baseVal.value; item.cy = n.cy.baseVal.value; item.cr = n.r.baseVal.value; }
      if (tag === 'rect') { item.rx = n.x.baseVal.value; item.ry = n.y.baseVal.value; item.rw = n.width.baseVal.value; item.rh = n.height.baseVal.value; }
      if (item.d || item.points || tag === 'line' || tag === 'circle' || tag === 'rect') paths.push(item);
    });
    return { viewBox: vb, paths: paths };
  }

  function walk(el, parentIdx, parentVisible, inheritedClip) {
    if (SKIP.has(el.tagName)) return;
    const tagLC = el.tagName.toLowerCase();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = el.getBoundingClientRect();
    if (r.width < 0.5 || r.height < 0.5) return;
    let clip = clipChain(el);
    if (!clip) clip = inheritedClip;
    const op = effOpacity(el);
    const visible = parentVisible && op > 0.01;
    const bg = parseColor(cs.backgroundColor);
    let grad = parseGradient(cs.backgroundImage);
    if (grad && grad.type !== 'linear') grad = null;
    const icon = /Material Symbols/i.test(cs.fontFamily || '');
    let img = null;
    let svgdata = null;
    if (el.tagName === 'IMG' && el.currentSrc) {
      img = { src: el.currentSrc, fit: cs.objectFit === 'fill' ? 'fill' : cs.objectFit, nw: el.naturalWidth, nh: el.naturalHeight, data: null };
    } else if (tagLC === 'svg') {
      svgdata = collectSvg(el, r);
      try { img = { svg: new XMLSerializer().serializeToString(el), fit: 'contain', data: null }; } catch (e) {}
    }
    const bgUrlM = cs.backgroundImage ? cs.backgroundImage.match(/url\(["']?([^"')]+)["']?\)/) : null;
    let bgimg = null;
    if (bgUrlM) {
      const fitMap = { 'cover': 'cover', 'contain': 'contain' };
      bgimg = { src: bgUrlM[1], fit: fitMap[cs.backgroundSize] || 'fill', data: null };
    }
    let borders = null;
    const bw = [parseFloat(cs.borderTopWidth), parseFloat(cs.borderRightWidth), parseFloat(cs.borderBottomWidth), parseFloat(cs.borderLeftWidth)];
    const bc = [parseColor(cs.borderTopColor), parseColor(cs.borderRightColor), parseColor(cs.borderBottomColor), parseColor(cs.borderLeftColor)];
    const bs = [cs.borderTopStyle, cs.borderRightStyle, cs.borderBottomStyle, cs.borderLeftStyle];
    const active = bs.map((s, i) => s !== 'none' && bw[i] > 0.5 && bc[i]);
    if (active.some(Boolean)) {
      const idxB = active.findIndex(Boolean);
      borders = { w: Math.round(Math.max(...bw.filter((x, i) => active[i])) * 100) / 100, c: bc[idxB] };
    }
    let texts = [];
    if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && !icon) {
      const ph = el.getAttribute('placeholder')
      if (ph) {
        const fs2 = px(cs.fontSize)
        const phc = parseColor(cs.color) || '#00000099'
        texts = [{ t: ph, x: px(r.left + sx) + 12, y: px(r.top + sy + (r.height - fs2 * 1.3) / 2), w: px(r.width) - 24, h: Math.round(fs2 * 1.3),
          fs: fs2, fw: 400, ff: firstFont(cs.fontFamily), lh: null, ls: 0,
          c: phc.slice(0, 7) + '8c', tt: null, icon: false }]
      }
    } else if (icon) {
      const lig = (el.textContent || '').trim();
      if (lig) texts = [{ t: lig, x: px(r.left + sx), y: px(r.top + sy), w: px(r.width), h: px(r.height),
        fs: px(cs.fontSize), fw: 400, ff: 'Material Symbols Outlined', lh: null, ls: 0,
        c: parseColor(cs.color) || '#000000ff', tt: null, icon: true }];
    } else {
      for (const n of el.childNodes) {
        if (n.nodeType === 3) {
          const extra = {
            fs: px(cs.fontSize), fw: parseInt(cs.fontWeight) || 400, ff: firstFont(cs.fontFamily),
            lh: cs.lineHeight === 'normal' ? null : px(cs.lineHeight),
            ls: cs.letterSpacing === 'normal' ? 0 : px(cs.letterSpacing),
            c: parseColor(cs.color) || '#000000ff', tt: cs.textTransform === 'none' ? null : cs.textTransform,
            icon: false
          };
          texts.push(...lineRuns(n, extra));
        }
      }
    }
    const shadow = parseShadow(cs.boxShadow);
    const isSemantic = SEMANTIC.has(el.tagName);
    const hasVisual = !!(bg || grad || img || bgimg || svgdata || shadow || borders || texts.length || isSemantic);
    let myIdx = parentIdx;
    if (visible && hasVisual) {
      const rec = { tag: el.tagName.toLowerCase(), p: parentIdx,
        x: px(r.left + sx), y: px(r.top + sy), w: px(r.width), h: px(r.height), op };
      if (cs.position === 'fixed') {
        rec.fixed = true
        rec.vpTop = px(r.top)
        rec.vpBottom = px(window.innerHeight - (r.top + r.height))
      }
      const aria = el.getAttribute && el.getAttribute('aria-label');
      if (aria) rec.label = aria;
      const cls = (el.getAttribute && el.getAttribute('class') || '').trim();
      if (cls) rec.cls = cls.slice(0, 120);
      if (bg) rec.bg = bg;
      if (grad) rec.grad = grad;
      if (shadow) rec.sw = shadow;
      if (borders) rec.b = borders;
      const rad = radii(el, cs, r);
      if (rad.some(v => v > 0.5)) rec.r = rad.map(px);
      if (clip) rec.clip = clip;
      if (texts.length) rec.texts = texts;
      if (svgdata) { rec.svgdata = svgdata; }
      if (img) { rec.img = img; bakes.push({ i: els.length, kind: img.svg ? 'svg' : 'url', src: img.src, svg: img.svg, w: r.width, h: r.height, fit: img.fit }); }
      if (bgimg) { rec.bgimg = bgimg; bakes.push({ i: els.length, kind: 'url', src: bgimg.src, w: r.width, h: r.height, fit: bgimg.fit }); }
      els.push(rec);
      myIdx = els.length - 1;
    }
    for (const c of el.children) walk(c, myIdx, visible, clip);
  }
  walk(document.body, -1, true, null);

  // bake images / svgs
  function bakeUrl(src, w, h, fit) {
    return new Promise(resolve => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = () => {
        let data = null;
        try {
          const c = document.createElement('canvas');
          c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
          const ctx = c.getContext('2d');
          const iw = img.naturalWidth, ih = img.naturalHeight;
          let dw = w, dh = h, dx = 0, dy = 0;
          if (fit === 'cover') { const s = Math.max(w / iw, h / ih); dw = iw * s; dh = ih * s; dx = (w - dw) / 2; dy = (h - dh) / 2; }
          else if (fit === 'contain') { const s = Math.min(w / iw, h / ih); dw = iw * s; dh = ih * s; dx = (w - dw) / 2; dy = (h - dh) / 2; }
          ctx.drawImage(img, dx, dy, dw, dh);
          data = c.toDataURL('image/png');
        } catch (e) {}
        resolve({ data, nw: img.naturalWidth, nh: img.naturalHeight });
      };
      img.onerror = () => resolve(null);
      img.src = src;
    });
  }
  function bakeSvg(svgStr, w, h) {
    return new Promise(resolve => {
      try {
        const blob = new Blob([svgStr], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const img = new Image();
        img.onload = () => {
          let data = null;
          try {
            const c = document.createElement('canvas');
            const scale = Math.min(4, Math.max(2, 256 / Math.max(w, h)));
            c.width = Math.max(1, Math.round(w * scale)); c.height = Math.max(1, Math.round(h * scale));
            const ctx = c.getContext('2d');
            ctx.drawImage(img, 0, 0, c.width, c.height);
            data = c.toDataURL('image/png');
          } catch (e) {}
          URL.revokeObjectURL(url);
          resolve({ data, nw: img.naturalWidth, nh: img.naturalHeight });
        };
        img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
        img.src = url;
      } catch (e) { resolve(null); }
    });
  }
  await Promise.all(bakes.map(async t => {
    const res = t.kind === 'svg' ? await bakeSvg(t.svg, t.w, t.h) : await bakeUrl(t.src, t.w, t.h, t.fit);
    const e = els[t.i];
    if (!e || !res) { if (e) e.bakeFail = true; return; }
    if (e.img) { e.img.data = res.data; if (!e.img.nw) { e.img.nw = res.nw; e.img.nh = res.nh; } }
    if (e.bgimg) e.bgimg.data = res.data;
  }));

  const bodyCS = getComputedStyle(document.body);
  out.browserVH = window.innerHeight
  out.bodyBg = parseColor(bodyCS.backgroundColor) || '#ffffffff';
  out.fonts = [];
  document.fonts.forEach(f => { if (!out.fonts.includes(f.family)) out.fonts.push(f.family); });

  // 剔除完全被裁剪的元素时必须重建父引用下标（旧->新重映射），否则 p 全部错位
  const keep = out.els.map(function (e) {
    if (!e.clip) return true;
    return !(e.x + e.w <= e.clip.x || e.x >= e.clip.x + e.clip.w || e.y + e.h <= e.clip.y || e.y >= e.clip.y + e.clip.h);
  });
  const remap = {};
  let ni = 0;
  for (let oi = 0; oi < out.els.length; oi++) remap[oi] = keep[oi] ? ni++ : -1;
  function resolveOld(i) {
    while (i !== -1 && i !== undefined && i !== null) {
      if (remap[i] !== undefined && remap[i] >= 0) return remap[i];
      i = out.els[i] ? out.els[i].p : -1;
    }
    return -1;
  }
  const kept = [];
  for (let oi = 0; oi < out.els.length; oi++) {
    if (!keep[oi]) continue;
    const e = out.els[oi];
    e.p = resolveOld(e.p);
    kept.push(e);
  }
  out.els = kept;
  return out;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--out", default=None)
    ap.add_argument("--type", choices=["mobile", "web"], default="mobile")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--no-screenshot", action="store_true")
    args = ap.parse_args()

    width = args.width or (390 if args.type == "mobile" else 1440)
    outdir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.html)), "sketch_build")
    os.makedirs(outdir, exist_ok=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": width, "height": 844}, device_scale_factor=1)
        page.goto(f"file://{os.path.abspath(args.html)}", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(400)
        page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
        page.wait_for_timeout(600)
        layout = page.evaluate(WALKER_JS)
        page.wait_for_timeout(300)
        if not args.no_screenshot:
            page.screenshot(path=os.path.join(outdir, "reference.png"), full_page=True)
        browser.close()

    layout["viewport"]["w"] = width
    with open(os.path.join(outdir, "layout.json"), "w") as f:
        json.dump(layout, f, ensure_ascii=False)
    n_text = sum(1 for e in layout["els"] if e.get("texts"))
    n_img = sum(1 for e in layout["els"] if e.get("img") or e.get("bgimg"))
    print(json.dumps({
        "ok": True, "out": outdir, "viewport": layout["viewport"],
        "elements": len(layout["els"]), "with_text": n_text, "with_img": n_img,
        "fonts": layout.get("fonts", []), "bodyBg": layout.get("bodyBg"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
