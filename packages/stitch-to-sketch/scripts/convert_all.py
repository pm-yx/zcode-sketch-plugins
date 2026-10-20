#!/usr/bin/env python3
"""Batch-convert an entire Stitch export project into ONE Sketch document.

Extracts every screen (subdirectories with code.html + the root single-page
app if present), lays frames out in a grid on one page, builds them
module-by-module through the Sketch MCP server, saves once at the end.

Usage: convert_all.py <project_dir> [--save out.sketch] [--cols 4]
"""
import argparse
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
EXTRACT = os.path.join(HERE, "extract_layout.py")
BUILD = os.path.join(HERE, "build_sketch.py")


def screens_of(project):
    items = []
    for name in sorted(os.listdir(project)):
        d = os.path.join(project, name)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "code.html")):
            items.append({"name": name, "html": os.path.join(d, "code.html"),
                          "out": os.path.join(d, "sketch_build")})
    # 根目录散置的单页 HTML（如整站高保真原型巨页）也作为屏参与转换
    for name in sorted(os.listdir(project)):
        f = os.path.join(project, name)
        if os.path.isfile(f) and name.lower().endswith(".html"):
            stem = os.path.splitext(name)[0]
            items.append({"name": stem, "html": f,
                          "out": os.path.join(project, f"{stem}_build")})
    return items


def run(cmd):
    print("+", " ".join(os.path.basename(c) if i else c for i, c in enumerate(cmd)), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout.strip():
        print("  ", r.stdout.strip().splitlines()[-1][:200], flush=True)
    if r.returncode != 0:
        print("STDERR:", r.stderr.strip()[-600:])
        raise SystemExit(f"command failed: {' '.join(cmd)}")
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--save", default=None)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--gap", type=int, default=60)
    ap.add_argument("--row-gap", type=int, default=80)
    args = ap.parse_args()

    save = args.save or os.path.join(args.project, f"{os.path.basename(args.project)}-还原.sketch")
    screens = screens_of(args.project)
    print(f"found {len(screens)} screens", flush=True)

    # 1) extract all screens (browser truth per screen)
    for s in screens:
        if os.path.isfile(os.path.join(s["out"], "layout.json")):
            print(f"skip extract (exists): {s['name']}", flush=True)
            continue
        run(["python3", EXTRACT, s["html"], "--type", "mobile", "--width", "390", "--out", s["out"]])
    layouts = {s["name"]: json.load(open(os.path.join(s["out"], "layout.json"))) for s in screens}

    # 2) grid coordinates
    xs, ys = {}, {}
    x_cursor, y_cursor, row_max, col = 0, 0, 0, 0
    for s in screens:
        v = layouts[s["name"]]["viewport"]
        xs[s["name"]], ys[s["name"]] = x_cursor, y_cursor
        x_cursor += v["w"] + args.gap
        row_max = max(row_max, v["h"])
        col += 1
        if col >= args.cols:
            col, x_cursor = 0, 0
            y_cursor += row_max + args.row_gap
            row_max = 0

    # 3) build: screen 0 creates the doc, others reuse it by id
    doc_id = None
    for i, s in enumerate(screens):
        layout = os.path.join(s["out"], "layout.json")
        state = os.path.join(s["out"], "build_state.json")
        if os.path.exists(state):
            os.remove(state)
        init_cmd = ["python3", BUILD, layout, "--phase", "init", "--name", s["name"],
                    "--page-name", "全部页面", "--x", str(xs[s["name"]]), "--y", str(ys[s["name"]])]
        if doc_id:
            init_cmd += ["--doc-id", doc_id]
        run(init_cmd)
        st = json.load(open(state))
        doc_id = st["docId"]
        run(["python3", BUILD, layout, "--phase", "modules", "--name", s["name"]])
        finish_cmd = ["python3", BUILD, layout, "--phase", "finish", "--name", s["name"],
                      "--export-dir", s["out"]]
        if i == len(screens) - 1:
            finish_cmd += ["--save", save]
        run(finish_cmd)
        print(f"== done {i + 1}/{len(screens)}: {s['name']}", flush=True)

    print(json.dumps({"done": True, "save": save, "screens": len(screens)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
