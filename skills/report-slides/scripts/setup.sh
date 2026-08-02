#!/usr/bin/env bash
# report-slides project setup — copies required scripts into the current project.
# Run from the project root:
#   bash "$(find ~/.claude -path "*/report-slides/scripts/setup.sh" | head -1)"
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_DIR="$(dirname "$SCRIPT_DIR")"

mkdir -p scripts docs/slides/reports docs/slides/assets/diagrams

cp "$SCRIPT_DIR/generate_slides.py" scripts/
cp "$SCRIPT_DIR/validate_diagram_manifest.py" scripts/
cp "$SCRIPT_DIR/render_review_sheet.py" scripts/

echo "report-slides setup complete:"
echo "  scripts/generate_slides.py"
echo "  scripts/validate_diagram_manifest.py"
echo "  scripts/render_review_sheet.py"
echo "  docs/slides/reports/"
echo "  docs/slides/assets/diagrams/"
echo "  Pillow is required only for review-sheet composition."
echo ""
echo "Optional — set a default slide style (default | minimal | dark | paper):"
echo "  bash \"$(find ~/.claude -path "*/report-slides/scripts/set-style.sh" | head -1)\" paper"
echo ""
echo "Optional — diagram slides (Mermaid):"
echo "  npm i -g @mermaid-js/mermaid-cli"
