Param(
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    $scriptDir = $PSScriptRoot
    $backendDir = Split-Path -Parent $scriptDir
    return Split-Path -Parent $backendDir
}

function Get-EnvValue {
    Param(
        [string]$FilePath,
        [string]$Name
    )

    if (-not (Test-Path $FilePath)) {
        return ""
    }

    $line = Get-Content -Path $FilePath |
        Where-Object { $_ -and -not $_.TrimStart().StartsWith("#") } |
        Where-Object { $_ -match "^\s*$Name\s*=" } |
        Select-Object -First 1

    if (-not $line) {
        return ""
    }

    $value = ($line -split "=", 2)[1].Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"')) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    if ($value.StartsWith("'") -and $value.EndsWith("'")) {
        $value = $value.Substring(1, $value.Length - 2)
    }

    return $value
}

function Resolve-BackendSetting {
    Param(
        [string]$Name,
        [string[]]$EnvFiles
    )

    foreach ($file in $EnvFiles) {
        $fileValue = Get-EnvValue -FilePath $file -Name $Name
        if ($fileValue) {
            return $fileValue
        }
    }

    $processValue = [System.Environment]::GetEnvironmentVariable($Name, "Process")
    if ($processValue) {
        return $processValue
    }

    return ""
}

function Test-IsPlaceholderValue {
    Param(
        [string]$Name,
        [string]$Value
    )

    if (-not $Value) {
        return $true
    }

    $v = $Value.Trim().ToLowerInvariant()
    if ($v -match "^test[-_]" -or $v -match "^example" -or $v -like "*your-*" -or $v -like "*placeholder*") {
        return $true
    }

    if ($Name -eq "AZURE_CONTENT_UNDERSTANDING_ENDPOINT" -and $v -like "*example.cognitiveservices.azure.com*") {
        return $true
    }
    if ($Name -eq "AI_OPENAI_ENDPOINT" -and $v -like "*example.openai.azure.com*") {
        return $true
    }

    return $false
}

function Resolve-PythonExe {
    Param([string]$Requested)

    if ($Requested -and (Test-Path $Requested)) {
        return $Requested
    }

    $preferred = "C:/Python314/python.exe"
    if (Test-Path $preferred) {
        return $preferred
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return $pythonCmd.Source
    }

    throw "Unable to find a Python executable. Pass -PythonExe with an absolute path."
}

$repoRoot = Get-RepoRoot
$frontendDir = Join-Path $repoRoot "frontend"
$frontendEnvFile = Join-Path $frontendDir ".env.local"
$backendEnvFiles = @(
    (Join-Path $repoRoot "backend/.env.local"),
    (Join-Path $repoRoot "backend/.env")
)

$apiKey = Get-EnvValue -FilePath $frontendEnvFile -Name "VITE_API_KEY"
if (-not $apiKey) {
    throw "Could not read VITE_API_KEY from frontend/.env.local."
}

$python = Resolve-PythonExe -Requested $PythonExe

$requiredBackendVars = @(
    "AZURE_CONTENT_UNDERSTANDING_ENDPOINT",
    "AZURE_CONTENT_UNDERSTANDING_KEY",
    "AZURE_SEARCH_SERVICE_NAME",
    "AZURE_SEARCH_API_KEY",
    "AZURE_BLOB_ACCOUNT_NAME",
    "AZURE_BLOB_ACCOUNT_KEY",
    "AI_OPENAI_API_KEY",
    "AI_OPENAI_ENDPOINT",
    "AI_OPENAI_DEPLOYMENT_NAME",
    "OPENAI_API_KEY"
)

$resolvedBackend = @{}
$missingVars = @()
foreach ($name in $requiredBackendVars) {
    $resolved = Resolve-BackendSetting -Name $name -EnvFiles $backendEnvFiles
    if (-not $resolved) {
        $missingVars += $name
        continue
    }
    if (Test-IsPlaceholderValue -Name $name -Value $resolved) {
        $missingVars += $name
        continue
    }

    $resolvedBackend[$name] = $resolved
}

if ($missingVars.Count -gt 0) {
    $missing = $missingVars -join ", "
    throw "Missing backend environment values: $missing. Set them in process env or backend/.env.local before running this script."
}

$backendEnv = @{
    "PYTHONPATH"                              = "."
    "SECURITY_API_KEY"                        = $apiKey
    "DB_DATABASE_URL"                         = (Resolve-BackendSetting -Name "DB_DATABASE_URL" -EnvFiles $backendEnvFiles)
    "STARTUP_INDEX_SANITY_CHECK_ENABLED"      = (Resolve-BackendSetting -Name "STARTUP_INDEX_SANITY_CHECK_ENABLED" -EnvFiles $backendEnvFiles)
    "USER_SESSION_RETENTION_CLEANUP_ENABLED"  = (Resolve-BackendSetting -Name "USER_SESSION_RETENTION_CLEANUP_ENABLED" -EnvFiles $backendEnvFiles)
    "PARSED_JSON_RETENTION_CLEANUP_ENABLED"   = (Resolve-BackendSetting -Name "PARSED_JSON_RETENTION_CLEANUP_ENABLED" -EnvFiles $backendEnvFiles)
}

foreach ($name in $requiredBackendVars) {
    $backendEnv[$name] = $resolvedBackend[$name]
}

if (-not $backendEnv["DB_DATABASE_URL"]) {
    $backendEnv["DB_DATABASE_URL"] = "sqlite+aiosqlite:///./backend/legal_qa_local.db"
}
if (-not $backendEnv["STARTUP_INDEX_SANITY_CHECK_ENABLED"]) {
    $backendEnv["STARTUP_INDEX_SANITY_CHECK_ENABLED"] = "false"
}
if (-not $backendEnv["USER_SESSION_RETENTION_CLEANUP_ENABLED"]) {
    $backendEnv["USER_SESSION_RETENTION_CLEANUP_ENABLED"] = "false"
}
if (-not $backendEnv["PARSED_JSON_RETENTION_CLEANUP_ENABLED"]) {
    $backendEnv["PARSED_JSON_RETENTION_CLEANUP_ENABLED"] = "false"
}

Write-Host "Starting frontend dev server in a separate terminal window..."
$frontendCmd = "Set-Location '$frontendDir'; npm run dev -- --host 0.0.0.0 --port 5173"
Start-Process pwsh -ArgumentList @("-NoExit", "-Command", $frontendCmd) | Out-Null

Set-Location $repoRoot
foreach ($key in $backendEnv.Keys) {
    [System.Environment]::SetEnvironmentVariable($key, $backendEnv[$key], "Process")
}

Write-Host "Starting backend API at http://localhost:8000 ..."
& $python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000