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

## 前置检查

1. Sketch MCP 在线（`http://localhost:31126/mcp`，⌘K → Start MCP Server）。
   **MCP 断连**：重启 Sketch 后服务器不会自启，需用户 ⌘K 手动 Start MCP Server
   （UI 自动化无辅助权限不可行）。
2. `python3` + playwright（系统 Chrome）+ Google Chrome。
3. 页面用到的 Google Fonts 先装：`bash <PLUGIN_ROOT>/scripts/setup_fonts.sh`（缺什么装什么，参数 `"Family:400,700"`）。
   缺字体 Sketch 静默回落，文字密集区比对差异会显著变大——先装再建。字体四个坑：
   - **家族名必须与页面 CSS 同名**：字体文件内部 family 常与 CSS 名不一致（如 Neue Haas 内部叫
     "Text Pro"、Noto CJK 官方 OTF 每档字重是独立家族名）——用 fontTools 改 name 表（1/16/2/17/4）
     统一；CoreText 按 PostScript 名缓存，改家族名要**换新 PS 名+新文件名**重注册才会生效。
   - **Sketch 文字层是单字体、无浏览器式逐字回落**：拉丁字体遇中文文本会被持久化回落苹方。
     build 的 `mapFont(ff, txt)` 已做内容感知路由（CJK 文本 → 栈内 CJK 家族），新项目请按需扩充映射。
   - **Sketch 启动后字体索引异步刷新**：装完字体/重启后立即建层仍可能回落，等 1-2 分钟再验证。
   - **fontWeight 刻度**：Sketch 的 `style.fontWeight` 是 AppKit 档位（5=Regular、6=Medium、
     7=Semibold、8=Bold），CSS 字重要 +1 档映射（400→5/500→6/600→7/700→8）；直接除以 100
     会整体偏轻一档（700 落 Semibold、被单面家族吸附成 Medium），粗体全变常规。
4. **SVG 精灵 `<use>` 引用**：extract 已内置 `resolveUses` 预处理（walk 前把 symbol 内部形状
   克隆回 svg、补 viewBox/描边属性）——内嵌 sprite 图标（Lucide/Iconfont symbol 方式）此前会
   提取成空：collectSvg 收不到 path + 序列化烘焙空图（两道工序都空）。排查图标缺失时先查
   layout.json 对应 svg 的 `svgdata.paths` 是否为空数组。

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

**写文档前必做完整性核对**：`doc.save` 前先列出 `doc.pages.map(p=>p.name+'('+p.layers.length+')')`
与分页计划比对——Sketch 会话可能被用户回退/重开（页面悄悄丢失），在回退态上保存会**覆盖掉好版本**。
另：`doc.save` 会改变内存 Document id，续建前重新探测 docId。

## 交付

- 一个 `.sketch`：每个入口一个 Page，每屏一个 Frame（网格排布）
- 图层结构：背景 → 卡片 → 元素 语义分组（`卡片 · xxx` / `文本 · xxx` / `图标 · xxx` / `图像 · xxx`）
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
- 报告：入口数、每入口屏数、图层数、字体清单、比对结果、已知近似项

## 重建与排障

- discover 的 entry 是纯文件路径，带 query（如 admin.html?demo=1）会被 URL 编码——用
  `location.replace` 跳转壳页；壳文件名会成为分页名前缀，事后 MCP 改名
- 清理 build_state 用 `screens-*/*/sketch_build/`，勿只写 `0*/`——10+ 号屏目录漏清会被
  skip 丢板；文档残留页会接住 index 组（INIT 找不到目标页且非 newPage 时落到
  selectedPage，页名不匹配正则不改名）——重建前先清空文档只留一个空页；
  **对已有画板的文档重跑单屏会追加重复画板**（INIT 每次新建 Frame），重跑前先删目标屏旧画板
- 超长页（>16000px）建议分段；32 屏以上遇 MCP 劣化时重启 Sketch 断点续跑

## 深入阅读

- `references/sketch-mcp-quirks.md` — run_code 沙箱 bug 与规避（写 SketchAPI 脚本前必读）
- `references/fidelity-rules.md` — fixed 归位、圆角、渐变映射、SVG 矢量化等还原规则
- `rules.md` — 本插件反馈归纳与迭代记录（用户反馈的问题都归档在这里）
