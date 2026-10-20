#!/usr/bin/env python3
"""交互态拆解：把任意 HTML（含 SPA/hash 路由/JS 视图切换）动态爬成一组静态屏。

浏览器加载 → 枚举可点击导航元素（单一全局序号）→ 逐个点击并对比"可见内容指纹" →
新状态则快照（剥 <script>、绝对化资源 URL）→ 按状态路径 BFS 继续爬 → 输出 screens/。

用法:
  python3 discover_screens.py <entry.html> --out <screens_dir> [--width 1440] [--max-screens 24] [--prefix admin-]

输出:
  <out>/<NN>-<slug>/code.html   静态快照（可直接喂 extract_layout.py）
  <out>/<NN>-<slug>/screen.png  浏览器基准截图
  <out>/manifest.json           屏清单（名称/hash/触发路径）
"""
import argparse
import json
import os
import re
import sys
from urllib.parse import quote

from playwright.sync_api import sync_playwright

# 可点击候选：单一过滤器 + 全局序号，点击回放与枚举共用同一份 JS（含危险动作黑名单，两处必须一致）
COLLECT_JS = r"""
() => {
  const els = []
  const add = el => { if (el && !els.includes(el)) els.push(el) }
  document.querySelectorAll('a[href^="#"]').forEach(add)
  document.querySelectorAll('[role="tab"],[role="menuitem"]').forEach(add)
  document.querySelectorAll('[onclick]').forEach(add)
  document.querySelectorAll('button,[type="button"],[type="submit"],[class*="btn" i],[class*="button" i]').forEach(add)
  document.querySelectorAll('nav a, aside a, [class*="menu"] a, [class*="menu"] li, [class*="nav"] a, [class*="tab"], [class*="Tab"]').forEach(add)
  const ok = els.filter(el => {
    const r = el.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) return false
    const st = getComputedStyle(el)
    if (st.display === 'none' || st.visibility === 'hidden' || +st.opacity === 0) return false
    const text = (el.innerText || el.getAttribute('aria-label') || '')
    if (/退出|登出|注销|删除|移除|清空|重置|撤销|logout|signout|delete|remove|reset/i.test(text)) return false
    return true
  })
  return ok.map((el, i) => ({
    i: i,
    text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
    href: (el.getAttribute('href') || '').slice(0, 60),
    how: el.hasAttribute('href') && el.getAttribute('href').startsWith('#') ? 'hash' : 'click'
  }))
}
"""

CLICK_JS = r"""
(i) => {
  const els = []
  const add = el => { if (el && !els.includes(el)) els.push(el) }
  document.querySelectorAll('a[href^="#"]').forEach(add)
  document.querySelectorAll('[role="tab"],[role="menuitem"]').forEach(add)
  document.querySelectorAll('[onclick]').forEach(add)
  document.querySelectorAll('button,[type="button"],[type="submit"],[class*="btn" i],[class*="button" i]').forEach(add)
  document.querySelectorAll('nav a, aside a, [class*="menu"] a, [class*="menu"] li, [class*="nav"] a, [class*="tab"], [class*="Tab"]').forEach(add)
  const ok = els.filter(el => {
    const r = el.getBoundingClientRect()
    if (r.width < 2 || r.height < 2) return false
    const st = getComputedStyle(el)
    if (st.display === 'none' || st.visibility === 'hidden' || +st.opacity === 0) return false
    const text = (el.innerText || el.getAttribute('aria-label') || '')
    if (/退出|登出|注销|删除|移除|清空|重置|撤销|logout|signout|delete|remove|reset/i.test(text)) return false
    return true
  })
  if (i >= ok.length) { throw new Error('candidate index out of range: ' + i + '/' + ok.length) }
  ok[i].click()
}
"""

FINGERPRINT_JS = r"""
() => {
  const norm = s => (s || '').replace(/\d+/g, '#').replace(/\s+/g, ' ').trim()
  const txt = norm(document.body.innerText).slice(0, 2500)
  let vis = 0
  const sig = []
  document.body.querySelectorAll('*').forEach(el => {
    const r = el.getBoundingClientRect()
    if (r.width > 0 && r.height > 0) {
      vis++
      if (sig.length < 4000) sig.push(el.tagName + '.' + (el.className && el.className.baseVal === undefined ? String(el.className) : '').trim().replace(/\s+/g, '.'))
    }
  })
  sig.sort()
  return { fp: (location.hash || '#') + '|' + vis + '|' + txt.slice(0, 1800),
           struct: vis + '|' + sig.join(',').slice(0, 12000) }
}
"""

SNAPSHOT_JS = r"""
() => {
  const abs = el => {
    for (const attr of ['src', 'href', 'poster', 'srcset']) {
      if (el.hasAttribute && el.hasAttribute(attr)) {
        try { const v = el[attr]; if (v) el.setAttribute(attr, v) } catch (e) {}
      }
    }
  }
  document.querySelectorAll('img,link,source,iframe,video,audio,embed,a').forEach(abs)
  const base = document.baseURI
  const rewriteCss = css => css.replace(/url\((['"]?)([^'")]+)\1\)/g, (m, q, u) => {
    if (/^(data:|https?:|file:|#)/.test(u)) return m
    try { return 'url(' + new URL(u, base).href + ')' } catch (e) { return m }
  })
  document.querySelectorAll('style').forEach(s => { if (s.textContent) s.textContent = rewriteCss(s.textContent) })
  document.querySelectorAll('[style*="url("]').forEach(el => el.setAttribute('style', rewriteCss(el.getAttribute('style'))))
  document.querySelectorAll('script,noscript').forEach(el => el.remove())
  return '<!DOCTYPE html>\n' + document.documentElement.outerHTML
}
"""


def slugify(text, fallback):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (text or "").strip()).strip("-").lower()
    return (s or fallback)[:30]


class Crawler:
    def __init__(self, page, base_url, out_dir, max_screens, keep_variants=False, verbose=True):
        self.page = page
        self.base = base_url
        self.out = out_dir
        self.max = max_screens
        self.keep_variants = keep_variants
        self.verbose = verbose
        self.states = {}     # 内容指纹 -> state
        self.structs = set()  # 结构指纹（同模板不同数据去重）
        self.queue = []      # 待探索的状态点击路径
        self.used_names = set()

    def log(self, *a):
        if self.verbose:
            print(*a, flush=True)

    def reach(self, path):
        """从 base 重放点击序列到达目标状态。"""
        self.page.goto(self.base, wait_until="networkidle", timeout=30000)
        self.page.wait_for_timeout(400)
        for idx in path:
            try:
                self.page.evaluate(CLICK_JS, idx)
                self.page.wait_for_timeout(450)
            except Exception as e:
                self.log(f"    replay fail at {idx}: {e}")
                return False
        return True

    def snapshot(self, name_hint, path):
        r = self.page.evaluate(FINGERPRINT_JS)
        fp, struct = r["fp"], r["struct"]
        if fp in self.states:
            return None
        hash_part = fp.split("|", 1)[0]
        # 结构去重只作用于"详情层"（hash 深度≥2 或非 hash 的内部视图）；顶层路由互不合并
        if hash_part.startswith("#/"):
            depth = len([s for s in hash_part[2:].split("/") if s])
            is_detail = depth >= 2
        else:
            is_detail = True
        if not self.keep_variants and is_detail and struct in self.structs:
            self.log(f"  · 跳过同模板状态（结构指纹重复）: {name_hint!r}")
            return None
        n = len(self.states) + 1
        # 命名：hash 路由优先用路由模板名（#/news/4 → news-detail），否则用触发文案
        if hash_part.startswith("#/") and hash_part != "#/":
            segs = ["detail" if re.fullmatch(r"\d+|[^/]*\d[^/]*", s) else s
                    for s in hash_part[2:].split("/") if s]
            base_name = slugify("-".join(segs), f"view-{n}")
        else:
            base_name = slugify(name_hint, f"view-{n}")
        name, k = base_name, 2
        while name in self.used_names:
            name, k = f"{base_name}-{k}", k + 1
        self.used_names.add(name)
        sdir = os.path.join(self.out, f"{n:02d}-{name}")
        os.makedirs(sdir, exist_ok=True)
        with open(os.path.join(sdir, "code.html"), "w") as f:
            f.write(self.page.evaluate(SNAPSHOT_JS))
        self.page.screenshot(path=os.path.join(sdir, "screen.png"), full_page=True)
        state = {"n": n, "name": name, "dir": sdir, "hash": hash_part, "path": list(path)}
        self.states[fp] = state
        self.structs.add(struct)
        self.queue.append(list(path))
        self.log(f"  [屏 {n:02d}] {name}  hash={hash_part}  path={list(path)}")
        return state

    def run(self):
        os.makedirs(self.out, exist_ok=True)
        self.reach([])
        self.snapshot("home", [])
        while self.queue and len(self.states) < self.max:
            path = self.queue.pop(0)
            if not self.reach(path):
                continue
            cands = self.page.evaluate(COLLECT_JS)
            self.log(f"> 状态 {path}: {len(cands)} 个候选")
            for c in cands:
                if len(self.states) >= self.max:
                    break
                if not self.reach(path):
                    break
                try:
                    self.page.evaluate(CLICK_JS, c["i"])
                    self.page.wait_for_timeout(450)
                    self.snapshot(c["href"] if c["how"] == "hash" and c["href"] else c["text"],
                                  path + [c["i"]])
                except Exception as e:
                    self.log(f"    skip[{c['i']}] {c['text']!r}: {e}")
        return list(self.states.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("entry")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--max-screens", type=int, default=24)
    ap.add_argument("--prefix", default="")
    ap.add_argument("--keep-detail-variants", action="store_true",
                    help="同模板不同数据的详情页各自成屏（默认去重只留代表屏）")
    args = ap.parse_args()

    url = "file://" + quote(os.path.abspath(args.entry))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        states = Crawler(page, url, args.out, args.max_screens,
                         keep_variants=args.keep_detail_variants).run()
        browser.close()

    manifest = {"entry": os.path.abspath(args.entry), "width": args.width,
                "screens": [{"n": s["n"], "name": args.prefix + s["name"] if args.prefix else s["name"],
                             "dir": s["dir"], "hash": s["hash"], "path": s["path"]} for s in states]}
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "screens": len(states), "out": args.out}, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
