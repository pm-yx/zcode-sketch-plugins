#!/usr/bin/env python3
"""layout.json -> native Sketch document, driven through the local Sketch MCP
server's run_code tool (http://localhost:31126/mcp).

Builds module-by-module for stability on long pages:
  phase init    — create doc + page + empty Frame (returns frameId)
  phase module  — build one element chunk into the existing Frame (finds it by id)
  phase finish  — save document + export Frame PNG for comparison

Layers are named with design roles (背景 / 卡片 / 元素 / 氛围光 / 文本 / 图标 / 图像),
images are downloaded/baked to local files first and placed 1:1.

Known sandbox bug (empirically confirmed): `[fn(x)]` — an identifier function
call directly inside an array literal — triggers a bogus SyntaxError. Never
write that pattern; assign to a temp variable first.

Usage:
  build_sketch.py <layout.json> --phase all [--name NAME] [--save PATH.sketch]
                   [--export-dir DIR] [--max-module-els N]
  build_sketch.py <layout.json> --phase init|module|finish ... [--chunk N]
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request

MCP_URL = os.environ.get("SKETCH_MCP_URL", "http://localhost:31126/mcp")
MAX_MODULE_ELS = 60


class Mcp:
    def __init__(self, url=MCP_URL):
        self.url = url
        self.session = None
        self._id = 0

    def _post(self, obj, timeout=120):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, data=json.dumps(obj).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if not self.session and "Mcp-Session-Id" in r.headers:
                self.session = r.headers["Mcp-Session-Id"]
            return r.read().decode()

    def _rpc(self, method, params=None, timeout=120):
        self._id += 1
        obj = {"jsonrpc": "2.0", "id": self._id, "method": method}
        if params is not None:
            obj["params"] = params
        raw = self._post(obj, timeout)
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("id") == self._id:
                return d
        return json.loads(raw)

    def connect(self):
        r = self._rpc("initialize", {"protocolVersion": "2024-11-05",
                                     "capabilities": {},
                                     "clientInfo": {"name": "stitch2sketch", "version": "0.1.0"}})
        if "error" in r:
            raise RuntimeError(f"MCP initialize failed: {r['error']}")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def run_code(self, script, title, timeout=300):
        r = self._rpc("tools/call", {"name": "run_code",
                                     "arguments": {"script": script, "title": title}},
                      timeout=timeout)
        if "error" in r:
            raise RuntimeError(f"run_code transport error: {r['error']}")
        result = r.get("result", {})
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        return "\n".join(texts), bool(result.get("isError"))


INIT_JS = r"""
const sketch = require('sketch')
const { Group, Page, Style } = require('sketch/dom')
const cfg = __CFG__
let doc = null
if (cfg.reuseDocId) { for (const d of sketch.Document.getDocuments()) { if (d.id === cfg.reuseDocId) { doc = d; break } } }
if (!doc && cfg.useActiveDoc) { doc = sketch.getSelectedDocument() }
if (!doc) { doc = new sketch.Document() }
let page = null
if (cfg.pageName) { for (const p of doc.pages) { if (p.name === cfg.pageName) { page = p; break } } }
if (!page && cfg.newPage && cfg.pageName) {
  page = new Page({ parent: doc, name: cfg.pageName })
  try { page.select() } catch (e) {}
}
if (!page) {
  page = doc.selectedPage || doc.pages[0]
  if (cfg.pageName && /^(Page|画板|页面\s?\d*|\d+)$/.test(page.name)) page.name = cfg.pageName
}
const frame = new Group.Frame({ parent: page, name: cfg.frameName,
  frame: { x: cfg.x, y: cfg.y, width: cfg.viewport.w, height: cfg.viewport.h } })
frame.style.fills = [{ color: cfg.bodyBg, fillType: Style.FillType.Color }]
console.log(JSON.stringify({ ok: true, docId: doc.id, frameId: frame.id, frameName: frame.name }))
"""

MODULE_JS = r"""
const sketch = require('sketch')
const { Group, ShapePath, Text, Style, Image } = require('sketch/dom')
const cfg = __CFG__
const els = __ELS__

let doc = null
for (const d of sketch.Document.getDocuments()) {
  if (d.id === cfg.docId) { doc = d; break }
}
if (!doc) { doc = sketch.getSelectedDocument(); if (!doc) { throw new Error('document not found: ' + cfg.docId) } }
let frame = null
for (const p of doc.pages) {
  const hit = sketch.find('#' + cfg.frameId, p)
  if (hit && hit.length) { frame = hit[0]; break }
}
if (!frame) { throw new Error('frame not found: ' + cfg.frameId) }

const origin = { '-1': { x: 0, y: 0 } }  // els 坐标本就是 Frame 内内容坐标，直接挂 Frame 不做画布偏移
const home = { '-1': frame }
for (const k in cfg.parentMap) { origin[k] = { x: cfg.parentMap[k].ox, y: cfg.parentMap[k].oy }; home[k] = cfg.parentMap[k].id }

function nm(e, dflt) {
  if (e.dname) return e.dname
  return (dflt || e.tag || '').slice(0, 60)
}
function fw(w) { return Math.max(1, Math.min(12, Math.round(w / 100))) }
function toD(item) {
  if (item.tag === 'path') return item.d
  if (item.tag === 'line') return 'M ' + item.x1 + ' ' + item.y1 + ' L ' + item.x2 + ' ' + item.y2
  if (item.tag === 'polyline' || item.tag === 'polygon') {
    const nums = (item.points || '').trim().split(/[\s,]+/).map(Number).filter(function (v) { return !isNaN(v) })
    if (nums.length < 4) return ''
    let d = 'M ' + nums[0] + ' ' + nums[1]
    for (let k = 2; k + 1 < nums.length; k += 2) d += ' L ' + nums[k] + ' ' + nums[k + 1]
    if (item.tag === 'polygon') d += ' Z'
    return d
  }
  if (item.tag === 'circle') return 'M ' + (item.cx - item.cr) + ' ' + item.cy + ' a ' + item.cr + ' ' + item.cr + ' 0 1 0 ' + (2 * item.cr) + ' 0 a ' + item.cr + ' ' + item.cr + ' 0 1 0 ' + (-2 * item.cr) + ' 0 Z'
  if (item.tag === 'ellipse') return item.rx > 0 && item.ry > 0 ? 'M ' + (item.cx - item.rx) + ' ' + item.cy + ' a ' + item.rx + ' ' + item.ry + ' 0 1 0 ' + (2 * item.rx) + ' 0 a ' + item.rx + ' ' + item.ry + ' 0 1 0 ' + (-2 * item.rx) + ' 0 Z' : ''
  if (item.tag === 'rect') {
    const x = item.x, y = item.y, w = item.w, h = item.h
    const r = Math.min(item.cr || 0, w / 2, h / 2)
    if (!r) return 'M ' + x + ' ' + y + ' H ' + (x + w) + ' V ' + (y + h) + ' H ' + x + ' Z'
    return 'M ' + (x + r) + ' ' + y + ' H ' + (x + w - r) +
      ' A ' + r + ' ' + r + ' 0 0 1 ' + (x + w) + ' ' + (y + r) + ' V ' + (y + h - r) +
      ' A ' + r + ' ' + r + ' 0 0 1 ' + (x + w - r) + ' ' + (y + h) +
      ' H ' + (x + r) + ' A ' + r + ' ' + r + ' 0 0 1 ' + x + ' ' + (y + h - r) +
      ' V ' + (y + r) + ' A ' + r + ' ' + r + ' 0 0 1 ' + (x + r) + ' ' + y + ' Z'
  }
  return ''
}
function mkGradient(e) {
  if (e.grad.type === 'radial') {
    // radial：from=圆心，to=水平半径端点（CSS 椭圆径向渐变的近似映射）
    const c = e.grad.from || { x: 0.5, y: 0.5 }
    const rx = e.grad.rx != null ? e.grad.rx : 0.5
    return { fillType: Style.FillType.Gradient,
      gradient: { gradientType: Style.GradientType.Radial,
        from: { x: c.x, y: c.y }, to: { x: Math.min(1, c.x + rx), y: c.y },
        stops: e.grad.stops.map(function (s) { return { position: s.pos, color: s.c } }) } }
  }
  const a = e.grad.angle * Math.PI / 180
  const dx = Math.sin(a), dy = -Math.cos(a)
  const adx = Math.abs(dx) > 1e-6 ? Math.abs(dx) : 1e-6
  const ady = Math.abs(dy) > 1e-6 ? Math.abs(dy) : 1e-6
  const t = Math.min(0.5 / adx, 0.5 / ady)  // 端点收敛到形状边界内，方向严格不变；对角渐变= 角到角（设计主流形态）
  const fx = 0.5 - dx * t, fy = 0.5 - dy * t
  const tx = 0.5 + dx * t, ty = 0.5 + dy * t
  return { fillType: Style.FillType.Gradient,
    gradient: { gradientType: Style.GradientType.Linear,
      from: { x: fx, y: fy }, to: { x: tx, y: ty },
      stops: e.grad.stops.map(function (s) { return { position: s.pos, color: s.c } }) } }
}

function mapFont(ff) {
  if (!ff) return ff
  // CSS 通用族 → 本机已装的等价字体，避免静默回落
  if (/^monospace$/i.test(ff)) return 'JetBrains Mono'
  if (/^sans-serif$/i.test(ff)) return 'PingFang SC'
  return ff
}

let counts = { group: 0, rect: 0, text: 0, img: 0, aura: 0 }
const containers = {}
for (let i = 0; i < els.length; i++) {
  const e = els[i]
  const pIdx = (home[e.p] !== undefined) ? e.p : -1
  let parent = home[pIdx]
  let ox = origin[pIdx].x, oy = origin[pIdx].y
  if (!parent) { parent = frame; ox = frame.frame.x; oy = frame.frame.y }

  const needsBox = e.bg || (e.grad && (e.grad.type === 'linear' || e.grad.type === 'radial')) || e.b || e.sw
  const hasVisual = needsBox || e.aura || e.img || e.bgimg
  let container = parent, cx = ox, cy = oy
  const idx = String(e.i)

  if (e.group) {
    const g = new Group({ parent: parent, name: nm(e, e.tag) })
    g.frame = { x: e.x - ox, y: e.y - oy, width: e.w, height: e.h }
    if (e.op < 1) g.style.opacity = e.op
    home[idx] = g; origin[idx] = { x: e.x, y: e.y }
    container = g; cx = e.x; cy = e.y
    containers[idx] = '' + g.sketchObject.objectID()
    counts.group++
  } else if (e.kids) {
    home[idx] = parent; origin[idx] = { x: ox, y: oy }
    containers[idx] = null
  }

  if (needsBox || e.aura) {
    const sh = new ShapePath({ parent: container, name: nm(e, 'rect'),
      frame: { x: e.x - cx, y: e.y - cy, width: e.w, height: e.h }, style: { fills: [] } })
    if (e.aura) {
      sh.shapeType = ShapePath.ShapeType.Oval
      const edge = e.aura.slice(0, 7) + '00'
      const radial = { fillType: Style.FillType.Gradient,
        gradient: { gradientType: Style.GradientType.Radial,
          from: { x: 0.5, y: 0.5 }, to: { x: 1, y: 1 },
          stops: [{ position: 0, color: e.aura }, { position: 1, color: edge }] } }
      sh.style.fills = [radial]
      counts.aura++
    } else {
      if (e.grad && e.grad.type === 'linear') {
        const g = mkGradient(e)
        sh.style.fills = [g]
      } else if (e.bg) {
        sh.style.fills = [{ color: e.bg, fillType: Style.FillType.Color }]
      }
      if (e.r) { try { sh.style.corners.radii = e.r } catch (err) {} }
      counts.rect++
    }
    if (e.b) sh.style.borders = [{ color: e.b.c, thickness: e.b.w, enabled: true, position: Style.BorderPosition.Inside }]
    if (e.sw) sh.style.shadows = [{ color: e.sw.c, x: e.sw.x, y: e.sw.y, blur: e.sw.blur, spread: e.sw.spread, enabled: true }]
  }

  if (e.svgdata && cfg.svgMode !== 'raster') {
    let vectorized = true
    try {
      const sd = e.svgdata
      const vbw = sd.viewBox.w || e.w, vbh = sd.viewBox.h || e.h
      const sx = e.w / vbw, sy = e.h / vbh
      const ds = sd.paths.map(function(item){ return { d: toD(item), item: item } })
      // 任一形状无法矢量化（line/circle 无路径数据）就整体回退光栅烘焙，避免图表缺件
      if (!ds.length || ds.some(function(x){ return !x.d })) { vectorized = false }
      else for (const x of ds) {
        const item = x.item
        const sp = ShapePath.fromSVGPath(x.d)
        sp.parent = container
sp.name = (cfg.lang === 'en' ? 'Chart Path · ' : '图表路径 · ') + item.tag
        const bb = item.bbox || { x: 0, y: 0, w: vbw, h: vbh }
        sp.frame = { x: e.x - cx + bb.x * sx, y: e.y - cy + bb.y * sy,
          width: Math.max(bb.w * sx, 0.2), height: Math.max(bb.h * sy, 0.2) }
        if (item.op < 1) sp.style.opacity = item.op
        if (typeof item.fill === 'string' && item.fill) {
          const fsolid = { color: item.fill, fillType: Style.FillType.Color }
          sp.style.fills = [fsolid]
        } else if (item.fill && item.fill.grad) {
          const gobj = mkGradient({ grad: item.fill.grad, w: Math.max(bb.w * sx, 1), h: Math.max(bb.h * sy, 1) })
          sp.style.fills = [gobj]
        }
        if (typeof item.stroke === 'string' && item.stroke) {
          const bw = Math.max(item.sw * (sx + sy) / 2, 0.3)
          sp.style.borders = [{ color: item.stroke, thickness: bw, enabled: true }]
        } else if (item.stroke && item.stroke.grad) {
          const stp = item.stroke.grad.stops
          const mid = stp[Math.floor(stp.length / 2)]
          const bw2 = Math.max(item.sw * (sx + sy) / 2, 0.3)
          sp.style.borders = [{ color: mid.c, thickness: bw2, enabled: true }]
        }
      }
      if (vectorized) counts.svg = (counts.svg || 0) + 1
    } catch (err) {
      vectorized = false
      console.log('SVG-VECTOR-FAIL ' + err)
    }
    if (!vectorized && e.svgdata.path) {
      try {
        const im2 = new Image({ parent: container, name: nm(e, 'svg'),
          frame: { x: e.x - cx, y: e.y - cy, width: e.w, height: e.h } })
        im2.image = { path: e.svgdata.path }
        counts.img++
      } catch (err) { console.log('SVGFALLBACKERR ' + err) }
    }
  }
  if (e.img && e.img.path) {
    try {
      const im = new Image({ parent: container, name: '图像 · ' + nm(e, 'image'),
        frame: { x: e.x - cx, y: e.y - cy, width: e.w, height: e.h } })
      im.image = { path: e.img.path }
      if (e.r) { try { im.style.corners.radii = e.r } catch (err) {} }
      counts.img++
    } catch (err) { console.log('IMGERR ' + err) }
  }
  if (e.bgimg && e.bgimg.path) {
    try {
      const im = new Image({ parent: container, name: '背景图 · ' + nm(e, 'bg-image'),
        frame: { x: e.x - cx, y: e.y - cy, width: e.w, height: e.h } })
      im.image = { path: e.bgimg.path }
      counts.img++
    } catch (err) { console.log('BGIMGERR ' + err) }
  }
  if (e.texts) {
    for (const t of e.texts) {
      const tx = new Text({
        parent: container, name: (t.icon ? (cfg.lang === 'en' ? 'Icon · ' : '图标 · ') : '') + t.t.slice(0, 30),
        text: t.t,
        style: {
          fontFamily: mapFont(t.ff) || 'Plus Jakarta Sans',
          fontSize: t.fs,
          fontWeight: t.icon ? 4 : fw(t.fw),
          textColor: t.c,
          alignment: t.ta === 'center' ? Text.Alignment.center : t.ta === 'right' ? Text.Alignment.right : Text.Alignment.left
        }
      })
      if (t.lh) { try { tx.style.lineHeight = t.lh } catch (err) {} }
      if (t.ls) { try { tx.style.letterSpacing = t.ls } catch (err) {} }
      if (t.ta === 'center') tx.frame = { x: e.x - cx, y: t.y - cy, width: e.w, height: t.h }
      else if (t.w > 0) tx.frame = { x: t.x - cx, y: t.y - cy, width: t.w, height: t.h }
      else tx.frame = { x: e.x - cx, y: t.y - cy, width: Math.max(10, e.w - (t.x - e.x)), height: t.h }
      counts.text++
    }
  }
}
console.log(JSON.stringify({ ok: true, module: cfg.module, counts: counts, containers: containers }))
"""

FINISH_JS = r"""
const sketch = require('sketch')
const cfg = __CFG__
let doc = null
for (const d of sketch.Document.getDocuments()) {
  if (d.id === cfg.docId) { doc = d; break }
}
if (!doc) { throw new Error('document not found') }
let frame = null
for (const p of doc.pages) {
  const hit = sketch.find('#' + cfg.frameId, p)
  if (hit && hit.length) { frame = hit[0]; break }
}
let exported = null
if (cfg.exportDir && frame) {
  sketch.export(frame, { output: cfg.exportDir, filename: cfg.frameName + '.png', formats: ['png'], scales: '1' })
  exported = cfg.exportDir + '/' + cfg.frameName + '.png'
}
if (cfg.savePath) { doc.save(cfg.savePath) }
let layers = 0
if (frame) { layers = frame.layers.length }
console.log(JSON.stringify({ ok: true, exported: exported, saved: cfg.savePath || null, topLevelLayers: layers, frameId: frame ? frame.id : null }))
"""


def role_of(e, viewport):
    """设计语义分层: 背景/卡片/元素/氛围光/文本/图标/图像 (design-layer theory)."""
    tag, cls = e.get("tag", ""), e.get("cls", "")
    if e.get("aura"):
        return "氛围光"
    if tag in ("header", "nav", "footer"):
        return {"header": "页头", "nav": "导航", "footer": "页脚"}[tag]
    if tag == "main":
        return "内容区"
    if e.get("img") or e.get("bgimg"):
        return "图像"
    if e.get("grad") or (e.get("bg") and (e.get("r") or e.get("sw"))):
        return "卡片"
    if e.get("bg"):
        return "色块"
    if tag == "section":
        return "卡片组"
    return "元素"


ROLE_ZH = {
    "header": "顶部导航", "nav": "导航菜单", "footer": "页脚", "main": "内容区",
    "section": "区块", "article": "内容卡片", "button": "按钮", "a": "链接",
    "input": "输入框", "textarea": "文本域", "select": "下拉选择", "form": "表单区",
    "ul": "列表", "ol": "列表", "li": "列表项", "img": "图像", "svg": "矢量图形",
    "table": "表格", "aside": "侧栏",
}
ROLE_EN = {
    "header": "Top Navbar", "nav": "Nav Menu", "footer": "Footer", "main": "Content",
    "section": "Section", "article": "Card", "button": "Button", "a": "Link",
    "input": "Input", "textarea": "Textarea", "select": "Select", "form": "Form",
    "ul": "List", "ol": "List", "li": "List Item", "img": "Image", "svg": "Vector Graphic",
    "table": "Table", "aside": "Sidebar",
}

def design_name(e, tag_role, snippet, lang):
    """设计语义命名：角色(官方设计语言) + 内容摘要，不出现工程框架类名。"""
    t = e.get("tag", "")
    if t in ("input", "textarea", "select", "button", "a", "nav", "header", "footer", "table"):
        role = tag_role[t]
    elif e.get("svgdata"):
        role = "图表" if lang == "zh" else "Chart"
    elif e.get("img") or e.get("bgimg"):
        role = "图像" if lang == "zh" else "Image"
    elif e.get("grad") or (e.get("bg") and (e.get("r") or e.get("sw"))):
        role = "卡片" if lang == "zh" else "Card"
    elif e.get("bg"):
        role = "背景色块" if lang == "zh" else "Color Block"
    elif t in ("h1", "h2", "h3", "h4", "h5", "h6"):
        role = "标题" if lang == "zh" else "Heading"
    else:
        role = tag_role.get(t, ("元素" if lang == "zh" else "Element"))
    limit = 10 if lang == "zh" else 16
    if snippet:
        return f"{role} · {snippet[:limit]}"
    return role


def _sanitize(s):
    """Sketch MCP 沙箱无法传输 ASCII 双引号/反斜杠（任何转义形式都会截断脚本），
    设计文本里用弯引号/全角斜杠替代，视觉几乎无差。"""
    return s.replace("\\", "＼").replace('"', "”")


def prepare(layout, outdir, keep_aura=False, naming_lang="zh"):
    """Slim elements, classify roles, resolve images to local files."""
    has_kids = set()
    for e in layout["els"]:
        if e.get("p", -1) >= 0:
            has_kids.add(e["p"])
    assets = os.path.join(outdir, "assets")
    os.makedirs(assets, exist_ok=True)
    els = []
    n = 0
    for i, e in enumerate(layout["els"]):
        if e.get("grad") and e["grad"].get("type") != "linear":
            e["grad"] = None
        s = {k: e[k] for k in ("tag", "x", "y", "w", "h", "op") if k in e}
        s["i"] = i
        s["p"] = e.get("p", -1)
        cls = e.get("cls", "")
        if cls:
            s["cls"] = _sanitize(cls)
        if e.get("label"):
            s["label"] = _sanitize(e["label"])
        if e.get("svgdata"):
            sd2 = s.get("svgdata") or e["svgdata"]
            sd2.pop("data", None)
            s["svgdata"] = sd2
        for k in ("fixed", "vpTop", "vpBottom"):
            if k in e and k not in s:
                s[k] = e[k]
        if re.search(r"blur-(2xl|3xl)", cls or "") and e.get("bg"):
            if keep_aura:
                s["aura"] = e["bg"]
            else:
                continue  # 氛围光默认省略：设计稿中卡片即纯渐变/底色，blur 光晕不落地
        else:
            for k in ("bg", "grad", "b", "sw", "r"):
                if e.get(k) is not None:
                    s[k] = e[k]
        im = e.get("img")
        if im and im.get("svg"):
            # svg 光栅烘焙：只留路径引用（载荷不带 base64/svg 标记，统一走文件）
            n += 1
            path = im.get("path") or os.path.join(assets, f"svg_{n:03d}.png")
            if not im.get("path") and im.get("data"):
                b64 = im["data"].split(",", 1)[1] if "," in im["data"] else im["data"]
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
            sd = e.get("svgdata") or {}
            sd["path"] = path
            s["svgdata"] = sd
            s.pop("img", None)
        for key in ("img", "bgimg"):
            im = e.get(key)
            if not im or im.get("svg"):
                continue
            n += 1
            path = os.path.join(assets, f"{key}_{n:03d}.png")
            if im.get("path"):
                s[key] = {"path": im["path"]}  # 提取阶段已落盘，直接引用
                continue
            if im.get("data"):
                b64 = im["data"].split(",", 1)[1] if "," in im["data"] else im["data"]
                with open(path, "wb") as f:
                    f.write(base64.b64decode(b64))
            elif im.get("src", "").startswith(("http://", "https://")):
                try:
                    urllib.request.urlretrieve(im["src"], path)  # 先下载，再传入 Sketch
                except Exception as ex:
                    print(f"WARN download failed {im['src']}: {ex}", file=sys.stderr)
                    continue
            elif im.get("src", "").startswith("file://"):
                # src 是百分号编码的 file URL，必须解码成真实文件系统路径
                from urllib.parse import unquote as _uq
                path = _uq(im["src"][7:])
            else:
                continue
            im2 = {"path": path}
            s[key] = im2
        if e.get("texts"):
            s["texts"] = e["texts"]
            for t in s["texts"]:
                t["t"] = _sanitize(t["t"])
            for t in s["texts"]:
                for k in ("lh", "tt"):
                    if t.get(k) in (None, 0):
                        t.pop(k, None)
        # 溢出裁剪：装饰性叶子元素(氛围光/纯色块)被 overflow-hidden 容器裁剪，
        # 几何收敛到与裁剪盒的交集，避免色块戳出卡片边缘
        clip = e.get("clip")
        if clip and not s.get("kids") and not s.get("texts"):
            ix0, iy0 = max(s["x"], clip["x"]), max(s["y"], clip["y"])
            ix1 = min(s["x"] + s["w"], clip["x"] + clip["w"])
            iy1 = min(s["y"] + s["h"], clip["y"] + clip["h"])
            if ix1 - ix0 > 0.5 and iy1 - iy0 > 0.5 and (ix0 > s["x"] + 0.5 or iy0 > s["y"] + 0.5 or ix1 < s["x"] + s["w"] - 0.5 or iy1 < s["y"] + s["h"] - 0.5):
                s["x"], s["y"] = round(ix0, 2), round(iy0, 2)
                s["w"], s["h"] = round(ix1 - ix0, 2), round(iy1 - iy0, 2)
        s["kids"] = i in has_kids
        s["role"] = ("氛围光" if s.get("aura") else role_of(e, layout["viewport"]))
        els.append(s)

    # 幽灵节点压缩：不会成为 Group 的纯布局容器（无视觉样式），其子元素父引用
    # 直接跳过它指向最近的"会成组"祖先 —— 消除跨模块 null 容器引用。
    by_i = {e["i"]: e for e in els}
    # 层级管理：直接子元素数（用压缩前的父引用统计）
    kidn = {}
    for e in els:
        kidn[e["p"]] = kidn.get(e["p"], 0) + 1
    page_area = float(layout["viewport"]["w"]) * float(layout["viewport"]["h"])
    def becomes_group(e):
        needs_box = e.get("bg") or e.get("grad") or e.get("b") or e.get("sw")
        has_visual = needs_box or e.get("aura") or e.get("img") or e.get("bgimg") or e.get("svgdata")
        if has_visual and (e.get("kids") or e.get("texts")):
            return True
        # 大模块卡片要有文件夹层级：无视觉样式的结构性容器，子元素够多或块面够大也保留成组
        if e.get("kids") and (kidn.get(e["i"], 0) >= 4 or (e.get("w") or 0) * (e.get("h") or 0) >= page_area * 0.12):
            return True
        return False
    memo = {}
    cycles = 0
    def resolve_p(start):
        nonlocal cycles
        path, seen = [], set()
        i = start
        while True:
            if i == -1 or i in memo:
                root = memo.get(i, -1); break
            if i in seen:
                cycles += 1; root = -1; break
            e = by_i.get(i)
            if e is None:
                root = -1; break
            if becomes_group(e):
                root = i; break
            seen.add(i); path.append(i)
            i = e["p"]
        for j in path:
            memo[j] = root
        return root
    for e in els:
        if e["p"] != -1:
            e["p"] = resolve_p(e["p"])
    els[:] = [e for e in els if becomes_group(e) or e.get("texts") or e.get("img") or e.get("bgimg")
              or e.get("svgdata") or e.get("bg") or e.get("grad") or e.get("b") or e.get("sw") or e.get("aura")]
    if cycles:
        print(f"WARN: {cycles} parent-reference cycles collapsed to frame root", file=sys.stderr)

    # 过滤后索引重映射：压缩阶段的 p 指向"旧下标"，过滤删除元素后必须重编号，
    # 否则前向引用/错位（与提取器同类 bug）
    old_to_new = {}
    for j, e in enumerate(els):
        old_to_new[e["i"]] = j
        e["i"] = j
    for e in els:
        if e["p"] != -1:
            e["p"] = old_to_new.get(e["p"], -1)

    # 同列表卡片样式归一：同父同标签 ≥3 个的兄弟，纯色底/边框出现细微色差时吸附到众数，
    # 防止同款卡片因逐像素还原看起来颜色不一致
    kids_map = {}
    for e in els:
        kids_map.setdefault(e["p"], []).append(e)
    geo = {e["i"]: (e["x"], e["y"], e["w"], e["h"]) for e in els}
    by_new = {e["i"]: e for e in els}

    def _rgb(s):
        s = (s or "").strip()
        if not s.startswith("#") or len(s) < 7:
            return None
        try:
            return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            return None

    def _close(a, b, tol=3):
        ra, rb = _rgb(a), _rgb(b)
        return ra is not None and rb is not None and all(abs(x - y) <= tol for x, y in zip(ra, rb))

    snapped = 0
    for _p, kids in kids_map.items():
        series = {}
        for c in kids:
            if c.get("tag"):
                series.setdefault(c["tag"], []).append(c)
        for grp in series.values():
            if len(grp) < 3:
                continue
            for get, setv in ((lambda c: c.get("bg"), lambda c, v: c.__setitem__("bg", v)),
                              (lambda c: c["b"]["c"] if isinstance(c.get("b"), dict) else None,
                               lambda c, v: c["b"].__setitem__("c", v))):
                cnt = {}
                for c in grp:
                    v = get(c)
                    if v:
                        cnt[v] = cnt.get(v, 0) + 1
                if len(cnt) < 2:
                    continue
                mode = max(cnt, key=lambda v: cnt[v])
                if cnt[mode] < 2:
                    continue
                for c in grp:
                    v = get(c)
                    if v and v != mode and _close(v, mode):
                        setv(c, mode)
                        snapped += 1
    if snapped:
        print(f"INFO: {snapped} 处同款卡片细微色差吸附到众数", file=sys.stderr)

    # 背景统一：子元素纯色底与最近祖先（或画板 bodyBg）相同时不再切块铺底，
    # 消除"统一背景被切成多块"的同色拼接缝；贴父级边+父级圆角的保守跳过防止角部戳色
    def _norm(s):
        return (s or "").strip().lower()

    def _walk_bg(i, inherited):
        for c in kids_map.get(i, []):
            col = c.get("bg") if isinstance(c.get("bg"), str) else None
            if col and inherited and _norm(col) == _norm(inherited):
                c["_dropbg"] = True
                _walk_bg(c["i"], inherited)
            else:
                _walk_bg(c["i"], col or inherited)

    body_bg = (layout.get("bodyBg") or "#ffffffff").strip().lower()
    _walk_bg(-1, body_bg)
    dropped = 0
    for e in els:
        if not e.pop("_dropbg", False):
            continue
        pe = by_new.get(e["p"])
        px, py, pw, ph = geo.get(e["p"], (0, 0, layout["viewport"]["w"], layout["viewport"]["h"]))
        if pe is not None and pe.get("r"):
            inset = 1.0
            if (e["x"] <= px + inset or e["y"] <= py + inset or
                    e["x"] + e["w"] >= px + pw - inset or e["y"] + e["h"] >= py + ph - inset):
                continue  # 贴父级边的子块在圆角卡内需要自己的底，跳过抑制
        del e["bg"]
        dropped += 1
    if dropped:
        print(f"INFO: {dropped} 块与祖先同色的铺底切块已合并（背景统一）", file=sys.stderr)

    # fixed 元素归位：HTML 可滚动，fixed 元素被截在滚动 0 位置；
    # 设计稿语义里底部锚定的（如底部导航）应贴画板底部，顶部锚定的（header）贴顶部。
    page_h = layout["viewport"]["h"]
    bvh = layout.get("browserVH") or 844
    if page_h > bvh:
        children_map = {}
        for e in els:
            children_map.setdefault(e["p"], []).append(e)
        def shift(el, dy):
            el["y"] = round(el["y"] + dy, 2)
            for t in el.get("texts") or []:
                t["y"] = round(t["y"] + dy, 2)
            for c in children_map.get(el["i"], []):
                shift(c, dy)
        for e in els:
            if e.get("fixed"):
                e["was_fixed"] = True
                vp_top = e.get("vpTop")  # 先读后删：pop 掉再 get 永远是 None，会把顶锚定 header 也判成底锚定
                vp_bottom = e.pop("vpBottom", None)
                e.pop("vpTop", None)
                e.pop("fixed", None)
                if vp_bottom is None:
                    continue
                # 只归位"贴视口底的短条"（底部导航/底部按钮栏）。
                # 全视口遮罩（上下都贴边）和大于半屏的浮层保持原位——浏览器整页截图里
                # fixed 元素就渲染在视口位置，归位反而错位（modal 遮罩曾被平移到画板底）
                flush_top = vp_top is not None and vp_top <= 2
                short_bar = e["h"] <= bvh * 0.5
                if vp_bottom <= 2 and not flush_top and short_bar:
                    new_y = page_h - vp_bottom - e["h"]
                    dy = new_y - e["y"]
                    if abs(dy) > 1:
                        shift(e, dy)
            else:
                for k in ("vpBottom", "vpTop", "fixed"):
                    e.pop(k, None)

    # z 序：fixed/sticky 子树最后创建（Sketch 组内后建=上层），否则会被
    # 后画的内容区底色盖住（浏览器里 header 是 z-50 浮层）
    children_map2 = {}
    for e in els:
        children_map2.setdefault(e["p"], []).append(e["i"])
    fixed_set = set()
    def mark_tree(i):
        if i in fixed_set: return
        fixed_set.add(i)
        for c in children_map2.get(i, []): mark_tree(c)
    for e in els:
        if e.get("was_fixed"):
            mark_tree(e["i"])
    if fixed_set:
        normal = [e for e in els if e["i"] not in fixed_set]
        topmost = [e for e in els if e["i"] in fixed_set]
        els[:] = normal + topmost
        remap2 = {}
        for j, e in enumerate(els):
            remap2[e["i"]] = j
            e["i"] = j
        for e in els:
            if e["p"] != -1:
                e["p"] = remap2.get(e["p"], -1)
    for e in els:
        e.pop("was_fixed", None)

    # 设计语义命名：角色 + 内容摘要（自身文本优先，容器取首个后代文本）
    tag_role = ROLE_ZH if naming_lang == "zh" else ROLE_EN
    by_i = {e["i"]: e for e in els}  # 必须用过滤+重映射后的最新索引重建
    children_all = {}
    for e in els:
        children_all.setdefault(e["p"], []).append(e["i"])

    def subtree_size(i, memo={}):
        if i in memo:
            return memo[i]
        n = 1
        for c in children_all.get(i, []):
            n += subtree_size(c, memo)
        memo[i] = n
        return n

    def pick_snippet(el):
        # 摘要优先级：自身非图标文本 > 子树内标题(h*) > 子树最长短文本(≤24) > 图标名
        best = ""
        for t in el.get("texts") or []:
            if not t.get("icon") and 0 < len(t.get("t", "")) <= 24 and len(t["t"]) > len(best):
                best = t["t"]
        if best:
            return best
        icon_name = ""
        stack = [el["i"]]
        while stack:
            cur = by_i.get(stack.pop(0))
            if cur is None:
                continue
            for t in cur.get("texts") or []:
                tn = t.get("t", "")
                if t.get("icon"):
                    if not icon_name:
                        icon_name = tn
                elif 0 < len(tn) <= 24 and len(tn) > len(best):
                    best = tn
            stack.extend(children_all.get(cur["i"], []))
        return best or icon_name

    for e in els:
        snippet = ""
        # 大容器(整页/主内容)不用远处文本命名；小组件才带内容摘要
        if e.get("tag") not in ("body", "main", "html") and subtree_size(e["i"]) <= 20:
            snippet = pick_snippet(e)
        snippet = _sanitize(snippet.replace("\n", " ").strip())
        e["dname"] = design_name(e, tag_role, snippet, naming_lang)

    # 成组标记：python 统一判定、MODULE_JS 照建容器——两处判定必须同源，
    # 否则跨块父引用拿到 null 断链（"parent ids missing from state"）
    cnt = {}
    for e in els:
        cnt[e["p"]] = cnt.get(e["p"], 0) + 1
    for e in els:
        has_visual = bool(e.get("bg") or e.get("grad") or e.get("b") or e.get("sw")
                          or e.get("aura") or e.get("img") or e.get("bgimg") or e.get("svgdata"))
        e["group"] = bool((has_visual and (e.get("kids") or e.get("texts"))) or
                          (e.get("kids") and (cnt.get(e["i"], 0) >= 4 or
                                              (e.get("w") or 0) * (e.get("h") or 0) >= page_area * 0.12)))
    return els


def chunk_modules(els, max_els=MAX_MODULE_ELS):
    """模块拆解：兄弟子树贪心打包到同一块（≤max），超大子树按子级递归细分。
    每块内部父引用闭合；跨块父级经 parentMap 挂载。"""
    children = {}
    for e in els:
        children.setdefault(e["p"], []).append(e["i"])

    def subtree(i):
        out = [i]
        for c in children.get(i, []):
            out += subtree(c)
        return out

    def emit(root):
        st = subtree(root)
        if len(st) <= max_els:
            return [st]
        parts = [[root]]
        for c in children.get(root, []):
            parts += emit(c)
        return parts

    chunks, cur = [], []
    for root in children.get(-1, []):
        for part in emit(root):
            if len(part) > max_els:
                if cur:
                    chunks.append(cur)
                    cur = []
                chunks.append(part)
                continue
            if cur and len(cur) + len(part) > max_els:
                chunks.append(cur)
                cur = []
            cur += part
    if cur:
        chunks.append(cur)
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("layout")
    ap.add_argument("--phase", choices=["all", "init", "modules", "module", "finish"], default="all")
    ap.add_argument("--chunk", type=int, default=None, help="module index for --phase module")
    ap.add_argument("--state", default=None, help="path to build state json (docId/frameId/parentMap)")
    ap.add_argument("--name", default=None)
    ap.add_argument("--save", default=None)
    ap.add_argument("--export-dir", default=None)
    ap.add_argument("--x", type=int, default=0)
    ap.add_argument("--y", type=int, default=0)
    ap.add_argument("--max-module-els", type=int, default=MAX_MODULE_ELS)
    ap.add_argument("--svg-mode", choices=["vector", "raster"], default="vector")
    ap.add_argument("--doc-mode", choices=["new", "active"], default="new")
    ap.add_argument("--page-name", default=None)
    ap.add_argument("--doc-id", default=None)
    ap.add_argument("--new-page", action="store_true",
                    help="reuse doc: create/select a fresh page named --page-name instead of current page")
    ap.add_argument("--keep-aura", action="store_true")
    ap.add_argument("--naming-lang", choices=["zh", "en"], default="zh")
    args = ap.parse_args()

    layout = json.load(open(args.layout))
    outdir = os.path.dirname(os.path.abspath(args.layout))
    name = args.name or os.path.basename(outdir) or "Stitch Screen"
    els = prepare(layout, outdir, keep_aura=args.keep_aura, naming_lang=args.naming_lang)
    chunks = chunk_modules(els, args.max_module_els)
    state_path = args.state or os.path.join(outdir, "build_state.json")

    mcp = Mcp().connect()

    def parse_out(out):
        def unesc(s):
            s = s.strip()
            if s.startswith("'") and s.endswith("'"):
                s = s[1:-1]
            return s.replace('\\"', '"').replace("\\\\", "\\")

        def objects_on(line):
            res = []
            start = line.find("{")
            while start != -1:
                depth, in_str, esc = 0, False, False
                for k in range(start, len(line)):
                    ch = line[k]
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = not in_str
                    elif not in_str:
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                try:
                                    res.append(json.loads(line[start:k + 1]))
                                except json.JSONDecodeError:
                                    pass
                                break
                start = line.find("{", start + 1)
            return res

        best = None
        for line in out.splitlines():
            for obj in objects_on(unesc(line)):
                if "ok" in obj:
                    best = obj
        if best is None:
            raise RuntimeError("no JSON with ok marker in run_code output: " + out[:300])
        return best

    def load_state():
        return json.load(open(state_path)) if os.path.exists(state_path) else {}

    def save_state(st):
        with open(state_path, "w") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)

    def do_init():
        cfg = {"pageName": name, "frameName": name, "x": args.x, "y": args.y,
               "viewport": layout["viewport"], "bodyBg": layout.get("bodyBg", "#ffffffff"),
               "useActiveDoc": args.doc_mode == "active", "pageName": args.page_name or name,
               "reuseDocId": args.doc_id, "newPage": args.new_page}
        script = INIT_JS.replace("__CFG__", json.dumps(cfg, ensure_ascii=False))
        out, err = mcp.run_code(script, f"init {name}")
        print(out)
        if err:
            sys.exit(1)
        data = parse_out(out)
        save_state({"docId": data["docId"], "frameId": data["frameId"],
                    "parentMap": {}, "modules": len(chunks)})

    def do_module(ci):
        st = load_state()
        idxs = chunks[ci]
        subset = [els[i] for i in idxs if i < len(els)]
        by_i = {e["i"]: e for e in els}
        # cross-chunk parents: parent index not in this chunk -> needs parentMap entry
        need = set()
        in_chunk = set(idxs)
        for e in subset:
            if e["p"] not in in_chunk and e["p"] != -1:
                need.add(e["p"])
        # ancestors may themselves be in previous chunks with known ids; state covers all
        pm = st.get("parentMap", {})
        missing = [p for p in need if str(p) not in pm]
        if missing:
            raise SystemExit(f"parent ids missing from state: {missing} — rebuild earlier modules")
        cfg = {"docId": st["docId"], "frameId": st["frameId"], "module": ci, "svgMode": args.svg_mode, "lang": args.naming_lang,
               "parentMap": {str(k): v for k, v in pm.items()}}
        script = MODULE_JS.replace("__CFG__", json.dumps(cfg, ensure_ascii=False)) \
                          .replace("__ELS__", json.dumps(subset, ensure_ascii=False))
        out, err = mcp.run_code(script, f"module {ci}")
        print(out)
        if err:
            sys.exit(1)
        data = parse_out(out)
        # merge container ids for future cross-chunk parenting
        for k, v in (data.get("containers") or {}).items():
            if v:
                pm[k] = {"id": v, "ox": by_i[int(k)]["x"], "oy": by_i[int(k)]["y"]}
        st["parentMap"] = pm
        save_state(st)

    def do_finish():
        st = load_state()
        cfg = {"docId": st["docId"], "frameId": st["frameId"], "frameName": name,
               "exportDir": args.export_dir, "savePath": args.save}
        script = FINISH_JS.replace("__CFG__", json.dumps(cfg, ensure_ascii=False))
        out, err = mcp.run_code(script, f"finish {name}")
        print(out)

    if args.phase in ("all", "init"):
        do_init()
    if args.phase in ("all", "module", "modules"):
        if args.phase == "module":
            assert args.chunk is not None, "--phase module needs --chunk N"
            do_module(args.chunk)
        else:
            for ci in range(len(chunks)):
                do_module(ci)
    if args.phase in ("all", "finish"):
        do_finish()


if __name__ == "__main__":
    main()
