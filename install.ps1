<#
.SYNOPSIS
    research-lab-skills installer (Windows PowerShell / PowerShell 7+)

.DESCRIPTION
    Native Windows counterpart to install.sh. Clones the repo and copies the
    requested skill directories into ~/.claude/skills (or a project-local
    .claude/skills when -Local is passed).

.EXAMPLE
    # All skills, global install
    irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1 | iex

.EXAMPLE
    # Flags require the script text, not a piped invocation, so download it
    # into a scriptblock first:
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -Local
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -ArsOnly
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -LabOnly
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1))) -Uninstall

.EXAMPLE
    # From cmd.exe, wrap the same command with powershell -Command
    powershell -Command "irm https://raw.githubusercontent.com/starpig1129/research-lab-skills/main/install.ps1 | iex"
#>

param(
    [switch]$Local,
    [switch]$ArsOnly,
    [switch]$LabOnly,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$Repo = "https://github.com/starpig1129/research-lab-skills.git"

# Lab skills (experiment journal + presentations + mode routing)
$LabSkills = @("research-log", "report-slides", "research-mode")
# Academic Research Skills (deep research, paper writing, review, pipeline)
$ArsSkills = @("deep-research", "academic-paper", "academic-paper-reviewer", "academic-pipeline")

$Skills = $LabSkills + $ArsSkills
if ($ArsOnly) { $Skills = $ArsSkills }
if ($LabOnly) { $Skills = $LabSkills }

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
    foreach ($skill in $Skills) {
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

if ($Uninstall) {
    Uninstall-Skills
} else {
    Install-Skills
}
