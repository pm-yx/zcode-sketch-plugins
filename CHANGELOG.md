# Changelog

All notable changes to the plugins in this repository are documented here.
Versions follow semver; each plugin versions independently.

## html-to-sketch

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
