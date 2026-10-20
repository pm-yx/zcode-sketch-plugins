# stitch-to-sketch

把 [Google Stitch](https://stitch.withgoogle.com) 导出的 HTML 100% 还原为 Sketch 原生设计文件。
ZCode 插件，[返回总览](../../README.md)。

## 输入结构

Stitch 每屏导出一个子目录（内含 `code.html`，`screen.png` 可选作交叉参考）：

```
导出目录/
├── _1/code.html
├── _2/code.html
├── ...
└── 巨页原型.html      # 根级散置的单页 HTML 也会作为一个屏参与转换
```

## 用法

一条命令整项目批量（自动提取 → 网格排布 → 分模块构建 → 保存）：

```bash
python3 scripts/convert_all.py <导出目录> --save 输出.sketch [--cols 4]
```

单屏细控（三阶段：init 建文档/画板 → modules 分块建层 → finish 导出+保存）：

```bash
# 1) 提取：浏览器精确几何 + 计算样式 → sketch_build/layout.json + reference.png
python3 scripts/extract_layout.py <屏>/code.html --type mobile --width 390 --out <屏>/sketch_build

# 2) 构建
python3 scripts/build_sketch.py <屏>/sketch_build/layout.json \
    --name "屏幕名" --naming-lang zh --export-dir <屏>/sketch_build --save 输出.sketch
```

### 关键参数

| 参数 | 说明 |
|---|---|
| `--type mobile/web` + `--width` | 移动端默认 390，网页端 1440；画板高度 = 内容高度 |
| `--naming-lang zh/en` | 图层设计语义命名语言（默认中文） |
| `--max-module-els N` | 每构建块元素上限（默认 60），超长页稳定性用 |
| `--svg-mode vector/raster` | SVG 默认矢量钢笔路径，失败自动回退光栅 |
| `--keep-aura` | 保留 blur 氛围光层（默认省略，卡片取纯渐变/底色） |
| `--doc-id` / `--page-name` / `--new-page` | 多板合一同文档：复用文档、指定 Page、自动新建页 |

## 还原规则要点

- 渐变端点界内收敛：CSS 角投影端点越界会扭曲渐变轴，收敛后方向严格不变，135° 对角自动角对角
- 渐变 stop 用原始属性解析，保留 rgba alpha（computed 样式会丢透明度）
- fixed 底部导航贴画板底、顶部 header 贴顶；fixed/sticky 子树最后创建避免被内容盖住
- 长中文文本按浏览器实际折行逐 token 拆行；图标字体（Material Symbols）以连字渲染
- 图片先下载/烘焙为本地文件再传入 Sketch，比例位置不变

## 验证闭环

finish 阶段每屏导出 `<屏名>.png`，与 `sketch_build/reference.png`（浏览器基准）逐像素比对。
建议保留工具链思路：PIL+numpy 计算平均差异并按条带定位热区，有差异查 `layout.json`
（每个元素的坐标/样式都在）定位修正后重跑该屏。

## 环境与前置

macOS + Sketch 2025.2.4+（官网版，`⌘K → Start MCP Server`）+ Chrome + `pip install playwright`。
字体：`bash scripts/setup_fonts.sh`（Stitch 标准三件套）或按页面字体追加。
