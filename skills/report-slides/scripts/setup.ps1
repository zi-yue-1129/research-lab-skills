# setup.ps1 — report-slides project setup for Windows PowerShell
# Run from the project root:
#   & (Get-ChildItem $env:USERPROFILE\.claude -Recurse -Filter setup.ps1 |
#       Where-Object FullName -like '*report-slides*' | Select-Object -First 1).FullName

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

New-Item -ItemType Directory -Force -Path "scripts", "docs\slides\reports", "docs\slides\assets\diagrams" | Out-Null
Copy-Item "$ScriptDir\generate_slides.py" "scripts\" -Force
Copy-Item "$ScriptDir\validate_diagram_manifest.py" "scripts\" -Force
Copy-Item "$ScriptDir\render_review_sheet.py" "scripts\" -Force

Write-Host "report-slides setup complete:"
Write-Host "  scripts\generate_slides.py"
Write-Host "  scripts\validate_diagram_manifest.py"
Write-Host "  scripts\render_review_sheet.py"
Write-Host "  docs\slides\reports\"
Write-Host "  docs\slides\assets\diagrams\"
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
