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
    if (/^transparent$/i.test(c.trim())) return '#00000000';
    let m = c.match(/rgba?\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
      if (p.length < 3) return null;
      const a = p.length > 3 ? Math.round(p[3] * 255) : 255;
      const h = n => n.toString(16).padStart(2, '0');
      return '#' + h(p[0]) + h(p[1]) + h(p[2]) + h(a);
    }
    m = c.match(/hsla?\(([^)]+)\)/);
    if (m) {
      const p = m[1].split(/[,\s/]+/).filter(Boolean);
      const hh = parseFloat(p[0]) / 360;
      const ss = parseFloat(p[1]) / 100, ll = parseFloat(p[2]) / 100;
      const a = p.length > 3 ? Math.round(parseFloat(p[3]) * 255) : 255;
      const f = (n) => { const k = (n + hh * 12) % 12; return ll - ss * Math.min(ll, 1 - ll) * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
      const h = n => Math.round(f(n) * 255).toString(16).padStart(2, '0');
      return '#' + h(0) + h(8) + h(4) + h(a);
    }
    if (/^#[0-9a-fA-F]{3,8}$/.test(c.trim())) {
      let s = c.trim().slice(1);
      if (s.length === 3) s = s.split('').map(x => x + x).join('') + 'ff';
      if (s.length === 6) s += 'ff';
      return '#' + s.toLowerCase();
    }
    return null;
  }
  // 全透明色 = 无色（渐变 stop 需要保留 alpha，其余调用点都按无色处理）
  const opaque = c => (c && parseInt(c.slice(7), 16) > 0) ? c : null;
  function firstFont(ff) {
    if (!ff) return null;
    const f = ff.split(',')[0].trim().replace(/["']/g, '');
    return f === '-apple-system' || f === 'system-ui' ? null : f;
  }
  function splitTop(s) {
    const out = []; let depth = 0, cur = '';
    for (const ch of s) {
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  function parseRadial(body) {
    const parts = splitTop(body);
    let from = { x: 0.5, y: 0.5 }, rpx = null;
    const head = parts[0].trim();
    if (/px|at\s|circle|ellipse|closest|farthest/i.test(head)) {
      const at = head.match(/at\s+(-?[\d.]+)%\s+(-?[\d.]+)%/);
      if (at) {
        const cx = Math.max(0, Math.min(1, parseFloat(at[1]) / 100));
        const cy = Math.max(0, Math.min(1, parseFloat(at[2]) / 100));
        from = { x: cx, y: cy };
      }
      const dims = head.match(/([\d.]+)px\s+([\d.]+)px/);
      if (dims) rpx = { x: parseFloat(dims[1]), y: parseFloat(dims[2]) };
      parts.shift();
    }
    const stops = parts.map(p => {
      const m = p.trim().match(/^(rgba?\([^)]+\)|hsla?\([^)]+\)|#[0-9a-f]+|[a-z]+)\s*([\d.]+%)?$/i);
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
    return { type: 'radial', from: from, rpx: rpx, stops: stops };
  }
  function parseGradient(s) {
    if (!s || s === 'none') return null;
    // 多图层背景：两层并存时优先 linear（底色渐变比光晕更影响观感），仅 radial 时才用 radial
    let firstRadialBody = null;
    for (const layer of splitTop(s)) {
      const rm = layer.match(/^radial-gradient\(([\s\S]*)\)$/i);
      if (rm) { if (!firstRadialBody) firstRadialBody = rm[1]; continue; }
      const g = layer.match(/^linear-gradient\(([\s\S]*)\)$/);
      if (!g) continue;
      const parts = splitTop(g[1]);
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
        const m = p.trim().match(/^(rgba?\([^)]+\)|hsla?\([^)]+\)|#[0-9a-f]+|[a-z]+)\s*([\d.]+%)?$/i);
        if (!m) return null;
        return { c: parseColor(m[1]) || m[1], pos: m[2] ? parseFloat(m[2]) / 100 : null };
      }).filter(Boolean);
      if (stops.length < 2) continue;
      if (stops[0].pos === null) stops[0].pos = 0;
      if (stops[stops.length - 1].pos === null) stops[stops.length - 1].pos = 1;
      for (let i = 1; i < stops.length; i++) if (stops[i].pos === null) {
        let j = i; while (j < stops.length && stops[j].pos === null) j++;
        const step = (stops[j].pos - stops[i - 1].pos) / (j - i + 1);
        for (let k = i; k < j; k++) stops[k].pos = stops[k - 1].pos + step;
      }
      return { type: 'linear', angle: angle, stops: stops };
    }
    return firstRadialBody ? parseRadial(firstRadialBody) : null;
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
    const c = opaque(parseColor(v));
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
      // 原始属性优先：computed stopColor 会丢 rgba 的 alpha（透明 stop 曾被兜底成不透明黑）
      const scRawAttr = st.getAttribute('stop-color');
      const soRaw = st.getAttribute('stop-opacity');
      let sc;
      if (scRawAttr !== null && scRawAttr !== '') {
        sc = parseColor(scRawAttr) || '#000000ff';
        if (soRaw !== null && soRaw !== '') {
          const a = Math.round(parseFloat(soRaw) * 255);
          sc = sc.slice(0, 7) + (a.toString(16).length < 2 ? '0' : '') + a.toString(16);
        }
      } else {
        const scs = getComputedStyle(st);
        let scRaw = scs.stopColor || '';
        sc = parseColor(scRaw) || '#000000ff';
        let so = scs.stopOpacity;
        if (so !== null && so !== undefined && so !== '') {
          const a = Math.round(parseFloat(so) * 255);
          sc = sc.slice(0, 7) + (a.toString(16).length < 2 ? '0' : '') + a.toString(16);
        }
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
      if (tag === 'ellipse') { item.cx = n.cx.baseVal.value; item.cy = n.cy.baseVal.value; item.rx = n.rx.baseVal.value; item.ry = n.ry.baseVal.value; }
      if (tag === 'rect') {
        item.x = n.x.baseVal.value; item.y = n.y.baseVal.value;
        item.w = n.width.baseVal.value; item.h = n.height.baseVal.value;
        item.cr = Math.min(n.rx.baseVal.value || 0, Math.min(item.w, item.h) / 2);
      }
      if (item.d || item.points || tag === 'line' || tag === 'circle' || tag === 'rect' || tag === 'ellipse') paths.push(item);
    });
    return { viewBox: vb, paths: paths };
  }

  function walk(el, parentIdx, parentVisible, inheritedClip) {
    if (SKIP.has(el.tagName)) return;
    const tagLC = el.tagName.toLowerCase();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    // offsetParent 剪枝（成熟方案，html2sketch/html-sketchapp 同款）：祖先 display:none 时
    // offsetParent 为 null，整子树不可见，直接跳过（fixed 元素豁免；SVG 无此属性不受影响）
    if (el.tagName !== 'BODY' && tagLC !== 'svg' && el.offsetParent === null && cs.position !== 'fixed') return;
    const r = el.getBoundingClientRect();
    // 零尺寸容器（如整页 fixed 内容使 body 塌缩）只跳过自身记录，仍要递归子元素
    const zeroSelf = r.width < 0.5 || r.height < 0.5;
    let clip = clipChain(el);
    if (!clip) clip = inheritedClip;
    const op = effOpacity(el);
    const visible = parentVisible && op > 0.01;
    // 隐藏文本（sr-only 惯用法）：大负 textIndent + overflow hidden，或 clip:rect(0,0,0,0)
    const srOnly = (parseFloat(cs.textIndent) < -50 && /hidden/.test(cs.overflow + cs.overflowX)) ||
                   cs.clip === 'rect(0px, 0px, 0px, 0px)';
    const bg = opaque(parseColor(cs.backgroundColor));
    let grad = parseGradient(cs.backgroundImage);
    if (grad && grad.type === 'radial') {
      // 径向半径按元素盒归一化（build 端 from/to 用 0..1 坐标）
      if (grad.rpx) {
        grad.rx = Math.max(0.05, Math.min(1, grad.rpx.x / (r.width || 1)))
        grad.ry = Math.max(0.05, Math.min(1, grad.rpx.y / (r.height || 1)))
      } else { grad.rx = 0.75; grad.ry = 0.75 }
      delete grad.rpx
    }
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
    const bc = [opaque(parseColor(cs.borderTopColor)), opaque(parseColor(cs.borderRightColor)), opaque(parseColor(cs.borderBottomColor)), opaque(parseColor(cs.borderLeftColor))];
    const bs = [cs.borderTopStyle, cs.borderRightStyle, cs.borderBottomStyle, cs.borderLeftStyle];
    const active = bs.map((s, i) => s !== 'none' && bw[i] > 0.5 && bc[i]);
    if (active.some(Boolean)) {
      const idxB = active.findIndex(Boolean);
      borders = { w: Math.round(Math.max(...bw.filter((x, i) => active[i])) * 100) / 100, c: bc[idxB] };
    }
    let texts = [];
    if (srOnly) {
      texts = [];  // 隐藏可访问性文本不成层
    } else if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && !icon) {
      const ph = el.getAttribute('placeholder')
      if (ph) {
        const fs2 = px(cs.fontSize)
        const phc = opaque(parseColor(cs.color)) || '#00000099'
        texts = [{ t: ph, x: px(r.left + sx) + 12, y: px(r.top + sy + (r.height - fs2 * 1.3) / 2), w: px(r.width) - 24, h: Math.round(fs2 * 1.3),
          fs: fs2, fw: 400, ff: firstFont(cs.fontFamily), lh: null, ls: 0,
          c: phc.slice(0, 7) + '8c', tt: null, icon: false }]
      }
    } else if (icon) {
      const lig = (el.textContent || '').trim();
      if (lig) texts = [{ t: lig, x: px(r.left + sx), y: px(r.top + sy), w: px(r.width), h: px(r.height),
        fs: px(cs.fontSize), fw: 400, ff: 'Material Symbols Outlined', lh: null, ls: 0,
        c: opaque(parseColor(cs.color)) || '#000000ff', tt: null, icon: true }];
    } else {
      for (const n of el.childNodes) {
        if (n.nodeType === 3) {
          const extra = {
            fs: px(cs.fontSize), fw: parseInt(cs.fontWeight) || 400, ff: firstFont(cs.fontFamily),
            lh: cs.lineHeight === 'normal' ? null : px(cs.lineHeight),
            ls: cs.letterSpacing === 'normal' ? 0 : px(cs.letterSpacing),
            c: opaque(parseColor(cs.color)) || '#000000ff', tt: cs.textTransform === 'none' ? null : cs.textTransform,
            icon: false
          };
          texts.push(...lineRuns(n, extra));
        }
      }
    }
    // 伪元素文本（html2sketch 成熟规则）：content 有实际文本时记录为文本层，
    // ::before 贴元素左缘、::after 贴右缘；装饰性色块伪元素留待后续版本
    if (!srOnly) {
      for (const which of ['before', 'after']) {
        try {
          const ps = getComputedStyle(el, ':' + which);
          if (!ps || ps.display === 'none' || ps.content === 'none' || ps.content === 'normal') continue;
          const ptext = (ps.content || '').replace(/^["']|["']$/g, '').trim();
          const pcolor = opaque(parseColor(ps.color));
          if (!ptext || !pcolor || parseFloat(ps.opacity) < 0.05) continue;
          const fs2 = px(cs.fontSize);
          const pw = px(ps.width) || 14;
          const bx = which === 'before' ? px(r.left + sx) : px(r.left + sx + r.width - pw);
          texts.push({ t: ptext, x: bx, y: px(r.top + sy + (r.height - fs2 * 1.3) / 2), w: pw, h: Math.round(fs2 * 1.3),
            fs: fs2, fw: parseInt(ps.fontWeight) || 400, ff: firstFont(ps.fontFamily),
            lh: cs.lineHeight === 'normal' ? null : px(cs.lineHeight), ls: px(cs.letterSpacing) || 0,
            c: pcolor, tt: cs.textTransform === 'none' ? null : cs.textTransform,
            icon: /Material Symbols/i.test(ps.fontFamily || '') });
        } catch (e) {}
      }
    }
    const shadow = parseShadow(cs.boxShadow);
    const isSemantic = SEMANTIC.has(el.tagName);
    const hasVisual = !!(bg || grad || img || bgimg || svgdata || shadow || borders || texts.length || isSemantic);
    let myIdx = parentIdx;
    if (!zeroSelf && visible && hasVisual) {
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
  out.bodyBg = opaque(parseColor(bodyCS.backgroundColor)) || '#ffffffff';
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
        # IntersectionObserver 覆盖：所有观察目标永远视为相交——滚动显现动画（reveal-on-scroll）
        # 只加类不撤类，回滚到顶后下方内容不再回到 opacity 0（画廊整片空白事故）
        page.add_init_script("""
            (() => {
              const Real = window.IntersectionObserver
              if (!Real) return
              window.IntersectionObserver = class extends Real {
                constructor(cb, opts) {
                  super((entries, obs) => {
                    try {
                      entries = entries.map(e => {
                        if (e.isIntersecting) return e
                        const fake = { isIntersecting: true, target: e.target,
                          intersectionRatio: Math.max(e.intersectionRatio, 0.1),
                          boundingClientRect: e.boundingClientRect, intersectionRect: e.intersectionRect,
                          rootBounds: e.rootBounds, time: e.time }
                        Object.setPrototypeOf(fake, Object.getPrototypeOf(e))
                        return fake
                      })
                    } catch (err) {}
                    cb(entries, obs)
                  }, opts)
                }
                observe(t) { try { super.observe(t) } catch (e) {} }
              }
            })()
        """)
        page.goto(f"file://{os.path.abspath(args.html)}", wait_until="networkidle", timeout=60000)
        # 滚动全页触发懒加载（full_page 截图不会触发 IntersectionObserver，首屏外懒图片曾整片空白）
        total_h = page.evaluate("() => document.documentElement.scrollHeight")
        y = 0
        while y < total_h:
            page.evaluate("(y) => window.scrollTo(0, y)", y)
            page.wait_for_timeout(220)
            y += 600
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        # 强制显现：站点 reveal-on-scroll（.rv 等）在滚动/回顶过程中反复加删显隐类，
        # 剥脚本后永远卡在 opacity 0。对静态/相对定位的半透明显现容器直写内联样式
        # （悬浮层 absolute/fixed 不动，防止 hover 遮罩被误显）
        page.evaluate("""() => {
          const revealish = /(^|\\s)(rv|reveal|fade|fade-in|appear|animate|in-view)(\\s|$)/i
          let n = 0
          document.querySelectorAll('*').forEach(el => {
            if (el.__rvFix) return
            const cs = getComputedStyle(el)
            if (parseFloat(cs.opacity) < 0.05 && cs.display !== 'none' && cs.visibility !== 'hidden' &&
                cs.position !== 'absolute' && cs.position !== 'fixed') {
              const cls = el.getAttribute('class') || ''
              if (revealish.test(cls) || /opacity/.test(cs.transition || '')) {
                el.style.opacity = '1'; el.style.transform = 'none'; el.__rvFix = true; n++
              }
            }
          })
          return n
        }""")
        page.wait_for_timeout(200)
        page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
        page.wait_for_timeout(600)
        page.evaluate(WALKER_JS)  # 预跑一遍：触发懒加载与入场动画
        page.wait_for_timeout(500)  # 等淡入/延时组件安定——walker 读到 opacity 0 会整页漏提取（登录页事故）
        layout = page.evaluate(WALKER_JS)
        page.wait_for_timeout(100)
        if not args.no_screenshot:
            # Chromium captureBeyondViewport 对视口外已加载图片常渲染空白（画廊空白事故），
            # 改为视口分片截图 + 拼接。第 2 片起 display:none 掉 fixed/sticky：
            # 悬浮层（导航/遮罩/模态/toast）定格在第一片（= full_page 语义：fixed 只画在滚动 0 处），
            # 后续片是纯文档内容。不能用 visibility:hidden——会被子元素 visibility:visible
            # 覆盖导致模态卡片残影（下架确认事故）
            import io as _io
            from PIL import Image as _PILImage
            vh = page.evaluate("() => window.innerHeight")
            total_h = max(page.evaluate("() => document.documentElement.scrollHeight"), vh)
            tiles = []
            positions = []
            pos = 0
            while pos < total_h:
                sy = min(pos, max(0, total_h - vh))
                page.evaluate("(y) => window.scrollTo(0, y)", sy)
                page.wait_for_timeout(120)
                if tiles:
                    page.evaluate("""() => {
                      document.querySelectorAll('*').forEach(el => {
                        if (el.__hid2) return
                        const cs = getComputedStyle(el)
                        if ((cs.position === 'fixed' || cs.position === 'sticky') && cs.display !== 'none') {
                          el.style.display = 'none'; el.__hid2 = true
                        }
                      })
                    }""")
                    page.evaluate("(y) => window.scrollTo(0, y)", sy)  # 隐藏后重落位
                    page.wait_for_timeout(80)
                tiles.append(page.screenshot())
                positions.append(sy)
                pos += vh
            page.evaluate("() => window.scrollTo(0, 0)")
            imgs = [_PILImage.open(_io.BytesIO(t)) for t in tiles]
            canvas = _PILImage.new("RGB", (imgs[0].width, total_h), (255, 255, 255))
            prev_end = 0
            for im, sy in zip(imgs, positions):
                # 每片只贴不重叠条带：文档区间 [sy, sy+vh] 与已填区 [0, prev_end] 取交
                top = max(sy, prev_end)
                bot = min(sy + im.height, total_h)
                if bot > top:
                    canvas.paste(im.crop((0, top - sy, im.width, bot - sy)), (0, top))
                    prev_end = bot
            canvas.save(os.path.join(outdir, "reference.png"))
        browser.close()

    layout["viewport"]["w"] = width

    # 图片一律落盘为 assets 文件、只保留 path 引用——管线中不允许存在 base64
    # （提取时烘焙出的 data URL 在此处立即转文件）；outdir 强制绝对路径，
    # 相对路径会被 Sketch 进程按自身 cwd 解析导致图片全部加载失败
    outdir = os.path.abspath(outdir)
    import base64 as _b64
    assets_dir = os.path.join(outdir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    n_baked = 0
    for e in layout.get("els", []):
        for key in ("img", "bgimg"):
            im = e.get(key)
            if not im:
                continue
            data = im.get("data")
            if data and "," in data:
                n_baked += 1
                p = os.path.join(assets_dir, f"{key}_{n_baked:03d}.png")
                try:
                    with open(p, "wb") as f:
                        f.write(_b64.b64decode(data.split(",", 1)[1]))
                    im["path"] = p
                except Exception as ex:
                    print(f"WARN bake save failed {key}: {ex}", file=sys.stderr)
                im.pop("data", None)

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
