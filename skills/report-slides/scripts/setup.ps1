# setup.ps1 — report-slides project setup for Windows PowerShell
# Run from the project root:
#   & (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
#       Where-Object FullName -like '*report-slides*' | Select-Object -First 1).FullName [SlidesDir]
# SlidesDir defaults to docs\slides; SKILL.md resolves it via resource-resolver
# and passes it explicitly.

param(
    [string]$SlidesDir = "docs\slides"
)

# The param default only applies when the argument is omitted entirely. SKILL.md
# always passes $SLIDES_DIR explicitly, and an unresolved slides role makes that
# $null -- cast to an empty string, which would turn the New-Item paths below
# into "\reports" and "\assets\diagrams", i.e. the current drive's ROOT.
# Re-apply the default for empty/null/whitespace input as well.
if ([string]::IsNullOrWhiteSpace($SlidesDir)) {
    $SlidesDir = "docs\slides"
}

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

New-Item -ItemType Directory -Force -Path "scripts", "$SlidesDir\reports", "$SlidesDir\assets\diagrams" | Out-Null
Copy-Item "$ScriptDir\generate_slides.py" "scripts\" -Force
Copy-Item "$ScriptDir\validate_diagram_manifest.py" "scripts\" -Force
Copy-Item "$ScriptDir\render_review_sheet.py" "scripts\" -Force

Write-Host "report-slides setup complete:"
Write-Host "  scripts\generate_slides.py"
Write-Host "  scripts\validate_diagram_manifest.py"
Write-Host "  scripts\render_review_sheet.py"
Write-Host "  $SlidesDir\reports\"
Write-Host "  $SlidesDir\assets\diagrams\"
Write-Host "  Pillow is required only for review-sheet composition."
Write-Host ""

$setStyle = (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter set-style.ps1 |
    Where-Object FullName -like "*report-slides*" | Select-Object -First 1).FullName
if ($setStyle) {
    Write-Host "Optional - set a default slide style (default | minimal | dark | paper):"
    Write-Host "  & '$setStyle' paper"
    Write-Host ""
}

Write-Host "Optional - diagram slides (Mermaid):"
Write-Host "  npm i -g @mermaid-js/mermaid-cli"
