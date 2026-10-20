#!/bin/bash
# setup_fonts.sh — download & install Google Fonts into ~/Library/Fonts (per-user, no sudo).
# Idempotent: skips files already present. Used before building Sketch documents so
# text layers and Material Symbols ligatures render with the real families.
#
# Usage:
#   ./setup_fonts.sh                 # install the default Stitch font set
#   ./setup_fonts.sh "Family A:400,700" "Family B:400"
set -euo pipefail
FONT_DIR="$HOME/Library/Fonts/stitch"
mkdir -p "$FONT_DIR"

# Default Stitch export set: UI font, numeric/mono font, icon font (variable, ligatures)
if [ $# -eq 0 ]; then
  set -- "Plus Jakarta Sans:400,500,600,700" "JetBrains Mono:400,500,600" "Material Symbols Outlined:400"
fi

installed=0; skipped=0; failed=0
for spec in "$@"; do
  family="${spec%%:*}"
  weights="${spec##*:}"
  famq="${family// /+}"
  if [ "$family" = "Material Symbols Outlined" ]; then
    # variable icon font; one file, ligatures on by default in Sketch
    css_url="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined"
  else
    css_url="https://fonts.googleapis.com/css2?family=${famq}:wght@${weights//,/&}"
  fi
  # curl's default UA makes Google's CSS API return .ttf URLs (woff2 requires a browser UA)
  css=$(curl -sf "$css_url") || { echo "FAIL css: $family"; failed=$((failed+1)); continue; }
  while IFS= read -r url; do
    fname=$(basename "$url")
    # keep family in filename so multiple families never collide
    safe_family=$(echo "$family" | tr ' ' '_')
    # extract weight from the css block that precedes this URL is unreliable in a flat
    # loop; Google TTF names already carry weight, e.g. PlusJakartaSans-Bold.ttf
    dest="$FONT_DIR/${safe_family}-${fname}"
    if [ -s "$dest" ]; then skipped=$((skipped+1)); continue; fi
    if curl -sfL "$url" -o "$dest"; then
      installed=$((installed+1)); echo "installed: $(basename "$dest")"
    else
      echo "FAIL font: $url"; failed=$((failed+1))
    fi
  done < <(printf '%s\n' "$css" | grep -o 'https://fonts.gstatic.com/[^)]*\.ttf' | sort -u)
done

echo "---"
echo "fonts installed=$installed skipped(existing)=$skipped failed=$failed  dir=$FONT_DIR"
# Make sure the font subsystem picks them up right away (harmless if already current)
atsutil server -kickstart >/dev/null 2>&1 || true
[ "$failed" -eq 0 ]
