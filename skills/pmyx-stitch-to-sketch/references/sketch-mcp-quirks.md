# Sketch MCP run_code 沙箱实测 quirks（2026-10 实测，SketchMCP 1.0 / Sketch 2025.2.4+）

全部经最小复现验证。给这个 Sketch MCP 版本写任何 SketchAPI 脚本前必读。

## 环境

- HTTP MCP：`http://localhost:31126/mcp`（Streamable HTTP，`initialize` 响应头带 `Mcp-Session-Id`，后续请求要带回）
- 实际暴露工具只有 **2 个**：`run_code`（万能）+ `get_selection_as_image`。
  官网文档写的 `get_document_info` / `get_layer_tree_summary` 等在本版本**不存在**（调用返回 "tool not found"）。一切读取也走 `run_code`。
- 脚本必须以 `const sketch = require('sketch')` 开头；用 `console.log()` 回传结果。
- 回传文本形态：每条 `console.log` 一行，整体被单引号包裹、内部双引号转义
  （`'{"ok":true,\"id\":...}'`）。解析时先剥外层引号、`\"`→`"`，再做括号配平 JSON 提取；
  末尾可能有包裹器的空对象，**要按 `ok` 标记筛选**，不能取"最后一个 JSON"。

## Bug 1：数组字面量里的标识符函数调用 → 伪 SyntaxError

```js
const a = [f(x)]          // ✗ SyntaxError: Unexpected token '('. Expected a property name after '.'
const a = [(() => 1)()]   // ✗ 同样挂（IIFE 也算）
const a = [obj.f(x)]      // ✓ 方法调用不受影响
const g = f(x); const a = [g]   // ✓ 先赋临时变量再进数组
```

**规避**：永远不要写 `[fn(...)]`。先 `const tmp = fn(...)` 再 `[tmp]`。

## Bug 2：`layer.id` 赋值给变量 → undefined

```js
const gid = g.id            // ✗ undefined
containers[k] = g.id        // ✗ undefined（JSON.stringify 丢键）
console.log({id: g.id})     // ✓ 对象字面量内联访问正常
const gid = '' + g.sketchObject.objectID()   // ✓ 推荐：objectID 稳定可用
```

**规避**：需要存 layer id 时用 `'' + layer.sketchObject.objectID()`。

## 状态与查找

- 每次 `run_code` 是独立 JS 上下文，**但文档/图层是 App 状态、跨调用存活**。
  分块构建：第一块建文档/Frame 并回传 `docId/frameId`；后续块用
  `sketch.Document.getDocuments()` 找 doc、`sketch.find('#' + frameId, page)` 找 Frame。
- 新版 API：Artboard 已废，画板 = `new Group.Frame({...})`；顶层画板枚举 `page.canvasLevelFrames`。
- **Page.select() 不可靠**：run_code 里调用后，后续独立上下文的 `doc.selectedPage` 仍指旧页
  （实测复用文档建第二块板，_2~_5 画板全落错页）。**跨调用定位页面必须按 `page.name` 遍历查找**；
  build_sketch.py init 已改为按 pageName 找页优先，`--new-page` 才新建。
- **未保存文档 save 后 id 会变**：`doc.save(path)` 后内存 Document id 改变（实测 6A26…→DD93…）。
  跨调用查文档用 `d.path` 匹配（注意 percent 编码），不要长期缓存 docId。
- 圆角：`shape.style.corners.radii = [tl, tr, br, bl]`（顺时针从左上）。
- 渐变：`fills = [{fillType: Style.FillType.Gradient, gradient: {gradientType, from:{x,y}, to:{x,y}, stops:[{position, color}]}}]`，from/to 是图层内 0..1 归一化坐标。
- 矢量：`ShapePath.fromSVGPath(dString)` 可用（钢笔路径），frame 赋值即缩放到目标盒。
- 阴影：`style.shadows = [{color, x, y, blur, spread, enabled: true}]`（**enabled 必须显式 true**）。
- 导出：`sketch.export(layer, {output, filename: 'x.png', formats: ['png'], scales: '1'})`（output+filename 都要给）。
- 文本：`new Text({text, style: {fontFamily, fontSize, fontWeight(1-12≈字重/100), textColor, alignment}})`，
  `style.lineHeight`（px）/`style.letterSpacing` 可设。字体必须已安装（`~/Library/Fonts`），
  Material Symbols 以连字渲染 icon（文本 = icon 名称）。

## 会话示例（bash 探活）

```bash
SID=$(curl -si -X POST http://localhost:31126/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"p","version":"0"}}}' \
  | grep -i 'Mcp-Session-Id' | tr -d '\r' | awk '{print $2}')
# 之后每个请求带 -H "Mcp-Session-Id: $SID"
```
