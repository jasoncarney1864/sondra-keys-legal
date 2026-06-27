[CmdletBinding()]
param(
    [string]$ContainerName = "sondra-api-test",
    [string]$SearchServiceName,
    [string]$IndexName,
    [string]$ApiKey,
    [string[]]$DeleteDocumentIds = @(),
    [string]$RenameDocumentId,
    [string]$RenameFileName,
    [switch]$ListOnly,
    [switch]$WhatIf
)

$ErrorActionPreference = "Stop"

function Get-ContainerEnv {
    param([string]$Name)

    try {
        $rawEnv = docker inspect $Name --format '{{range .Config.Env}}{{println .}}{{end}}' 2>$null
        if (-not $rawEnv) {
            return @{}
        }

        $envMap = @{}
        foreach ($entry in $rawEnv) {
            if ($entry -match '^[^=]+=') {
                $parts = $entry.Split('=', 2)
                $envMap[$parts[0]] = $parts[1]
            }
        }
        return $envMap
    }
    catch {
        return @{}
    }
}

$containerEnv = Get-ContainerEnv -Name $ContainerName
if (-not $SearchServiceName) { $SearchServiceName = $containerEnv["AZURE_SEARCH_SERVICE_NAME"] }
if (-not $IndexName) { $IndexName = $containerEnv["AZURE_SEARCH_INDEX_NAME"] }
if (-not $ApiKey) { $ApiKey = $containerEnv["AZURE_SEARCH_API_KEY"] }

if (-not $SearchServiceName -or -not $IndexName -or -not $ApiKey) {
    throw (
        "Missing search configuration. Provide -SearchServiceName, -IndexName, " +
        "and -ApiKey, or run with a container that has AZURE_SEARCH_* env vars."
    )
}

if (($RenameDocumentId -and -not $RenameFileName) -or (-not $RenameDocumentId -and $RenameFileName)) {
    throw "Use -RenameDocumentId and -RenameFileName together."
}

$headers = @{ "api-key" = $ApiKey; "Content-Type" = "application/json" }
$base = "https://$SearchServiceName.search.windows.net/indexes/$IndexName/docs"

$searchBody = @{ search = "*"; select = "id,document_id,file_name"; top = 1000 } | ConvertTo-Json -Depth 4 -Compress
$allDocs = @(
    (Invoke-RestMethod -Uri "$base/search?api-version=2023-11-01" -Method Post -Headers $headers -Body $searchBody).value
)

Write-Host "Current index entries: $($allDocs.Count)"
if ($allDocs.Count -gt 0) {
    $allDocs | Select-Object id, document_id, file_name | Format-Table -AutoSize
}

if ($ListOnly) {
    return
}

$actions = @()

if ($RenameDocumentId) {
    foreach ($doc in $allDocs) {
        if ($doc.document_id -eq $RenameDocumentId) {
            $actions += @{
                "@search.action" = "merge"
                id = $doc.id
                file_name = $RenameFileName
            }
        }
    }
}

if ($DeleteDocumentIds.Count -gt 0) {
    foreach ($doc in $allDocs) {
        if ($DeleteDocumentIds -contains $doc.document_id) {
            $actions += @{
                "@search.action" = "delete"
                id = $doc.id
            }
        }
    }
}

if ($actions.Count -eq 0) {
    Write-Host "No matching documents found for requested actions."
    return
}

Write-Host "Prepared actions: $($actions.Count)"
if ($WhatIf) {
    $actions | Format-Table -AutoSize
    return
}

$payload = @{ value = $actions } | ConvertTo-Json -Depth 6 -Compress
$result = Invoke-RestMethod -Uri "$base/index?api-version=2023-11-01" -Method Post -Headers $headers -Body $payload

Write-Host "`nApplied actions:"
$result.value | Select-Object key, status, statusCode, errorMessage | Format-Table -AutoSize

$afterDocs = @(
    (Invoke-RestMethod -Uri "$base/search?api-version=2023-11-01" -Method Post -Headers $headers -Body $searchBody).value
)

Write-Host "`nIndex entries after update: $($afterDocs.Count)"
if ($afterDocs.Count -gt 0) {
    $afterDocs | Select-Object id, document_id, file_name | Format-Table -AutoSize
}
