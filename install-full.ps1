# Claude Context Sync Extended - Full sync installer for Windows (PowerShell)
# Usage:
#   irm https://raw.githubusercontent.com/shaike1/claude-sync/main/install-full.ps1 -OutFile install-full.ps1
#   .\install-full.ps1 -Repo https://github.com/YOUR_USERNAME/YOUR_REPO [-Level essential|full]

param(
    [string]$Repo = "",
    [ValidateSet("essential", "full")]
    [string]$Level = "essential",
    [string]$ScriptUrl = "https://raw.githubusercontent.com/shaike1/claude-sync/main/claude-sync-extended.py"
)

$ErrorActionPreference = "Stop"

function Write-Utf8File([string]$Path, [string]$Content) {
    # Windows PowerShell 5.1 adds a BOM with -Encoding UTF8, which breaks command front matter
    [System.IO.File]::WriteAllText($Path, $Content, (New-Object System.Text.UTF8Encoding($false)))
}

Write-Host "Claude Context Sync Extended Installer (Windows)" -ForegroundColor Cyan
Write-Host "================================================"

if (-not $Repo) {
    $Repo = Read-Host "Enter your GitHub repository URL"
}

if ($Repo -notmatch '^https://github\.com/[^/]+/[^/]+(\.git)?$') {
    Write-Host "Invalid GitHub repository URL" -ForegroundColor Red
    exit 1
}
if ($Repo -notmatch '\.git$') {
    $Repo = "$Repo.git"
}

# Find a real Python 3 (the Microsoft Store 'python' stub exits non-zero)
$python = $null
$pythonArgs = @()
foreach ($candidate in @(@("python"), @("py", "-3"))) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $extra = @($candidate | Select-Object -Skip 1)
    $version = & $candidate[0] @extra --version 2>$null
    if ($LASTEXITCODE -eq 0 -and "$version" -match "^Python 3") {
        $python = $candidate[0]
        $pythonArgs = $extra
        break
    }
}
if (-not $python) {
    Write-Host "Python 3 was not found. Install it from https://www.python.org/downloads/ and run this again." -ForegroundColor Red
    exit 1
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git was not found. Install it from https://git-scm.com/download/win and run this again." -ForegroundColor Red
    exit 1
}

Write-Host "Installing Claude Context Sync Extended..." -ForegroundColor Cyan
Write-Host "Repository: $Repo"
Write-Host "Sync level: $Level"
Write-Host "Python:     $python $($pythonArgs -join ' ')"

$home_dir = $env:USERPROFILE
$commands = Join-Path $home_dir ".claude\commands"
$syncScript = Join-Path $home_dir "claude-sync-extended.py"
New-Item -ItemType Directory -Force $commands | Out-Null
New-Item -ItemType Directory -Force (Join-Path $home_dir ".claude-sync") | Out-Null

Write-Host "Downloading claude-sync-extended.py..."
Invoke-WebRequest -UseBasicParsing -Uri $ScriptUrl -OutFile $syncScript

# Slash commands live in ~/.claude/commands, one markdown file per command
Write-Host "Creating slash commands..."
$run = (@($python) + $pythonArgs + "`"`$HOME/claude-sync-extended.py`"") -join " "
$definitions = @{
    "sync-pull"      = @("Pull Claude context from remote (essential data only).", "pull")
    "sync-push"      = @("Push Claude context to remote (essential data only).", "push")
    "sync-pull-full" = @("Pull ALL Claude data from remote (sessions, settings, todos).", "pull")
    "sync-push-full" = @("Push ALL Claude data to remote for other PCs to access.", "push")
    "sync-full"      = @("Perform a complete bidirectional sync of ALL Claude data.", "sync")
    "sync-status"    = @("Show Claude Context Sync status and what will be synced.", "status")
}
foreach ($name in $definitions.Keys) {
    $description, $action = $definitions[$name]
    $body = "---`ndescription: $description`nallowed-tools: Bash(python:*), Bash(py:*)`n---`nResult of the sync, report it briefly:`n`n!``$run $action```n"
    Write-Utf8File (Join-Path $commands "$name.md") $body
}

Write-Host "Configuring with repository and sync level..." -ForegroundColor Cyan
& $python @pythonArgs $syncScript setup --git-repo $Repo --level $Level

Write-Host "`nCurrent sync configuration:" -ForegroundColor Cyan
& $python @pythonArgs $syncScript status

# The script exits 0 even when a sync fails, so look for its success message
Write-Host "`nAttempting initial sync..." -ForegroundColor Cyan
$ErrorActionPreference = "Continue"
$output = & $python @pythonArgs $syncScript push 2>&1 | Out-String
$ErrorActionPreference = "Stop"
if ($output -match "Push completed") {
    Write-Host "Initial sync successful" -ForegroundColor Green
} else {
    Write-Host "Initial sync skipped (repository might be empty or not reachable yet)" -ForegroundColor Yellow
}

Write-Host "`nClaude Context Sync Extended installed!" -ForegroundColor Green
Write-Host @"

Available commands (restart Claude Code to see them):
  /sync-pull, /sync-push   - essential data
  /sync-pull-full, /sync-push-full, /sync-full - all Claude data
  /sync-status             - show what will be synced

Quick start:
  1. Run /sync-push-full to upload your current Claude setup
  2. On your other PCs, run this installer with the same repository, then /sync-pull-full
"@
