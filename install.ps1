<#
.SYNOPSIS
    research-lab-skills installer (Windows PowerShell / PowerShell 7+)

.DESCRIPTION
    Native Windows counterpart to install.sh. Clones the repo and copies the
    requested skill directories into ~/.claude/skills (or a project-local
    .claude/skills when -Local is passed).

.EXAMPLE
    # All skills, global install
    irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1 | iex

.EXAMPLE
    # Flags require the script text, not a piped invocation, so download it
    # into a scriptblock first:
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Local
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -ArsOnly
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -LabOnly
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Uninstall

.EXAMPLE
    # From cmd.exe, wrap the same command with powershell -Command
    powershell -Command "irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1 | iex"

.EXAMPLE
    # Check the runtime dependencies the skills need (installs nothing)
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/zi-yue-1129/research-lab-skills/main/install.ps1))) -Doctor
#>

param(
    [switch]$Local,
    [switch]$ArsOnly,
    [switch]$LabOnly,
    [switch]$Uninstall,
    [switch]$Doctor
)

$ErrorActionPreference = "Stop"

$Repo = "https://github.com/zi-yue-1129/research-lab-skills.git"

# Shared foundation both lab and ARS skills depend on -- always installed
$ResolverSkills = @("resource-resolver", "agent-state")
# Lab skills (experiment journal + presentations + mode routing)
$LabSkills = @("research-log", "report-slides", "research-mode")
# Academic Research Skills (deep research, paper writing, review, pipeline)
$ArsSkills = @("research-project-init", "deep-research", "academic-paper", "academic-paper-reviewer", "academic-pipeline")

$Skills = $ResolverSkills + $LabSkills + $ArsSkills
if ($ArsOnly) { $Skills = $ResolverSkills + $ArsSkills }
if ($LabOnly) { $Skills = $ResolverSkills + $LabSkills }

if ($Local) {
    $Dest = Join-Path (Get-Location) ".claude\skills"
} else {
    $Dest = Join-Path $HOME ".claude\skills"
}

function Install-Skills {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Error "git is required. Install Git for Windows: https://git-scm.com/download/win"
        exit 1
    }

    $Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("crs-" + [System.Guid]::NewGuid().ToString())
    try {
        Write-Host "Downloading research-lab-skills..."
        git clone --depth 1 $Repo $Tmp -q

        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
        foreach ($skill in $Skills) {
            Copy-Item -Recurse -Force (Join-Path $Tmp "skills\$skill") $Dest
            Write-Host "  * $skill"
        }

        Write-Host ""
        Write-Host "Installed to: $Dest"
        Write-Host "Restart Claude Code to activate the skills."
        Write-Host "  Lab:      /research-log  /report-slides  /mode"
        Write-Host "  Academic: /ars-full  /ars-plan  /ars-lit-review  /ars-review  and more"
    }
    finally {
        Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
    }
}

function Uninstall-Skills {
    # resource-resolver is a shared dependency of both skill families. A subset
    # uninstall (-LabOnly / -ArsOnly) must not pull it out from under the skills
    # that stay installed; only a full uninstall removes it.
    $subset = $ArsOnly -or $LabOnly
    foreach ($skill in $Skills) {
        if ($subset -and ($ResolverSkills -contains $skill)) {
            Write-Host "  - Kept (shared dependency): $(Join-Path $Dest $skill)"
            continue
        }
        $target = Join-Path $Dest $skill
        if (Test-Path $target) {
            Remove-Item -Recurse -Force $target
            Write-Host "  * Removed: $target"
        } else {
            Write-Host "  - Not found (skipped): $target"
        }
    }
    Write-Host "Done."
}

function Test-PythonModule {
    <#
    .SYNOPSIS
        Report whether a module imports under the `python` on PATH.
    #>
    param([string]$Module)

    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { return $false }
    python -c "import $Module" 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Write-Check {
    <#
    .SYNOPSIS
        Print one dependency row and return whether a required item is missing.
    #>
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail,
        [string]$Fix,
        [ValidateSet("required", "optional")][string]$Level = "required"
    )

    if ($Ok) {
        Write-Host ("  [ok]   {0,-22} {1}" -f $Name, $Detail) -ForegroundColor Green
        return $false
    }
    $tag = if ($Level -eq "required") { "MISS" } else { "warn" }
    $color = if ($Level -eq "required") { "Red" } else { "Yellow" }
    Write-Host ("  [{0}] {1,-22} {2}" -f $tag, $Name, $Detail) -ForegroundColor $color
    if ($Fix) { Write-Host ("         fix: {0}" -f $Fix) -ForegroundColor DarkGray }
    return ($Level -eq "required")
}

function Invoke-Doctor {
    <#
    .SYNOPSIS
        Report the runtime dependencies the skills need. Installs nothing.

    .DESCRIPTION
        Copying the skill directories is only half an install: report-slides
        additionally shells out to Python and to an office renderer, and a
        Windows box satisfies almost none of that out of the box. Every one of
        those gaps used to surface as a silent no-op mid-deck, so check them up
        front and print the exact command that fixes each one.
    #>
    Write-Host ""
    Write-Host "research-lab-skills -- dependency check" -ForegroundColor Cyan
    Write-Host ""

    $missing = $false

    Write-Host "Core"
    $git = Get-Command git -ErrorAction SilentlyContinue
    $missing = (Write-Check "git" ([bool]$git) $(if ($git) { $git.Source } else { "not found" }) `
        "https://git-scm.com/download/win") -or $missing

    $py = Get-Command python -ErrorAction SilentlyContinue
    $pyDetail = if ($py) { "$($py.Source) ($(python --version 2>&1))" } else { "not found" }
    $missing = (Write-Check "python" ([bool]$py) $pyDetail "https://www.python.org/downloads/windows/") -or $missing

    # The skill docs spell every command `python3`, which on Windows resolves to
    # the Microsoft Store stub -- it exits 9009 and prints nothing, so the whole
    # pipeline fails silently. Say so rather than letting it be discovered later.
    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    $python3Real = $false
    if ($python3) {
        python3 -c "pass" 2>$null | Out-Null
        $python3Real = ($LASTEXITCODE -eq 0)
    }
    if (-not $python3Real) {
        Write-Host ("  [warn] {0,-22} {1}" -f "python3", "not a working interpreter (Microsoft Store stub)") -ForegroundColor Yellow
        Write-Host "         note: run the skills' 'python3 ...' commands as 'python ...' on Windows" -ForegroundColor DarkGray
    } else {
        Write-Host ("  [ok]   {0,-22} {1}" -f "python3", $python3.Source) -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "report-slides -- PPTX export"
    $missing = (Write-Check "python-pptx" (Test-PythonModule "pptx") "PPTX export and structure validation" `
        "python -m pip install python-pptx") -or $missing
    $missing = (Write-Check "lxml" (Test-PythonModule "lxml") "SVG parsing" `
        "python -m pip install lxml") -or $missing
    Write-Check "Pillow" (Test-PythonModule "PIL") "raster fallbacks" `
        "python -m pip install Pillow" "optional" | Out-Null
    Write-Check "PyYAML" (Test-PythonModule "yaml") "threshold and token files" `
        "python -m pip install pyyaml" "optional" | Out-Null

    Write-Host ""
    Write-Host "report-slides -- visual review renderer (one of these is required)"
    # PowerPoint is checked first because on Windows it is both the faster and
    # the higher-fidelity renderer: it exports PNG directly, with no PDF hop.
    $ppt = $false
    $pptVersion = ""
    try {
        $app = New-Object -ComObject PowerPoint.Application
        $pptVersion = $app.Version
        $ppt = $true
        # Only quit an instance this check started, never the user's own.
        if ($app.Presentations.Count -eq 0) { $app.Quit() }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
    } catch {
        $ppt = $false
    }
    $pywin32 = Test-PythonModule "win32com.client"

    Write-Check "PowerPoint (COM)" $ppt $(if ($ppt) { "version $pptVersion -- native renderer available" } else { "not installed" }) `
        "install Microsoft Office, or use LibreOffice below" "optional" | Out-Null
    Write-Check "pywin32" $pywin32 "required to drive PowerPoint from Python" `
        "python -m pip install pywin32" "optional" | Out-Null

    $soffice = $null
    foreach ($candidate in @(
        (Get-Command soffice -ErrorAction SilentlyContinue).Source,
        "$env:ProgramFiles\LibreOffice\program\soffice.exe",
        "${env:ProgramFiles(x86)}\LibreOffice\program\soffice.exe"
    )) {
        if ($candidate -and (Test-Path $candidate)) { $soffice = $candidate; break }
    }
    Write-Check "LibreOffice" ([bool]$soffice) $(if ($soffice) { $soffice } else { "not installed" }) `
        "winget install TheDocumentFoundation.LibreOffice" "optional" | Out-Null
    Write-Check "pdftoppm (poppler)" ([bool](Get-Command pdftoppm -ErrorAction SilentlyContinue)) `
        "converts LibreOffice's PDF to per-slide PNG" `
        "winget install oschwartz10612.Poppler  (not needed if using PowerPoint)" "optional" | Out-Null

    if (-not ($ppt -and $pywin32) -and -not ($soffice -and (Get-Command pdftoppm -ErrorAction SilentlyContinue))) {
        Write-Host "  ! No complete renderer chain. The pptx_render gate will report 'blocked'" -ForegroundColor Red
        Write-Host "    and no deck can reach 'completed'. Install either:" -ForegroundColor Red
        Write-Host "      PowerPoint + pywin32   (recommended on Windows), or" -ForegroundColor Red
        Write-Host "      LibreOffice + poppler  (cross-platform)" -ForegroundColor Red
        $missing = $true
    }

    Write-Host ""
    Write-Host "report-slides -- diagrams"
    Write-Check "mmdc (mermaid-cli)" ([bool](Get-Command mmdc -ErrorAction SilentlyContinue)) `
        "Mermaid diagram slides; falls back to Claude-authored SVG when absent" `
        "npm install -g @mermaid-js/mermaid-cli" "optional" | Out-Null

    Write-Host ""
    if ($missing) {
        Write-Host "Required dependencies are missing -- see the fix lines above." -ForegroundColor Red
    } else {
        Write-Host "All required dependencies present." -ForegroundColor Green
    }
    Write-Host ""
}

if ($Doctor) {
    Invoke-Doctor
} elseif ($Uninstall) {
    Uninstall-Skills
} else {
    Install-Skills
}
