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
   - **家族名必须与页面 CSS 同名**：字体文件内部 family 常与 CSS 名不一致（如 Neue Haas 内部叫
     "Text Pro"、Noto CJK 官方 OTF 每档字重是独立家族名）——用 fontTools 改 name 表（1/16/2/17/4）
     统一；CoreText 按 PostScript 名缓存，改家族名要**换新 PS 名+新文件名**重注册才会生效。
   - **Sketch 文字层是单字体、无浏览器式逐字回落**：拉丁字体遇中文文本会被持久化回落苹方。
     build 的 `mapFont(ff, txt)` 已做内容感知路由（CJK 文本 → 栈内 CJK 家族），新项目请按需扩充映射。
   - **Sketch 启动后字体索引异步刷新**：装完字体/重启后立即建层仍可能回落，等 1-2 分钟再验证。
   - **SVG 精灵 `<use>` 引用**：extract 已内置 `resolveUses` 预处理（walk 前把 symbol 内部形状
     克隆回 svg、补 viewBox/描边属性）——内嵌 sprite 图标（Lucide/Iconfont symbol 方式）此前会
     提取成空：collectSvg 收不到 path + 序列化烘焙空图（两道工序都空）。排查图标缺失时先查
     layout.json 对应 svg 的 `svgdata.paths` 是否为空数组。
   - **MCP 断连**：重启 Sketch 后服务器不会自启，需用户 ⌘K 手动 Start MCP Server（UI 自动化无辅助权限不可行）。
   - **fontWeight 刻度**：Sketch 的 `style.fontWeight` 是 AppKit 档位（5=Regular、6=Medium、
     7=Semibold、8=Bold），CSS 字重要 +1 档映射（400→5/500→6/600→7/700→8）；直接除以 100
     会整体偏轻一档（700 落 Semibold、被单面家族吸附成 Medium），粗体全变常规。

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

**写文档前必做完整性核对**：`doc.save` 前先列出 `doc.pages.map(p=>p.name+'('+p.layers.length+')')`
与分页计划比对——Sketch 会话可能被用户回退/重开（页面悄悄丢失），在回退态上保存会**覆盖掉好版本**。
另：`doc.save` 会改变内存 Document id，续建前重新探测 docId。

## 排问题先读（按需）

- `references/sketch-mcp-quirks.md` — 写任何 SketchAPI 脚本前必读：run_code 沙箱 bug
  （引号毒字符/[fn()]/layer.id）、doc.save 改内存 id、Page.select 失效、增量保存断链
- `references/fidelity-rules.md` — 还原规则：fixed 归位与 z 序、渐变端点收敛、SVG 全矢量、
  懒加载滚动、显现动画强制显直、分片基准截图、同款卡片色差吸附

## 交付

- 一个 `.sketch`：每入口一组 Page（`{入口名}-{NN}`，每页 ≤6 画板），每屏一个 Frame 网格排布
- 图层：背景 → 卡片文件夹（结构容器成组）→ 元素，语义命名
- 文字行高：固定行高仅用于定位，建层后自动转 **auto** 并按半行距补偿 y——层框贴字形、
  视觉位置与浏览器一致（避免"文字顶部有 line-height 间距"的观感问题），多行段落允许轻微累积偏差
- 文字居中（带背景元素）：提取时检测"单行文本位于更高宿主盒且行盒中心≈宿主中心"→ 记录宿主盒
  （t.hx/hy/hw/hh + vc/hc 标记），build 把贴合内容的文字层框**居中放置**进宿主盒（双向）——
  设计稿里文字框在背景内居中。**坑：Sketch 文字层 frame 会被 auto-fit 收缩，固定框的
  textBehaviour（wrapper 字符串与 sketchObject=1）实测都不生效——不要试图给 Text 撑大框，
  用"紧框 + 居中坐标"**
- 装饰性伪元素（content 为空的色块/圆点/下划线，如 `.pill::before` 状态点、编号下划线）：
  提取为宿主元素的同级形状层（绝对定位按 computed 偏移、流内块贴内容盒底、行内项贴起端/末端
  垂直居中），支持背景/渐变/圆角。**两条铁律**：①采集必须放在「元素自身成层」守卫**之外**——
  文本藏在子元素的宿主（如 `<span class=seal"><span>01</span></span>`）自身无视觉不成层，
  但其 ::after 装饰仍要采集；②`mask-image` 型伪元素（.more 箭头等 currentColor+mask 字形）
  直接跳过——转纯色形状会变成实心方块
- 向用户报告：入口数/屏数（含去重）、图层数、字体清单、逐屏比对分数、已知近似项

## 已知限制

- 模态框/浮层不作为独立屏（按可见内容指纹去重）
- 连真实后端的页面慎爬（发现器有危险文案黑名单兜底，但提交类按钮有副作用）
- discover 的 entry 是纯文件路径，带 query（如 admin.html?demo=1）会被 URL 编码——用
  `location.replace` 跳转壳页；壳文件名会成为分页名前缀，事后 MCP 改名
- 清理 build_state 用 `screens-*/*/sketch_build/`，勿只写 `0*/`——10+ 号屏目录漏清会被
  skip 丢板；文档残留页会接住 index 组（INIT 找不到目标页且非 newPage 时落到
  selectedPage，页名不匹配正则不改名）——重建前先清空文档只留一个空页；**对已有画板的文档重跑单屏会追加重复画板**（INIT 每次新建 Frame），
  重跑前先删目标屏旧画板
- 超长页（>16000px）建议分段；32 屏以上遇 MCP 劣化时重启 Sketch 断点续跑
