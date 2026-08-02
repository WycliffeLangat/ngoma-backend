# Runs the automated metadata-enrichment sweep headlessly via the Claude Code CLI.
# Invoked by a Windows Task Scheduler entry; safe to run manually too.
#
# bypassPermissions is required because nothing is present to answer permission
# prompts on an unattended schedule. The prompt file it runs is narrowly scoped
# (scripts/ and logs/ only, no git, no migrations) -- see research_prompt.txt.

$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $backendDir

$logDir = Join-Path $backendDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $logDir "auto_enrich_$stamp.log"

$promptPath = Join-Path $PSScriptRoot "research_prompt.txt"
$prompt = Get-Content -Raw -Path $promptPath

& claude -p $prompt `
    --permission-mode bypassPermissions `
    --allowed-tools "Bash,Read,Write,WebSearch" `
    --output-format text *> $logPath

Write-Output "Auto-enrich run finished. Log: $logPath"
