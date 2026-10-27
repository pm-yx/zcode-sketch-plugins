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
   默认 `http://localhost:31126/mcp`。**MCP 断连**：重启 Sketch 后服务器不会自启，
   需用户 ⌘K 手动 Start MCP Server（UI 自动化无辅助权限不可行）。
2. **运行时**：`python3` + `pip install playwright`（走系统 Chrome）+ Google Chrome。
3. **字体**：`bash scripts/setup_fonts.sh`（Stitch 标准三件套：Plus Jakarta Sans /
   JetBrains Mono / Material Symbols Outlined）；页面用了别的 Google Fonts 时按
   `"Family:400,700"` 追加安装。缺字体 → 文本回落错误字重、图标变英文单词。
   中文页面把 **Noto Sans SC** 加进安装清单——Sketch 文字层单字体、无浏览器式逐字回落，
   拉丁字体配中文文本会被持久回落苹方（build 的 `mapFont(ff, txt)` 已按文本内容路由到
   Noto Sans SC，新字体栈按需扩充映射）。另三个坑：
   - **家族名必须与页面 CSS 同名**：字体文件内部 family 常与 CSS 名不一致——用 fontTools
     改 name 表（1/16/2/17/4）统一；CoreText 按 PostScript 名缓存，改家族名要
     **换新 PS 名+新文件名**重注册才会生效
   - **Sketch 启动后字体索引异步刷新**：装完字体/重启后立即建层仍可能回落，等 1-2 分钟再验证
   - **fontWeight 刻度**：Sketch 的 `style.fontWeight` 是 AppKit 档位（5=Regular、6=Medium、
     7=Semibold、8=Bold），CSS 字重要 +1 档映射（400→5/500→6/600→7/700→8）；直接除以 100
     会整体偏轻一档（700 落 Semibold、被单面家族吸附成 Medium），粗体全变常规
4. **SVG 精灵 `<use>` 引用**：extract 已内置 `resolveUses` 预处理（walk 前把 symbol 内部形状
   克隆回 svg、补 viewBox/描边属性）——内嵌 sprite 图标（Lucide/Iconfont symbol 方式）此前会
   提取成空：collectSvg 收不到 path + 序列化烘焙空图（两道工序都空）。排查图标缺失时先查
   layout.json 对应 svg 的 `svgdata.paths` 是否为空数组。

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

**写文档前必做完整性核对**：`doc.save` 前先列出 `doc.pages.map(p=>p.name+'('+p.layers.length+')')`
与分页计划比对——Sketch 会话可能被用户回退/重开（页面悄悄丢失），在回退态上保存会**覆盖掉好版本**。
另：`doc.save` 会改变内存 Document id，续建前重新探测 docId。

## 排问题先读（按需）

- `references/sketch-mcp-quirks.md` — run_code 沙箱 bug 清单（写 SketchAPI 前必读）
- `references/fidelity-rules.md` — 还原规则全集：渐变端点界内收敛（135° 对角=角对角）、
  透明渐变 stop 保 alpha、CJK 逐 token 折行、fixed z 序重分区、图片先下载再传入

## 图层还原语义

- 文字行高：固定行高仅用于定位，建层后自动转 **auto** 并按半行距补偿 y——层框贴字形、
  视觉位置与浏览器一致（避免"文字顶部有 line-height 间距"的观感问题），多行段落允许轻微累积偏差
- 文字居中（带背景元素）：提取时检测"单行文本位于更高宿主盒且行盒中心≈宿主中心"→ 记录宿主盒
  （t.hx/hy/hw/hh + vc/hc 标记），build 把贴合内容的文字层框**居中放置**进宿主盒（双向）。
  **坑：Sketch 文字层 frame 会被 auto-fit 收缩，固定框的 textBehaviour（wrapper 字符串与
  sketchObject=1）实测都不生效——不要试图给 Text 撑大框，用"紧框 + 居中坐标"**
- 装饰性伪元素（content 为空的色块/圆点/下划线，如状态点、编号下划线）：提取为宿主元素的
  同级形状层（绝对定位按 computed 偏移、流内块贴内容盒底、行内项贴起端/末端垂直居中），
  支持背景/渐变（仅 linear）/圆角。**两条铁律**：①采集必须放在「元素自身成层」守卫**之外**——
  宿主自身无视觉不成层，但其 ::after 装饰仍要采集；②`mask-image` 型伪元素直接跳过——
  转纯色形状会变成实心方块

## 已知限制

- 清理 build_state 用 `<导出目录>/*/sketch_build/`，勿只清部分屏目录——漏清的屏会被
  skip 丢板；文档残留页会接住后续屏组、**对已有画板的文档重跑单屏会追加重复画板**
  （INIT 每次新建 Frame）——重建前先清空文档只留一个空页，重跑前先删目标屏旧画板
- 超长页（>16000px）建议分段；32 屏以上遇 MCP 劣化时重启 Sketch 断点续跑
- 氛围光（blur-2xl/3xl）默认不落地（`--keep-aura` 可保留）
- transform 3D 展示区（透视手机样机等）像素级还原有限，随文档注明
- canvas/webGL 按位图处理
