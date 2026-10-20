---
name: pmyx-stitch-to-sketch
description: 把 Google Stitch 导出的 HTML 100% 还原为 Sketch 原生设计文件（像素级，非截图）。逐屏浏览器精确几何提取 + 计算样式，中英混排逐行折行，设计语义图层命名，SVG 图表钢笔矢量，模块化分块构建，fixed 归位/z 序，导出与浏览器基准逐像素比对。Use whenever the user mentions Stitch exports, "Stitch 转换/还原", stitch_withgoogle, or wants to convert Stitch-generated screens into an editable Sketch .sketch file.
---

# stitch-to-sketch · Stitch 导出 → Sketch 原生设计文件

把 [Google Stitch](https://stitch.withgoogle.com) 导出的 HTML 100% 还原为 Sketch 原生设计文件：
真实矩形/圆角/渐变/阴影/文本/图片/矢量图层。独立 skill，脚本内置于 `scripts/`。

## 触发方式

技能的斜杠调用由 ZCode 按安装目录名自动提供（`/pmyx-stitch-to-sketch`），自动触发靠
frontmatter description 语义匹配，无需在本文内实现。典型触发指令：

- `把 <Stitch 导出目录> 转成 sketch`
- `/pmyx-stitch-to-sketch 还原这个 Stitch 项目，移动端，图层中文命名`
- `/pmyx-stitch-to-sketch <目录> 网页端 1440，英文图层名`
- `Stitch 导出的 HTML 做成 Sketch 设计稿`

## 第 0 步：先问用户两件事

1. **项目类型**：移动端（视口宽 **390**）还是网页（**1440**）？影响 extract 的 `--type/--width`。
2. **图层命名语言**：中文/英文（`--naming-lang zh|en`，默认中文）。

## 前置检查（顺序执行，缺一不可）

1. **Sketch MCP 在线**：Sketch 2025.2.4+（官网版），⌘K → Start MCP Server，
   默认 `http://localhost:31126/mcp`。重启 Sketch 后需手动重开。
2. **运行时**：`python3` + `pip install playwright`（走系统 Chrome）+ Google Chrome。
3. **字体**：`bash scripts/setup_fonts.sh`（Stitch 标准三件套：Plus Jakarta Sans /
   JetBrains Mono / Material Symbols Outlined）；页面用了别的 Google Fonts 时按
   `"Family:400,700"` 追加安装。缺字体 → 文本回落错误字重、图标变英文单词。

## 输入结构

Stitch 每屏导出一个子目录（内含 `code.html`）：

```
导出目录/
├── _1/code.html
├── _2/code.html
└── 根级单页.html     # 散置在根目录的单页 HTML 也会作为一个屏参与转换
```

## 转换流程


```bash
# 整项目一条命令（自动提取 → 网格排布 → 分模块构建 → 保存）
python3 scripts/convert_all.py <导出目录> --save 输出.sketch [--cols 4]

# 单屏细控（三阶段）：
python3 scripts/extract_layout.py <屏>/code.html --type mobile --width 390 --out <屏>/sketch_build
python3 scripts/build_sketch.py <屏>/sketch_build/layout.json \
    --name 屏名 --naming-lang zh --export-dir <屏>/sketch_build --save 输出.sketch
```

多板合一同文档：后续屏 init 传 `--doc-id`（首屏返回的 docId）+ `--page-name <板名>`，
换新板首屏加 `--new-page`；`--save` 只在最后一屏传一次（doc.save 会改内存 Document id，
中途保存会让后续 --doc-id 失效）。

常用参数：`--max-module-els 60`（每块元素上限，超长页稳定性）、`--svg-mode vector|raster`、
`--keep-aura`（保留 blur 氛围光；默认省略，卡片取纯渐变/底色）。

## 验证闭环（必做）

finish 导出 `<屏名>.png` 与 `sketch_build/reference.png`（浏览器基准）逐像素比对
（平均差异 ≤10/100 为优，PIL+numpy 分条带定位热区）。检查清单：文本字形字重正确、
Material Symbols 是图标不是英文单词（连字=字体装对）、圆角渐变阴影一致、
fixed 底部导航贴画板底/顶部 header 贴顶。有差异查 `layout.json` 定位 → 修正 → 重跑该屏。

## 排问题先读（按需）

- `references/sketch-mcp-quirks.md` — run_code 沙箱 bug 清单（写 SketchAPI 前必读）
- `references/fidelity-rules.md` — 还原规则全集：渐变端点界内收敛（135° 对角=角对角）、
  透明渐变 stop 保 alpha、CJK 逐 token 折行、fixed z 序重分区、图片先下载再传入

## 已知限制

- 氛围光（blur-2xl/3xl）默认不落地（`--keep-aura` 可保留）
- transform 3D 展示区（透视手机样机等）像素级还原有限，随文档注明
- canvas/webGL 按位图处理
