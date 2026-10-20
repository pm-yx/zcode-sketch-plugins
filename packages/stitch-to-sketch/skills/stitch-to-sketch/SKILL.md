---
name: stitch-to-sketch
description: 将 Stitch (stitch.withgoogle.com) 导出的 HTML 100% 还原为 Sketch 原生设计文件。浏览器引擎精确取几何与计算样式，经 Sketch MCP run_code 模块化构建原生图层：矢量图表（钢笔路径）、真实字体/字重、Material Symbols 图标、图片下载后 1:1 传入、fixed 元素归位画板底部。开始前必须先询问项目类型（移动端/网页）。
---

# Stitch HTML → Sketch 设计文件 100% 还原

把 Stitch 导出的 `code.html` 变成 Sketch 里的原生设计稿（非截图贴图）：
真实矩形/圆角/渐变/阴影/文本图层/图标字体/图片图层/矢量曲线，图层按设计语义分层命名。

**核心原理**：不用肉眼猜 Tailwind 类——用真实浏览器渲染 HTML，逐元素读取
`getBoundingClientRect()` + `getComputedStyle()` 拿到绝对几何与最终样式，
再驱动 Sketch MCP 的 `run_code` 原生建层，最后导出 PNG 与浏览器截图比对闭环。

## 第 0 步：先问项目类型（必做）

开始任何转换前，**必须询问用户**：

1. **项目类型**：移动端 还是 网页？
1b. **图层命名语言**：中文 还是 英文（`--naming-lang zh|en`，默认中文）？（可读 HTML `<meta name="shell-type">` 自动预判并给出建议，但要让用户确认）
2. 移动端默认视口宽 **390**（iPhone 主流逻辑宽度，内容高度自适应 = 画板高度）；网页默认 **1440**，按原始比例。网页端注意：新字体（如 Noto Serif/Hanken Grotesk）要先用 setup_fonts.sh 安装。
3. 输出位置：`.sketch` 文件保存路径（默认 Stitch 导出目录旁）。

移动端和网页的区别只影响 `extract_layout.py --type` 与宽度参数。

## 前置检查（顺序执行，缺一不可）

1. **Sketch MCP 已启动**：Sketch 2025.2.4+（官网版，非 App Store 版），
   ⌘K 输入 MCP → Start MCP Server，默认 `http://localhost:31126/mcp`。
   测试：`curl -s -X POST http://localhost:31126/mcp -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0.0.1"}}}'`
   通不了就让用户在 Sketch 里开 MCP Server，并检查 系统设置→隐私与安全→本地网络。
2. **运行时**：`python3`（含 playwright：`pip install playwright`，无需下载浏览器内核，走系统 Chrome）+ Google Chrome。
3. **字体安装**（缺字体会导致文本回落错误字重/字形）：
   `bash <PLUGIN_ROOT>/scripts/setup_fonts.sh`
   装 Stitch 标准三件套（Plus Jakarta Sans / JetBrains Mono / Material Symbols Outlined，可变字体单 TTF 全字重）到 `~/Library/Fonts/stitch/`。
   页面用了别的 Google Fonts 时按 `"Family:400,700"` 追加参数安装。
4. **扫描 Stitch 导出目录**：每屏一个子目录，内含 `code.html`（+ `screen.png` 交叉参考）。

## 转换流程（每屏执行）

```bash
# 1) 提取：浏览器精确几何 + 计算样式 → layout.json + reference.png（还原度基准）
python3 <PLUGIN_ROOT>/scripts/extract_layout.py <screen>/code.html \
    --type mobile --width 390 --out <screen>/sketch_build

# 2) 构建：init（建文档+Frame）→ 按模块分块增量建层 → finish（导出+保存）
python3 <PLUGIN_ROOT>/scripts/build_sketch.py <screen>/sketch_build/layout.json \
    --name "屏幕名" --naming-lang zh --export-dir <screen>/sketch_build --save <输出>.sketch
```

长页面稳定性：`build_sketch.py` 自动按顶层子树拆模块（默认 `--max-module-els 60`，
可调），每模块一次 `run_code`，跨模块父级经 layer id 挂载——超长页也不会因脚本过大失败。
SVG 图表默认 **矢量模式**（`--svg-mode vector`，`ShapePath.fromSVGPath` 钢笔路径），
失败自动回退浏览器烘焙 PNG（`--svg-mode raster` 强制光栅）。

多板合一（如移动端+网页端进同一个 .sketch）：后续屏的 init 传 `--doc-id <首次返回的docId>`
复用文档、`--page-name <板名>` 指定 Page；换新板首屏加 `--new-page`（init 按页面名找页优先，
找不到才新建——`page.select()` 在 run_code 沙箱里不影响后续调用的 selectedPage，别依赖）。
`--save` 只在最后一屏的 finish 传一次。整项目批量参考 `scripts/convert_all.py`（单页网格）。

## 验证闭环（必做）

1. 构建 finish 后得到 `<screen>/sketch_build/<屏幕名>.png`（Sketch 导出）。
2. 与 `sketch_build/reference.png`（浏览器基准）**并排视觉比对**（上传两图做图像分析，或肉眼检查）。
3. 检查清单：
   - 文本字形/字重正确（非系统回退字体、中文不豆腐）
   - Material Symbols 显示为图标而非英文单词（连字生效=字体装对）
   - 卡片圆角、渐变、阴影与基准一致
   - 图表曲线平滑且渐变填充正确（卡片为纯渐变填充；blur 氛围光默认省略，--keep-aura 可保留）
   - **fixed 元素归位**：底部导航贴画板底部、顶部 header 贴顶部（见 references/fidelity-rules.md）
4. 有差异 → 定位该元素（`layout.json` 里有每个元素的坐标/样式）→ 修正后重跑该屏。

## 交付

- 一个 `.sketch` 文件：每屏一个 Page（Frame 名 = 屏幕名）
- 图层结构：背景 → 卡片 → 元素 语义分组（`卡片 · xxx` / `文本 · xxx` / `图标 · xxx` / `图像 · xxx` / `氛围光 · xxx` / `矢量 · path`）
- 向用户报告：屏数、每屏图层数、字体清单、验证比对结果、已知近似项（见 fidelity-rules.md 的"近似与豁免"）

## 深入阅读

- `references/sketch-mcp-quirks.md` — **run_code 沙箱实测 bug 清单与规避（必读，写任何 SketchAPI 脚本前）**
- `references/fidelity-rules.md` — 还原度规则：fixed 归位、圆角、渐变映射、SVG 矢量化、图片下载传入、JS 随机内容快照语义
