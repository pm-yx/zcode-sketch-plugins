# zcode-sketch-plugins

[English](README_EN.md) | 中文

把 HTML 设计稿 100% 还原为 **Sketch 原生图层**（不是截图贴图）的一组 [ZCode](https://zcode.ai) 插件：
真实矩形 / 圆角 / 渐变 / 阴影 / 文本 / 图片 / SVG 矢量路径，图层按设计语义命名。

本仓库包含两个插件：

| 插件 | 适用场景 | 版本 |
|---|---|---|
| [`packages/stitch-to-sketch`](packages/stitch-to-sketch) | [Google Stitch](https://stitch.withgoogle.com) 导出的单屏静态 HTML，逐屏转换 | v0.3.1 |
| [`packages/html-to-sketch`](packages/html-to-sketch) | **任意** HTML：官网、管理后台、SPA——交互子页面自动发现、动态拆解 | v0.1.0 |

两者共享同一套提取/构建引擎（`extract_layout` + `build_sketch`），后者是前者的通用化演进。

## 工作原理

```
HTML ──Playwright(Chrome)──▶ 逐元素 getBoundingClientRect + getComputedStyle
     ──▶ layout.json（几何 + 计算样式 + 文本逐行折行 + SVG 路径 + fixed 标记）
     ──Sketch MCP run_code──▶ 模块化分块构建原生图层（≤60 元素/块，跨块按 id 挂载）
     ──▶ 导出 PNG 与浏览器基准逐像素比对（验证闭环）
```

核心特性：

- **像素级还原**：几何、圆角、线性/径向渐变（含透明 stop）、阴影、边框全部按计算样式落地
- **SVG 全矢量**：图标/图表转钢笔路径（`ShapePath.fromSVGPath`），复制出来就是可编辑矢量
- **文本真折行**：CJK 逐 token 测行盒，长中文段落按浏览器实际折行拆成逐行文本层
- **设计语义命名**：图层名是「卡片 · 月度账单」而非 `px-space-sm py-0.5`（中/英文可选）
- **交互态拆解**（html-to-sketch）：真实浏览器爬态——hash 路由、`go('view')` 内部路由、登录墙、
  弹窗状态；内容指纹 + 结构指纹 + 截图签名三层去重
- **稳定性**：每页 ≤6 画板自动分页、断点续跑、连续失败熔断、图片全文件化（载荷零 base64）
- **验证闭环**：每屏导出 PNG 与浏览器基准做逐像素差异门禁

## 环境要求

- macOS + [Sketch](https://www.sketch.com) **2025.2.4+**（官网版；内置 MCP：`⌘K → Start MCP Server`）
- Google Chrome
- Python 3.10+，`pip install playwright`（复用系统 Chrome，无需下载内核）

## 安装

```bash
git clone https://github.com/pm-yx/zcode-sketch-plugins.git
```

- **ZCode**：插件市场 → 本地目录安装，分别指向 `packages/stitch-to-sketch` 与 `packages/html-to-sketch`
- 字体（首次）：`bash packages/<插件>/scripts/setup_fonts.sh`，或按页面字体按需安装
  （如 `setup_fonts.sh "Noto Sans SC:400,500,700"`）

## 快速上手

**Stitch 导出转换**（每屏一个子目录含 `code.html`）：

```bash
python3 packages/stitch-to-sketch/scripts/convert_all.py <导出目录> \
    --save 输出.sketch
```

**任意 HTML（含多子页面站点）**：

```bash
# 1) 动态拆解：浏览器里点遍可点击元素，产出 screens/<NN>-<视图>/code.html + 基准截图
python3 packages/html-to-sketch/scripts/discover_screens.py dist/portal.html \
    --out screens_portal --width 1440

# 2) 一键构建：自动分页（每页 ≤6 画板）、断点续跑、逐屏像素门禁
python3 packages/html-to-sketch/scripts/convert_project.py \
    screens_portal/manifest.json --save 输出.sketch
```

日常使用建议直接让 ZCode agent 执行——两个插件的 `SKILL.md` 就是写给 agent 的操作手册
（触发词：`把 <目录/HTML> 转成 sketch`）。开始前 agent 会确认：项目类型（移动端 390 / 网页端 1440）
与图层命名语言（中文/英文）。

## 文档

- [`packages/stitch-to-sketch/README.md`](packages/stitch-to-sketch/README.md) — Stitch 工作流详解
- [`packages/html-to-sketch/README.md`](packages/html-to-sketch/README.md) — 任意 HTML 工作流详解（拆解原理、去重策略）
- [`docs/sketch-mcp-quirks.md`](docs/sketch-mcp-quirks.md) — Sketch MCP run_code 沙箱实测 bug 与规避
- [`CHANGELOG.md`](CHANGELOG.md) — 版本历史

## 已知限制

- 氛围光（blur-2xl/3xl 装饰层）默认不落地，卡片取纯渐变/底色（`--keep-aura` 可保留）
- transform 3D 展示区（如手机样机透视）像素级还原有限，建议人工补片
- canvas / webGL 内容按位图处理
- 模态框/浮层作为独立屏的能力有限（发现器按可见内容指纹去重）

## 致谢

设计思路参考了这些先驱项目（本项目的引擎为独立实现）：

- [html2sketch](https://github.com/ant-design/html2sketch)（ant-design）— 可见性判定、伪元素文本、溢出蒙层等规则
- [html-sketchapp](https://github.com/html-sketchapp/html-sketchapp) — HTML → Sketch 的早期开拓

## License

[MIT](LICENSE) © 2026 Brose
