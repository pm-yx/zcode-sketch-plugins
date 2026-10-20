# html-to-sketch

把**任意 HTML**（营销官网、管理后台、SPA、多子页面站点）转换成 Sketch 原生设计文件——
交互态在浏览器里动态发现与拆解，不依赖静态解析。
ZCode 插件，[返回总览](../../README.md)。

## 两步用法

```bash
# 1) 动态拆解：加载页面 → 枚举可点击候选 → 逐个点击并指纹比对 → 快照新视图
python3 scripts/discover_screens.py dist/portal.html \
    --out screens_portal --width 1440 [--max-screens 24] [--prefix portal-] [--keep-detail-variants]

# 2) 批量构建：逐屏提取 + 自动分页构建 + 保存（断点续跑，重复执行安全）
python3 scripts/convert_project.py screens_portal/manifest.json \
    --save 输出.sketch [--cols 4] [--per-page 6]
```

`discover_screens.py` 产出：

```
screens_portal/
├── manifest.json            # 屏清单（名称/hash/触发路径）
├── 01-home/code.html        # 静态快照（剥 <script>、资源 URL 绝对化，随处可渲染）
├── 01-home/screen.png       # 浏览器基准截图
└── ...
```

## 拆解原理

- **候选枚举**：`a[href^="#"]`、`[role=tab/menuitem]`、`[onclick]`、`button/[type=submit]/[class*=btn]`
  （登录按钮常常没有 onclick），叠加危险动作文案黑名单（退出/删除/重置等）；
  枚举与点击回放共用同一份过滤 JS，序号严格对齐
- **可见性**：零尺寸 + display/visibility/opacity 过滤 + `offsetParent` 剪枝——
  登录墙场景整个外壳 `display:none`，内部导航全是不透明但 0×0 的死元素
- **状态识别（三层去重）**：内容指纹（hash+可见元素数+正文文本，数字归零）挡同屏重复；
  结构指纹（可见元素 tag.class 集合，仅作用于详情层）挡"同模板不同数据"的详情页爆炸；
  构建前再按 screen.png 缩略签名兜底
- **状态回放**：每个状态记录"从首页出发的点击路径"，探索下一层时 reload + 重放
  （不依赖 history.back，内部路由函数也能爬）
- **快照冻结**：剥 `<script>`/`<noscript>` 冻结 JS 渲染结果；img/link/style url() 全部绝对化

## 引擎特性（与 stitch-to-sketch 同源，另有增强）

- **分页构建**：`--per-page 6`，每个 Page 最多 6 画板自动新建页，页面命名 `{入口名}-{NN}`
- **断点续跑**：每屏 build_state.json 记 done 标记；连续两屏失败自动熔断（视为 Sketch/MCP 死亡）
- **懒加载与显现动画**：提取前整页滚动触发懒加载；reveal-on-scroll 类元素强制显直；
  IntersectionObserver 覆盖让观察目标恒相交（只加类不撤类）
- **SVG 全矢量**：path/circle/ellipse/rect（含圆角弧线）/line/polygon 全部转钢笔路径，
  任一形状无法矢量化才整体回退光栅；对齐用 getBBox × viewBox 缩放
- **分片基准截图**：规避 Chromium 视口外图片渲染空白；fixed/sticky 第 2 片起隐藏
  （悬浮层定格首屏，等价 full_page 语义）
- **同款卡片一致性**：同父同标签 ≥3 兄弟的纯色底/边框 ±3 色差吸附众数；
  与祖先同色的铺底切块合并，消除拼接缝
- **大模块文件夹化**：子元素 ≥4 或块面 ≥12% 页面的结构容器保留成组，图层树可管理

## 环境与前置

macOS + Sketch 2025.2.4+（官网版，`⌘K → Start MCP Server`）+ Chrome + `pip install playwright`。
字体按页面实际使用安装：`bash scripts/setup_fonts.sh "Noto Sans SC:400,500,700"`。

## 已知限制

- 模态框/浮层不作为独立屏（指纹去重会跳过同结构状态）
- 带副作用的按钮（真实删除/提交）与普通按钮同等对待——demo 站无碍，连真实后端的页面慎爬
- canvas / webGL 内容按位图处理
- 超长页（>16000px）建议先分段或用 `--max-screens` 控制
