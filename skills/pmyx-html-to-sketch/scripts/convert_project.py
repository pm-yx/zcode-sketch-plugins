#!/usr/bin/env python3
"""把 discover_screens.py 产出的一个或多个 manifest 批量构建进一个 Sketch 文档。

每个 manifest（= 一个 HTML 入口）占一个 Page，屏按网格排布。
断点续跑：每屏 build_state.json 写 done 标记，中断后重跑自动跳过已完成屏。

用法:
  convert_project.py <manifest.json> [manifest2.json ...] \
      --save 输出.sketch [--naming-lang zh] [--cols 4] [--gap 60] [--row-gap 80]
      [--max-module-els 60] [--svg-mode vector]
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = os.path.join(HERE, "extract_layout.py")
BUILD = os.path.join(HERE, "build_sketch.py")


def shot_sig(path):
    """截图缩略灰度签名，用于组内视觉去重。"""
    img = Image.open(path).convert("L").resize((48, 48))
    return list(img.getdata())


def dedupe_screens(screens, log):
    """同组内 screen.png 视觉一致的后续屏剔除（发现器经不同路径捕到同一视图）。"""
    kept, seen = [], []
    for s in screens:
        shot = os.path.join(s["dir"], "screen.png")
        if not os.path.isfile(shot):
            kept.append(s)
            continue
        sig = shot_sig(shot)
        dup = any(sum(abs(a - b) for a, b in zip(sig, old)) / len(sig) < 2.0 for old in seen)
        if dup:
            log(f"  · 构建前去重（视觉一致）: {s['name']}")
            continue
        seen.append(sig)
        kept.append(s)
    return kept


def run(cmd):
    print("+", " ".join(os.path.basename(c) if i else c for i, c in enumerate(cmd)), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()
    if tail:
        print("   ", tail[-1][:200], flush=True)
    if r.returncode != 0:
        print("STDERR:", (r.stderr or "").strip()[-800:], flush=True)
        raise SystemExit("FAILED: " + " ".join(cmd))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifests", nargs="+")
    ap.add_argument("--save", required=True)
    ap.add_argument("--naming-lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--gap", type=int, default=60)
    ap.add_argument("--row-gap", type=int, default=80)
    ap.add_argument("--max-module-els", type=int, default=60)
    ap.add_argument("--svg-mode", default="vector", choices=["vector", "raster"])
    ap.add_argument("--save-every", type=int, default=0,
                    help="每构建 N 屏增量保存一次。默认 0 只在最后保存：doc.save 会改变内存"
                         " Document id，增量保存会让后续 init 的 --doc-id 失效漂移（实测只剩最后一页）")
    ap.add_argument("--per-page", type=int, default=6,
                    help="每个 Page 最多画板数，超出自动分页（画板过多会拖慢画布）")
    ap.add_argument("--doc-id", default=None,
                    help="从指定文档续建（分段构建场景：先在 Sketch 打开已保存文档，传入其 docId）")
    args = ap.parse_args()
    args.save = os.path.abspath(args.save)  # doc.save 在 Sketch 进程里解析，必须绝对路径

    raw_groups = []
    for mp in args.manifests:
        m = json.load(open(mp))
        name = m.get("pageName") or os.path.splitext(os.path.basename(m["entry"]))[0]
        screens = dedupe_screens(m["screens"], lambda *a: print(*a, flush=True))
        print(f"{name}: {len(m['screens'])} 屏发现，去重后 {len(screens)} 屏进入构建", flush=True)
        # 分页规范：{入口名}-{两位页号}，每页最多 per-page 个画板
        per = max(1, args.per_page)
        for pi in range(0, len(screens), per):
            raw_groups.append({"page": f"{name}-{pi // per + 1:02d}",
                               "screens": screens[pi:pi + per],
                               "width": m.get("width", 1440)})
    groups = raw_groups
    print("分页计划:", "、".join(f"{g['page']}({len(g['screens'])})" for g in groups), flush=True)

    if os.path.exists(args.save) and not args.doc_id:
        os.remove(args.save)  # 续建模式（--doc-id）保留已保存文件
    doc_id = args.doc_id
    built = 0
    fail_streak = 0
    for gi, g in enumerate(groups):
        coords = {}
        x = y = row_max = col = 0
        for s in g["screens"]:
            lp = os.path.join(s["dir"], "sketch_build", "layout.json")
            if not os.path.isfile(lp):
                run([sys.executable, EXTRACT, os.path.join(s["dir"], "code.html"),
                     "--type", "web", "--width", str(g["width"]), "--out",
                     os.path.join(s["dir"], "sketch_build")])
            v = json.load(open(lp))["viewport"]
            coords[s["n"]] = (x, y)
            x += v["w"] + args.gap
            row_max = max(row_max, v["h"])
            col += 1
            if col >= args.cols:
                col, x = 0, 0
                y += row_max + args.row_gap
                row_max = 0
        for si, s in enumerate(g["screens"]):
          try:
            sdir = os.path.abspath(s["dir"])  # 传给 Sketch 的路径必须绝对（Sketch 进程按自身 cwd 解析相对路径）
            state = os.path.join(sdir, "sketch_build", "build_state.json")
            st = json.load(open(state)) if os.path.exists(state) else {}
            if st.get("done"):
                print(f"skip (done): {g['page']}/{s['name']}", flush=True)
                if doc_id is None:
                    doc_id = st["docId"]
                continue
            if os.path.exists(state):
                os.remove(state)
            name = s["name"]
            cmd = [sys.executable, BUILD, os.path.join(sdir, "sketch_build", "layout.json"),
                   "--phase", "init", "--name", name, "--page-name", g["page"],
                   "--x", str(coords[s["n"]][0]), "--y", str(coords[s["n"]][1]),
                   "--naming-lang", args.naming_lang,
                   "--max-module-els", str(args.max_module_els), "--svg-mode", args.svg_mode]
            if doc_id:
                cmd += ["--doc-id", doc_id]
            if si == 0 and gi > 0:
                cmd += ["--new-page"]
            run(cmd)
            st = json.load(open(state))
            doc_id = st["docId"]
            run([sys.executable, BUILD, os.path.join(sdir, "sketch_build", "layout.json"),
                 "--phase", "modules", "--name", name, "--naming-lang", args.naming_lang,
                 "--max-module-els", str(args.max_module_els), "--svg-mode", args.svg_mode])
            fcmd = [sys.executable, BUILD, os.path.join(sdir, "sketch_build", "layout.json"),
                    "--phase", "finish", "--name", name, "--export-dir",
                    os.path.join(sdir, "sketch_build"), "--naming-lang", args.naming_lang]
            built += 1
            last = gi == len(groups) - 1 and si == len(g["screens"]) - 1
            # 增量保存：对同一打开文档反复 save 到同一路径是安全的；崩了最多丢最近 N 屏
            if last or (args.save_every and built % args.save_every == 0):
                fcmd += ["--save", args.save]
            run(fcmd)
            st = json.load(open(state))
            st["done"] = True
            with open(state, "w") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
            fail_streak = 0
            print(f"== done {g['page']}/{name}", flush=True)
          except (SystemExit, Exception) as ex:
            fail_streak += 1
            print(f"!! failed {g['page']}/{s['name']}: {str(ex)[:160]} (连续失败 {fail_streak})", flush=True)
            if fail_streak >= 2:
                raise  # 连续两屏失败视为 MCP/Sketch 死亡，中止保留断点
    print(json.dumps({"ok": True, "save": args.save}, ensure_ascii=False))


if __name__ == "__main__":
    main()
