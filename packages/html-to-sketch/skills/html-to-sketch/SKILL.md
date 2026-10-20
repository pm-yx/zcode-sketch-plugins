# Skill: html-to-sketch
# 任意 HTML → Sketch 设计文件（含交互态动态拆解）

把任意 HTML 页面（营销官网、管理后台、SPA、多子页面站点）变成 Sketch 原生设计稿：
真实矩形/圆角/渐变/阴影/文本/图片/矢量图层，图层按设计语义命名。

**与 stitch-to-sketch 的关系**：本插件是通用化版本——Stitch 导出是"单屏静态 HTML"，
真实项目的 HTML 往往**交互在页面里**（hash 路由、JS 视图切换、模态框、多子页面），
所以多一步 **动态拆解**：真实浏览器里爬出所有子页面/视图，逐个快照成静态屏，再走同一套
提取→构建→比对管线（extract/build 脚本与 stitch-to-sketch 同源）。

## 第 0 步：确认三件事

1. **入口文件**：哪个/哪些 HTML 是入口（如 `dist/admin.html`、`dist/portal.html`）？每个入口单独拆解，最终一个 .sketch 文档里每个入口一个 Page。
2. **视口宽度**：桌面后台/官网默认 **1440**；有移动端布局另说。内容高度自适应 = 画板高度。
3. **图层命名语言**：中文/英文（`--naming-lang zh|en`，默认中文）。

## 前置检查（同 stitch-to-sketch）

1. Sketch MCP 在线（`http://localhost:31126/mcp`，⌘K → Start MCP Server）。
2. `python3` + playwright（系统 Chrome）+ Google Chrome。
3. 页面用到的 Google Fonts 先装：`bash <PLUGIN_ROOT>/scripts/setup_fonts.sh`（缺什么装什么，参数 `"Family:400,700"`）。

## 转换流程

```bash
# 1) 拆解：浏览器动态爬交互态 → screens/（每屏 code.html + screen.png + manifest.json）
python3 <PLUGIN_ROOT>/scripts/discover_screens.py <入口>.html \
    --out <项目>/screens_portal --width 1440 --prefix portal-

#    --keep-detail-variants   同模板不同数据的详情页各自成屏（默认去重只留代表屏）
#    --max-screens N          上限保护（默认 24）

# 2) 提取：每屏浏览器精确几何 + 计算样式
python3 <PLUGIN_ROOT>/scripts/extract_layout.py <屏>/code.html \
    --type web --width 1440 --out <屏>/sketch_build

# 3) 构建：新文档按入口分 Page（--page-name / --doc-id / --new-page，多板合一用法同 stitch-to-sketch）
python3 <PLUGIN_ROOT>/scripts/build_sketch.py <屏>/sketch_build/layout.json \
    --name "<屏名>" --page-name "<入口名>" --naming-lang zh --export-dir <屏>/sketch_build
# 最后一屏的 finish 加 --save <输出>.sketch，且只保存这一次
```

## 拆解原理（discover_screens.py，排问题先读这段）

- **候选枚举**：`a[href^="#"]`、`[role=tab/menuitem]`、`[onclick]`、nav/aside/menu/tab 容器内元素，
  统一编号（枚举与点击回放共用同一份 JS，序号对齐）。
- **状态识别**：到达一个状态后取双重指纹——内容指纹（hash+可见元素数+正文文本，数字归零）精确去重；
  结构指纹（可见元素 tag.class 集合）做**同模板不同数据去重**（如 20 条新闻详情只留 1 张代表屏）。
- **状态回放**：每个状态记录"从首页出发的点击路径"，探索下一层时 reload+重放（本地页面快，可靠性优先）。
- **快照**：剥 `<script>`/`<noscript>` 冻结 JS 渲染结果；img/link/style url() 全部绝对化（file://），
  快照文件放哪都能渲染；full_page 截图作基准。
- **已知限制**：模态框/浮层不作为独立屏（去重后指纹相同会被跳过）；带副作用按钮（删除/退出）
  与普通按钮同等对待，demo 站无碍，真实后端页面慎爬；canvas/webGL 内容按位图处理。

## 验证闭环（同 stitch-to-sketch）

finish 导出的 `<屏>/sketch_build/<屏名>.png` 与 `<屏>/screen.png` 并排比对；
文本字形、图标连字、圆角渐变阴影、fixed 归位逐项核对；工具链可用 `tools/pixel_gate.py` 思路
（PIL+numpy 逐像素差异 + 分条带热区）。有差异 → 查 layout.json 定位 → 修 → 重跑该屏。

## 交付

- 一个 `.sketch`：每个入口一个 Page，每屏一个 Frame（网格排布）
- 图层结构：背景 → 卡片 → 元素 语义分组（`卡片 · xxx` / `文本 · xxx` / `图标 · xxx` / `图像 · xxx`）
- 报告：入口数、每入口屏数、图层数、字体清单、比对结果、已知近似项

## 深入阅读

- `references/sketch-mcp-quirks.md` — run_code 沙箱 bug 与规避（写 SketchAPI 脚本前必读）
- `references/fidelity-rules.md` — fixed 归位、圆角、渐变映射、SVG 矢量化等还原规则
- `rules.md` — 本插件反馈归纳与迭代记录（用户反馈的问题都归档在这里）
