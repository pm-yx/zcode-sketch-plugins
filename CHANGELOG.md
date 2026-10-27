# Changelog

All notable changes to the plugins in this repository are documented here.
Versions follow semver; each plugin versions independently.

## Repository

### 2026-10-27 — Engine updates from production practice

- Both standalone skills (`pmyx-html-to-sketch`, `pmyx-stitch-to-sketch`) synced with a batch of
  practice-validated engine updates; the html-to-sketch package ships the same fixes as v0.2.0
- Decorative pseudo-elements (empty-content color blocks / dots / underline bars) extracted as
  sibling shape layers; two iron rules: collect **outside** the element-becomes-a-layer guard
  (hosts without own visuals still contribute decorations), skip `mask-image` pseudo-elements
  (solid-color conversion would bake into opaque blocks)
- SVG sprite `<use>` references resolved in place before the walk (`resolveUses`) — embedded
  Lucide/Iconfont `symbol` icons used to come out empty (no paths to collect, empty raster bake)
- Single-line text vertically centered in a taller host box records host-box geometry
  (`vc`/`hc` markers) and is placed tight-frame centered in Sketch — `textBehaviour` does not
  stick, so "tight frame + centered coordinates" is the only reliable route
- Font weight mapping fixed: Sketch `style.fontWeight` is the AppKit scale (5=Regular, 6=Medium,
  7=Semibold, 8=Bold); CSS weights shift +1 step (400→5 … 700→8) — dividing by 100 rendered
  bold as regular
- `mapFont(ff, txt)` routes CJK text to the stack's CJK family: Sketch text layers are
  single-font with no per-glyph fallback, so Latin fonts + Chinese text persisted to PingFang
- Fixed line heights convert to **auto** after layer creation with half-leading y compensation
  (frames hug glyphs at the browser-visual position)
- Skill docs now cover: font family naming pitfalls (fontTools name-table rewrite needs a new
  PostScript name + filename to re-register), async font-index refresh after Sketch launch,
  pre-save document integrity check (list pages vs. plan — protects good versions from being
  overwritten on a reverted session; `doc.save` also changes the in-memory Document id), and
  rebuild hygiene (clear stale state dirs, empty the document first, delete old artboards
  before single-screen reruns)

### 2026-10-20 — Standalone skills added

- Both plugins packaged as standard ZCode skills under `skills/`
  (`pmyx-html-to-sketch`, `pmyx-stitch-to-sketch`; the `pmyx-` prefix marks the author)
- Same engine as the plugin packages; install without the plugin marketplace:
  `cp -r skills/pmyx-* ~/.agents/skills/` — slash invocation (`/pmyx-html-to-sketch`) and
  natural-language triggers both work in new sessions
- Functional test round passed: Stitch screen diff 3.07/100; portal discovery 4→3 screens
  (screenshot dedupe), builds gated at 9.63/2.19/3.15

## html-to-sketch

### v0.2.0 — 2026-10-27

- Ships the practice-validated engine updates described under Repository → 2026-10-27:
  decorative pseudo-element extraction, SVG sprite `<use>` resolution, host-box centered text,
  AppKit font-weight scale (+1 step), CJK-aware `mapFont` routing, line-height auto conversion
  with half-leading compensation
- Plugin SKILL.md: font pitfalls (family naming / single-font fallback / async index / weight
  scale), MCP reconnection note, pre-save integrity check, new "rebuild & troubleshooting"
  section

### v0.1.0 — 2026-10-20

Initial release.

- **Interactive-state discovery** (`discover_screens.py`): crawls a real browser — hash routing,
  internal view-routing functions, login walls; candidate enumeration (nav semantics + generic
  buttons + danger-action blocklist), triple dedupe (content fingerprint / structure fingerprint
  for detail templates / screenshot signature), reload+replay state paths, snapshot freezing
  (scripts stripped, asset URLs absolutized)
- **Batch orchestration** (`convert_project.py`): auto-pagination (≤6 artboards per Page,
  `{entry}-{NN}` naming), screenshot-level pre-build dedupe, resumable via state files,
  consecutive-failure circuit breaker
- **Engine** (lineage of stitch-to-sketch v0.3.1, independently evolved):
  - SVG stays fully vector: path/circle/ellipse/rect (incl. rounded arcs)/line/polygon → pen paths,
    raster fallback only when any shape fails
  - Lazy-load scroll priming, reveal-on-scroll force-show, IntersectionObserver always-intersecting
    override
  - Tiled baseline screenshots (avoids Chromium beyond-viewport blank images), fixed/sticky hidden
    from tile 2, overlap-free strip stitching
  - File-based images end to end (zero base64 in build payloads), `file://` percent-decoding
  - Same-series card color snapping (±3 tolerance to mode), same-color background block merging,
    structural containers kept as groups (≥4 children or ≥12% page area)
  - Multi-layer backgrounds (linear preferred), radial-gradient mapping, raw-attribute gradient
    stops preserving alpha, hsl/hex color support, `offsetParent` pruning, sr-only text skipping,
    pseudo-element text layers
  - Cross-chunk parent integrity: grouping decided once in Python, JS mirrors it

## stitch-to-sketch

### v0.3.1 — 2026-10-19

- Multi-board single-document builds: init resolves the target page **by name** first
  (`Page.select()` is unreliable across run_code contexts), plus `--new-page` to create pages
- Documented: `doc.save()` changes the in-memory Document id — match documents by path afterwards

### v0.3.0 — 2026-10-19

- CJK token-by-token line wrapping (per-token Range top measurement; Latin by word, CJK by char)
- Design-semantic layer naming (`--naming-lang zh/en`) instead of framework class names
- Gradient endpoint clamping: CSS corner-projection endpoints outside the shape twist the gradient
  axis in Sketch; endpoints converge inside while direction is preserved (135° becomes corner-to-corner)
- Aura layers (blur-2xl/3xl) dropped by default (`--keep-aura` to keep)
- fixed repositioning and z-order partitioning (fixed headers created last)
- SVG vector mode by default (`ShapePath.fromSVGPath`) with raster fallback
- Full pixel-diff gate across all screens (web ≤7.9, mobile ≤13.5 mean channel distance /255)

### Earlier

- v0.1.0–v0.2.0: initial pipeline (Playwright extraction → Sketch MCP modular build → PNG diff gate),
  placeholder capture, post-walk screenshots, giant-page chunking (sibling-subtree greedy packing)
