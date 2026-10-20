---
name: pmyx-html-to-sketch
description: 把任意 HTML 转成 Sketch 原生设计稿（100% 像素还原，非截图贴图）。真实浏览器动态拆解交互子页面（hash 路由/SPA 视图切换/登录墙/弹窗态），像素级几何提取，SVG 图标保矢量，文本真折行，设计语义图层命名，导出与浏览器基准逐像素比对验证。Use whenever the user wants to turn any HTML file, website directory, admin dashboard, or web page into an editable Sketch .sketch design file —— 哪怕只是说"转成 sketch / 还原成设计稿 / 做成设计文件"。
---

# html-to-sketch · 任意 HTML → Sketch 原生设计稿

把任意 HTML（营销官网、管理后台、SPA、多子页面站点）变成 Sketch 原生设计稿：
真实矩形/圆角/渐变/阴影/文本/图片/SVG 矢量路径，图层按设计语义命名。
独立 skill，脚本全部内置于 `scripts/`，不依赖插件市场。

## 触发方式

技能的斜杠调用由 ZCode 按安装目录名自动提供（`/pmyx-html-to-sketch`），自动触发靠
frontmatter description 语义匹配，无需在本文内实现。典型触发指令：

- `把 dist/portal.html 转成 sketch`（任意 HTML/网站/目录 → 设计稿）
- `/pmyx-html-to-sketch 把 <目录> 里的网页还原成 Sketch，网页端 1440 宽`
- `/pmyx-html-to-sketch <入口>.html 拆解所有子页面生成 .sketch，图层中文命名`
- `这个官网做一份 Sketch 设计稿`

## 第 0 步：先问用户三件事

开始前确认（不问清楚会返工）：

1. **入口文件**：哪个/哪些 HTML 是入口？每个入口单独拆解，一个 .sketch 文档里每入口一组 Page。
2. **视口宽度**：桌面默认 **1440**；移动端布局用 **390**。画板高度 = 内容自适应高度。
3. **图层命名语言**：中文/英文（`--naming-lang zh|en`，默认中文）。

## 前置检查（顺序执行，缺一不可）

1. **Sketch MCP 在线**：Sketch 2025.2.4+（官网版），⌘K → Start MCP Server，默认
   `http://localhost:31126/mcp`。重启 Sketch 后需手动重开；工具调用断连 = 长会话劣化，
   重启 Sketch 即恢复（见 references/sketch-mcp-quirks.md）。
2. **运行时**：`python3` + `pip install playwright`（走系统 Chrome）+ Google Chrome。
3. **字体**：按页面实际用字安装，`bash scripts/setup_fonts.sh "Noto Sans SC:400,500,700"`。
   缺字体 Sketch 静默回落，文字密集区比对差异会显著变大——先装再建。

## 转换流程

脚本路径相对本技能根目录书写，可直接执行；项目数据放独立目录（如 `<工作区>/projects/<项目名>/`）。

```bash
# 1) 拆解：真实浏览器爬交互态 → 每屏静态快照 + 基准截图 + manifest.json
python3 scripts/discover_screens.py <入口>.html --out <项目>/screens --width 1440

# 2) 一键构建：逐屏提取 + 自动分页（每页 ≤6 画板，Page 命名 {入口名}-{NN}）+ 保存
python3 scripts/convert_project.py <项目>/screens/manifest.json --save <输出>.sketch
```

常用参数：`--max-screens 24`（上限保护）、`--keep-detail-variants`（同模板详情页各自成屏）、
`--cols 4`（网格列数）、`--per-page 6`、`--naming-lang en`、`--svg-mode raster`（强制图表位图）。
中断续跑安全：重跑 convert_project 自动跳过已完成屏（状态在磁盘）。

## 验证闭环（必做，不许跳过）

每屏 finish 导出 `<屏>/sketch_build/<屏名>.png`，与同目录 `reference.png`（浏览器基准）
逐像素比对：平均差异 ≤10/100 为优。用 PIL+numpy 分条带定位热区，裁剪放大两图对照，
查 `layout.json`（每元素坐标/样式都在）定位修正后重跑该屏。

## 排问题先读（按需）

- `references/sketch-mcp-quirks.md` — 写任何 SketchAPI 脚本前必读：run_code 沙箱 bug
  （引号毒字符/[fn()]/layer.id）、doc.save 改内存 id、Page.select 失效、增量保存断链
- `references/fidelity-rules.md` — 还原规则：fixed 归位与 z 序、渐变端点收敛、SVG 全矢量、
  懒加载滚动、显现动画强制显直、分片基准截图、同款卡片色差吸附

## 交付

- 一个 `.sketch`：每入口一组 Page（`{入口名}-{NN}`，每页 ≤6 画板），每屏一个 Frame 网格排布
- 图层：背景 → 卡片文件夹（结构容器成组）→ 元素，语义命名
- 向用户报告：入口数/屏数（含去重）、图层数、字体清单、逐屏比对分数、已知近似项

## 已知限制

- 模态框/浮层不作为独立屏（按可见内容指纹去重）
- 连真实后端的页面慎爬（发现器有危险文案黑名单兜底，但提交类按钮有副作用）
- 超长页（>16000px）建议分段；32 屏以上遇 MCP 劣化时重启 Sketch 断点续跑
