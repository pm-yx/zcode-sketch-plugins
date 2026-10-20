# zcode-sketch-plugins

[中文](README.md) | English

A set of [ZCode](https://zcode.ai) plugins that convert HTML designs into **native Sketch layers** —
real rectangles, corner radii, gradients, shadows, text, images and SVG vector paths
(not screenshot pastes), with design-semantic layer names.

The repository contains two plugins:

| Plugin | Use case | Version |
|---|---|---|
| [`packages/stitch-to-sketch`](packages/stitch-to-sketch) | Single-screen static HTML exported from [Google Stitch](https://stitch.withgoogle.com), screen by screen | v0.3.1 |
| [`packages/html-to-sketch`](packages/html-to-sketch) | **Any** HTML: marketing sites, admin dashboards, SPAs — interactive sub-pages are discovered and decomposed automatically | v0.1.0 |

Both share the same extraction/build engine (`extract_layout` + `build_sketch`); the latter is a
generalized evolution of the former.

## How it works

```
HTML ──Playwright(Chrome)──▶ per-element getBoundingClientRect + getComputedStyle
     ──▶ layout.json (geometry + computed styles + per-line text wrapping + SVG paths + fixed marks)
     ──Sketch MCP run_code──▶ modular chunked native-layer building (≤60 elements/chunk)
     ──▶ exported PNG vs browser baseline per-pixel diff gate (verification loop)
```

Key features:

- **Pixel-accurate restoration**: geometry, radii, linear/radial gradients (incl. transparent stops),
  shadows and borders all derived from computed styles
- **SVG stays vector**: icons/charts become pen paths (`ShapePath.fromSVGPath`), copy-paste keeps them editable
- **Real text wrapping**: CJK token-by-token line-box measurement splits long paragraphs into per-line text layers
- **Design-semantic naming**: layers are named "Card · Monthly Bill" rather than `px-space-sm py-0.5` (Chinese/English)
- **Interactive-state discovery** (html-to-sketch): crawls states in a real browser — hash routing,
  internal `go('view')` routing, login walls, modal states; three-tier dedupe (content fingerprint +
  structure fingerprint + screenshot signature)
- **Stability**: auto-pagination (≤6 artboards per page), resumable builds, circuit breaker,
  file-based images (zero base64 in payloads)
- **Verification loop**: per-screen exported PNG vs browser baseline pixel-diff gate

## Requirements

- macOS + [Sketch](https://www.sketch.com) **2025.2.4+** (direct-download version; built-in MCP via `⌘K → Start MCP Server`)
- Google Chrome
- Python 3.10+, `pip install playwright` (uses system Chrome, no browser download needed)

## Install

```bash
git clone https://github.com/pm-yx/zcode-sketch-plugins.git
```

- **ZCode**: plugin marketplace → install from local directory, pointing at `packages/stitch-to-sketch`
  and `packages/html-to-sketch`
- Fonts (first run): `bash packages/<plugin>/scripts/setup_fonts.sh`, or install per-page fonts as needed,
  e.g. `setup_fonts.sh "Noto Sans SC:400,500,700"`

## Quick start

**Stitch exports** (one sub-directory per screen containing `code.html`):

```bash
python3 packages/stitch-to-sketch/scripts/convert_all.py <export-dir> --save out.sketch
```

**Any HTML (multi-page sites included)**:

```bash
# 1) Discover: clicks through candidates in a browser → screens/<NN>-<view>/code.html + baseline
python3 packages/html-to-sketch/scripts/discover_screens.py dist/portal.html \
    --out screens_portal --width 1440

# 2) Build: auto-pagination (≤6 artboards/page), resumable, per-screen pixel gate
python3 packages/html-to-sketch/scripts/convert_project.py \
    screens_portal/manifest.json --save out.sketch
```

For day-to-day use, simply ask your ZCode agent — each plugin's `SKILL.md` is the operator manual
for the agent (trigger: "convert <dir/HTML> to Sketch"). The agent will confirm the project type
(mobile 390 / web 1440) and layer-naming language (Chinese/English) before starting.

## Docs

- [`packages/stitch-to-sketch/README.md`](packages/stitch-to-sketch/README.md) — Stitch workflow in detail (Chinese)
- [`packages/html-to-sketch/README.md`](packages/html-to-sketch/README.md) — any-HTML workflow: discovery internals, dedupe strategy (Chinese)
- [`docs/sketch-mcp-quirks.md`](docs/sketch-mcp-quirks.md) — field-tested Sketch MCP `run_code` sandbox bugs and workarounds
- [`CHANGELOG.md`](CHANGELOG.md) — version history

## Known limitations

- Aura layers (blur-2xl/3xl decoration) are dropped by default; cards keep solid gradient fills (`--keep-aura` to keep)
- Transform-3D showcase areas (e.g. perspective phone mockups) have limited pixel-level fidelity
- canvas / WebGL content is treated as bitmaps
- Modals/overlays as standalone screens are limited (the discoverer dedupes by visible-content fingerprint)

## Acknowledgements

Design ideas referenced from these pioneering projects (this engine is an independent implementation):

- [html2sketch](https://github.com/ant-design/html2sketch) (ant-design) — visibility rules, pseudo-element text, overflow masks
- [html-sketchapp](https://github.com/html-sketchapp/html-sketchapp) — early HTML → Sketch pioneer

## License

[MIT](LICENSE) © 2026 Brose
