# 还原度规则（fidelity rules）

100% 还原的判定基准是**自己的浏览器全页截图**（`reference.png`），不是 Stitch 附带的
`screen.png`（其尺寸被平台缩放过、不一致，只作交叉参考）。

## fixed 定位元素归位（重要）

HTML 是可滚动的：`position: fixed` 元素在全页截图里停在**滚动 0 位置**（如底部导航
会浮在页面中部），但设计稿语义里它们应该贴住画板边缘。

- 提取器记录 `fixed: true` + `vpTop` / `vpBottom`（元素到视口顶/底的距离）+ `browserVH`。
- 构建器重定位（`build_sketch.py prepare()`）：
  - 底部锚定（`vpBottom <= vpTop`，如底部 Tab 栏）→ 整棵子树平移到 `画板高 - vpBottom - 高`
  - 顶部锚定（header 等）→ 保持画板顶部
- 需求来源：移动端底部按钮在浏览器里"固定在下面"，设计稿中必须位于画板底部。

## 圆角

- `border-radius` 按四角（tl/tr/br/bl）提取，百分比按短边换算并封顶 `min(w,h)/2`。
- `rounded-full` 的圆/胶囊 → 封顶后天然成立；椭圆用 `ShapePath.ShapeType.Oval`。
- 图片图层带 `img` 圆角时同样应用 `corners.radii`。

## 渐变映射（CSS → Sketch）

- CSS 角度（0deg=向上）→ 方向向量 `(sin a, -cos a)`；Sketch `from/to` 为图层内
  0..1 归一化坐标，线长按 `|w·dx|+|h·dy|` 投影近似（卡片渐变误差可忽略）。
- SVG 渐变：解析 `<linearGradient>` 的 stops（`stop-color`/`stop-opacity` 常在 CSS 类或
  内联 style 里，**必须用 getComputedStyle 解析**，属性读不到）+ x1/y1/x2/y2 转角度。
- 渐变描边（发光曲线）无法直接给 border 上渐变 → 取中间 stop 实色近似（面积渐变填充不受影响）。

## SVG / 图表：矢量优先

- 图表是 JS 运行时注入的 `<svg>`；**SVG 元素 tagName 是小写 `svg`**，别用大写判断。
- 矢量模式：逐 `<path>/<line>/<circle>/<rect>/<polyline>` 转 `d` 字符串 →
  `ShapePath.fromSVGPath()`（等价钢笔工具），用 `getBBox()` 把路径坐标从 viewBox 空间
  精确映射到页面坐标（scale = 元素渲染尺寸 / viewBox）。
- 光栅兜底：提取时同时烘焙 PNG（CORS 干净时），矢量失败自动回退。

## 图片移植（先下载，再传入）

- `<img>`：浏览器内按 `object-fit`（cover/contain 数学）烘焙成目标尺寸 PNG；同时保留
  原始 URL。构建时：烘焙数据落盘 → `image: {path}` 建图层；无烘焙数据但有远程 URL →
  直接下载落盘再传入。**位置与比例 1:1**。
- `background-image: url()` 同路径处理。
- 内联 SVG：矢量优先（见上），烘焙 PNG 兜底。

## 文本

- 逐行拆分（word-walking Range 切行），每行一个 Text 图层，坐标 = 行盒绝对位置。
- `text-transform` 已在提取时应用；`letter-spacing`（px）与 `line-height`（px）显式设置。
- 字重映射：CSS 100–900 → Sketch `fontWeight` 1–9（≈ w/100）。
- Material Symbols：文本 = icon 名称（ligature），字体装好后渲染为图标本体。

## 近似与豁免（向用户说明的已知项）

- `blur-2xl/3xl` 氛围光晕：用椭圆 + 径向渐变（色→透明）近似 backdrop 大模糊。
- `backdrop-blur` 毛玻璃：仅半透明填充，无实时背景模糊（设计稿中背景为静态，视觉等价）。
- `overflow-hidden` 裁剪：超出容器的子元素按裁剪盒剔除（完全在外的删，跨界的保留可见部分近似）。
- 渐变描边、混合模式：实色/分层近似。
- **JS 随机内容**：部分 Stitch 页面脚本会随机化数字（如历史收益），提取是瞬时快照，
  Sketch 内容与快照一致、与后续再渲染可能差几个数字——属正常。

## 模块拆解（长页稳定性）

- 默认按顶层子树拆模块（≤60 元素/块），超大子树再按其子级细分；根元素（body 背景）
  单独成块先行。跨块父级用 layer id（`sketchObject.objectID()`，见 quirks.md Bug 2）挂载。
- 每块一次 `run_code`，任何一块失败只需重跑该屏，不影响其他屏。

## 图层命名（设计分层理论）

背景（色块/氛围光）→ 卡片（带底色/圆角/阴影的容器）→ 元素（文本/图标/图像/矢量），
名称形如 `卡片 · rounded-xl bg-surface-container`、`文本 · 净资产`、`图标 · visibility`，
保留源 class 片段便于回溯。

## 传输毒字符与索引重映射（2026-10 整项目实测）

- **ASCII 双引号/反斜杠是传输毒药**：文本或样式字段里的 `"`（如 `MacBook Air M2 13"`）
  以任何 JSON 转义形式（`\"`、`\\\"`）进入 run_code 脚本都会被沙箱包装器截断
  （报 `Unexpected end of script`）。`prepare()` 统一清洗：`"`→`”`、`\`→`＼`。
  `background-image: url("...")` 的 css 兜底字段同理——非 linear 渐变直接丢弃，
  并让提取器把 url() 背景独立捕获为 bgimg（否则照片背景会整个漏掉）。
- **过滤数组必须重映射父引用**：任何"从 els 数组删除元素"的操作（提取器剔除
  完全被裁剪元素、构建器剔除幽灵容器）都会让后续下标错位，`p` 变成前向引用/
  环，症状是巨页模块数暴涨（1300 元素拆出 300+ 块）或 `parent ids missing`。
  两端都已加 old→new 索引重映射；新改动若涉及删除元素，必须照做。
- **幽灵节点压缩**：不构成 Group 的纯布局容器（无视觉样式、仅有子级）在
  `prepare()` 里做父链压缩，子元素直接指向最近的会成组祖先；跨模块引用一律
  只指向 Group（有 layer id），不存在 null 容器引用。
- **模块打包**：兄弟子树贪心合并到 ≤60 元素/块，超大子树递归细分；
  巨页（某 1301 元素巨页）从 305 块收敛到 26 块。

## 氛围光（blur 光晕）策略（按用户设计语义定稿）

`blur-2xl/3xl` 氛围光默认**不落地**：设计稿里卡片就是干净的渐变/底色填充，
浏览器里那种大半径高斯光晕属于运行时特效，画成椭圆径向渐变反而显脏、还会
在图层树里多出装饰层。`build_sketch.py --keep-aura` 可保留（自动收敛在
卡片裁剪盒内），仅严格像素对比时使用。

## 网页端（web_standard）兼容要点（v0.2.0 实测）

- **fixed 元素 z 序**：浏览器里 fixed header 带 z-50 浮在内容上；构建按 DOM 序平铺会被
  后画的内容区底色盖住（移动端因底色相同看不出来，网页端配色不同即暴露）。
  `prepare()` 把 fixed/sticky 子树稳定分区到元素列表末尾（最后创建=Sketch 最上层），
  分区后必须再做一次索引重映射。
- **坐标原点**：els 坐标是 Frame 内内容坐标，直接挂 Frame 时 `origin['-1'] = {0,0}`，
  绝不能减 Frame 的画布位置（网格第 2 行起全部子层变负坐标、导出空白）。
- **fixed 锚定判定**：先读 `vpTop` 再 pop——pop 后再 get 永远 None，条件退化为
  `vp_bottom <= vp_bottom` 恒真，顶锚定 header 会被误判成底锚定。
- **input/textarea placeholder**：无文本节点，遍历器按属性合成一条占位文本
  （颜色取 computed color @55% alpha）。
- **截图与遍历同态**：reference 截图改在 walker evaluate 之后（+300ms 定态），
  避免组件延时状态导致基准与数据不一致。
- **已知限制**：transform 缩放复刻的"手机样机"展示区、mix-blend-mode 等浏览器
  特效区域逐层还原有限（如 某巨页下 1/3），建议人工补片或接受近似。

## 中文折行与图层命名（v0.3.0 实测）

- **CJK 折行**：切行算法必须"逐 token 单独建 Range 测 top"——range 锚定节点起点时
  bbox.top 永远是第一行，切行判定永不触发（英文其实也从未切对，短标签看不出来）。
  token 化：拉丁词整词、空白保留、CJK/全角逐字。
- **设计语义命名**：`prepare()` 产出 `dname`（角色 + 内容摘要）。角色用官方设计语言
  （顶部导航/页脚/卡片/按钮/输入框/列表项/标题/背景色块/图表…，`--naming-lang en` 切英文），
  摘要取自身或子树内 ≤24 字的文本（大容器 body/main 不取，避免风马牛不相及）。
  任何"过滤/重排元素列表"的操作后，`by_i`/`children` 索引结构必须重建，否则 BFS 命名会
  走进陈旧环路挂死。

## 渐变端点边界收敛（v0.3.0 补充）

CSS 渐变线按"过中心角投影"计算时端点会落在形状边界之外（如 135° 卡片 from(0.1,-0.17)），
Sketch 渲染越界手柄会扭曲渐变轴（方向看起来不对）。主流设计工具的形态是端点落在形状上：
`t = min(0.5/|dx|, 0.5/|dy|)`，from/to = center ∓ d·t —— 方向严格不变、端点必在边界内，
对角渐变自动得到 0,0→1,1 角对角（Sketch/Figma 的标准形态）。
