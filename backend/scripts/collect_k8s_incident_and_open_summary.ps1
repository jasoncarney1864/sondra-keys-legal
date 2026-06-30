Param(
    [string]$Namespace = "",
    [string]$OutputRoot = "",
    [int]$MaxProblemPods = 20,
    [int]$LogTail = 300,
    [bool]$IncludePreviousLogs = $true,
    [bool]$CreateZip = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    $scriptDir = $PSScriptRoot
    $backendDir = Split-Path -Parent $scriptDir
    return Split-Path -Parent $backendDir
}

function Resolve-OutputRoot {
    Param([string]$ConfiguredRoot)

    if ($ConfiguredRoot) {
        return $ConfiguredRoot
    }

    $repoRoot = Get-RepoRoot
    return Join-Path $repoRoot "artifacts/k8s-incidents"
}

$collectorScript = Join-Path $PSScriptRoot "collect_k8s_incident.ps1"
if (-not (Test-Path -Path $collectorScript)) {
    throw "Required script not found: $collectorScript"
}

$resolvedOutputRoot = Resolve-OutputRoot -ConfiguredRoot $OutputRoot
$existingDirectories = @{}
if (Test-Path -Path $resolvedOutputRoot) {
    foreach ($dir in Get-ChildItem -Path $resolvedOutputRoot -Directory) {
        $existingDirectories[$dir.FullName] = $true
    }
}

& $collectorScript `
    -Namespace $Namespace `
    -OutputRoot $OutputRoot `
    -MaxProblemPods $MaxProblemPods `
    -LogTail $LogTail `
    -IncludePreviousLogs:$IncludePreviousLogs `
    -CreateZip:$CreateZip

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if (-not (Test-Path -Path $resolvedOutputRoot)) {
    throw "Output root does not exist after collection: $resolvedOutputRoot"
}

$allDirectories = Get-ChildItem -Path $resolvedOutputRoot -Directory | Sort-Object LastWriteTimeUtc -Descending
if ($allDirectories.Count -eq 0) {
    throw "No incident bundle directory found under: $resolvedOutputRoot"
}

$newDirectory = $allDirectories | Where-Object { -not $existingDirectories.ContainsKey($_.FullName) } | Select-Object -First 1
if (-not $newDirectory) {
    $newDirectory = $allDirectories | Select-Object -First 1
}

$summaryPath = Join-Path $newDirectory.FullName "SUMMARY.md"
if (-not (Test-Path -Path $summaryPath)) {
    throw "Summary file was not found: $summaryPath"
}

Write-Host "Opening summary: $summaryPath"
$codeCmd = Get-Command code -ErrorAction SilentlyContinue
if ($codeCmd) {
    & $codeCmd.Source -r $summaryPath | Out-Null
} else {
    Invoke-Item -Path $summaryPath
}
