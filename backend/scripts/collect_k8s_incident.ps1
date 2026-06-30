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

function Sanitize-FilePart {
    Param([string]$Value)

    if (-not $Value) {
        return "unknown"
    }

    return ($Value -replace "[^a-zA-Z0-9._-]", "_")
}

function Ensure-Directory {
    Param([string]$Path)

    if (-not (Test-Path -Path $Path)) {
        New-Item -Path $Path -ItemType Directory -Force | Out-Null
    }
}

function Write-File {
    Param(
        [string]$Root,
        [string]$RelativePath,
        [string]$Content
    )

    $targetPath = Join-Path $Root $RelativePath
    $parent = Split-Path -Parent $targetPath
    Ensure-Directory -Path $parent
    Set-Content -Path $targetPath -Value $Content -Encoding UTF8
}

function Run-CommandCapture {
    Param(
        [string]$Root,
        [string]$RelativePath,
        [string]$Command,
        [string[]]$Args,
        [ref]$Warnings
    )

    $cmd = Get-Command $Command -ErrorAction SilentlyContinue
    if (-not $cmd) {
        $msg = "Command not found: $Command"
        Write-File -Root $Root -RelativePath $RelativePath -Content $msg
        $Warnings.Value += $msg
        return $false
    }

    $cmdText = "$Command $($Args -join ' ')".Trim()
    $started = Get-Date
    $output = & $Command @Args 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    $ended = Get-Date

    $header = @(
        "# Command",
        $cmdText,
        "",
        "# Started",
        $started.ToString("o"),
        "",
        "# Finished",
        $ended.ToString("o"),
        "",
        "# ExitCode",
        $exitCode,
        "",
        "# Output",
        ""
    ) -join [Environment]::NewLine

    Write-File -Root $Root -RelativePath $RelativePath -Content ($header + $output)

    if ($exitCode -ne 0) {
        $Warnings.Value += "Command failed (exit $exitCode): $cmdText"
        return $false
    }

    return $true
}

function Get-ProblemPods {
    Param(
        [object]$PodJson,
        [int]$MaxCount
    )

    $problems = @()
    foreach ($item in @($PodJson.items)) {
        $phase = [string]$item.status.phase
        $namespace = [string]$item.metadata.namespace
        $name = [string]$item.metadata.name

        $containerStatuses = @($item.status.containerStatuses)
        $restartTotal = 0
        $notReady = 0
        $reasonSet = New-Object 'System.Collections.Generic.HashSet[string]'

        foreach ($status in $containerStatuses) {
            $restartTotal += [int]$status.restartCount
            if (-not [bool]$status.ready) {
                $notReady += 1
            }
            if ($status.state.waiting.reason) {
                [void]$reasonSet.Add([string]$status.state.waiting.reason)
            }
            if ($status.state.terminated.reason) {
                [void]$reasonSet.Add([string]$status.state.terminated.reason)
            }
        }

        $isProblem = $false
        if ($phase -notin @("Running", "Succeeded")) {
            $isProblem = $true
        }
        if ($restartTotal -gt 0) {
            $isProblem = $true
        }
        if ($phase -eq "Running" -and $notReady -gt 0) {
            $isProblem = $true
        }

        if ($isProblem) {
            $reasons = ($reasonSet | Sort-Object) -join ","
            if (-not $reasons) {
                $reasons = "n/a"
            }

            $problems += [PSCustomObject]@{
                Namespace = $namespace
                Name = $name
                Phase = $phase
                RestartCount = $restartTotal
                NotReadyContainers = $notReady
                Reasons = $reasons
            }
        }
    }

    return $problems | Sort-Object -Property RestartCount -Descending | Select-Object -First $MaxCount
}

$repoRoot = Get-RepoRoot
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "artifacts/k8s-incidents"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$bundleDir = Join-Path $OutputRoot $timestamp
Ensure-Directory -Path $bundleDir

$warnings = @()

$kubectl = Get-Command kubectl -ErrorAction SilentlyContinue
if (-not $kubectl) {
    throw "kubectl is not installed or not on PATH."
}

$currentContext = (& kubectl config current-context 2>$null | Out-String).Trim()
if (-not $currentContext) {
    throw "No current kubectl context is set. Configure one first (for example: az aks get-credentials / aws eks update-kubeconfig / gcloud container clusters get-credentials)."
}

$namespaceLabel = if ($Namespace) { $Namespace } else { "all-namespaces" }
Write-Host "Collecting Kubernetes incident bundle for context '$currentContext' and scope '$namespaceLabel'..."

$baseScopeArgs = @("-A")
if ($Namespace) {
    $baseScopeArgs = @("-n", $Namespace)
}

Run-CommandCapture -Root $bundleDir -RelativePath "00-meta/kubectl-version.txt" -Command "kubectl" -Args @("version") -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "00-meta/current-context.txt" -Command "kubectl" -Args @("config", "current-context") -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "00-meta/cluster-info.txt" -Command "kubectl" -Args @("cluster-info") -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "00-meta/contexts.txt" -Command "kubectl" -Args @("config", "get-contexts") -Warnings ([ref]$warnings) | Out-Null

Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/nodes-wide.txt" -Command "kubectl" -Args @("get", "nodes", "-o", "wide") -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/namespaces.txt" -Command "kubectl" -Args @("get", "ns") -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/pods-wide.txt" -Command "kubectl" -Args (@("get", "pods") + $baseScopeArgs + @("-o", "wide")) -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/deployments.txt" -Command "kubectl" -Args (@("get", "deployments") + $baseScopeArgs + @("-o", "wide")) -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/statefulsets.txt" -Command "kubectl" -Args (@("get", "statefulsets") + $baseScopeArgs + @("-o", "wide")) -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/daemonsets.txt" -Command "kubectl" -Args (@("get", "daemonsets") + $baseScopeArgs + @("-o", "wide")) -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/services.txt" -Command "kubectl" -Args (@("get", "svc") + $baseScopeArgs + @("-o", "wide")) -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/ingress.txt" -Command "kubectl" -Args (@("get", "ingress") + $baseScopeArgs + @("-o", "wide")) -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/events.txt" -Command "kubectl" -Args (@("get", "events") + $baseScopeArgs + @("--sort-by=.metadata.creationTimestamp")) -Warnings ([ref]$warnings) | Out-Null

Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/top-nodes.txt" -Command "kubectl" -Args @("top", "nodes") -Warnings ([ref]$warnings) | Out-Null
Run-CommandCapture -Root $bundleDir -RelativePath "01-cluster/top-pods.txt" -Command "kubectl" -Args (@("top", "pods") + $baseScopeArgs) -Warnings ([ref]$warnings) | Out-Null

$podJsonPath = "02-workloads/pods.json"
$podJsonOk = Run-CommandCapture -Root $bundleDir -RelativePath $podJsonPath -Command "kubectl" -Args (@("get", "pods") + $baseScopeArgs + @("-o", "json")) -Warnings ([ref]$warnings)

$problemPods = @()
if ($podJsonOk) {
    $podRaw = & kubectl get pods @baseScopeArgs -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $podRaw) {
        $podObj = $podRaw | ConvertFrom-Json
        $problemPods = Get-ProblemPods -PodJson $podObj -MaxCount $MaxProblemPods
    }
}

if ($problemPods.Count -gt 0) {
    $problemCsv = $problemPods | ConvertTo-Csv -NoTypeInformation | Out-String
    Write-File -Root $bundleDir -RelativePath "02-workloads/problem-pods.csv" -Content $problemCsv

    foreach ($pod in $problemPods) {
        $ns = $pod.Namespace
        $name = $pod.Name
        $safeNs = Sanitize-FilePart -Value $ns
        $safeName = Sanitize-FilePart -Value $name

        Run-CommandCapture -Root $bundleDir -RelativePath "03-problem-pods/$safeNs-$safeName.describe.txt" -Command "kubectl" -Args @("describe", "pod", "-n", $ns, $name) -Warnings ([ref]$warnings) | Out-Null
        Run-CommandCapture -Root $bundleDir -RelativePath "03-problem-pods/$safeNs-$safeName.logs.txt" -Command "kubectl" -Args @("logs", "-n", $ns, $name, "--all-containers", "--tail", "$LogTail") -Warnings ([ref]$warnings) | Out-Null

        if ($IncludePreviousLogs) {
            Run-CommandCapture -Root $bundleDir -RelativePath "03-problem-pods/$safeNs-$safeName.logs-previous.txt" -Command "kubectl" -Args @("logs", "-n", $ns, $name, "--all-containers", "--previous", "--tail", "$LogTail") -Warnings ([ref]$warnings) | Out-Null
        }
    }
}

$summary = @()
$summary += "# Kubernetes Incident Bundle"
$summary += ""
$summary += "- GeneratedAt: $(Get-Date -Format o)"
$summary += "- Context: $currentContext"
$summary += "- Scope: $namespaceLabel"
$summary += "- OutputDirectory: $bundleDir"
$summary += "- ProblemPodsCaptured: $($problemPods.Count)"
$summary += ""

if ($problemPods.Count -gt 0) {
    $summary += "## Problem Pods"
    foreach ($pod in $problemPods) {
        $summary += "- $($pod.Namespace)/$($pod.Name) phase=$($pod.Phase) restarts=$($pod.RestartCount) notReady=$($pod.NotReadyContainers) reasons=$($pod.Reasons)"
    }
    $summary += ""
}

if ($warnings.Count -gt 0) {
    $summary += "## Warnings"
    foreach ($warning in $warnings) {
        $summary += "- $warning"
    }
    $summary += ""
}

$summary += "## Suggested Next Step"
$summary += "Run this command to review bundle contents quickly:"
$summary += ""
$summary += "Get-ChildItem -Recurse '$bundleDir'"

Write-File -Root $bundleDir -RelativePath "SUMMARY.md" -Content ($summary -join [Environment]::NewLine)

$zipPath = ""
if ($CreateZip) {
    $zipPath = "$bundleDir.zip"
    if (Test-Path $zipPath) {
        Remove-Item -Path $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $bundleDir "*") -DestinationPath $zipPath
}

Write-Host "Incident bundle complete: $bundleDir"
if ($zipPath) {
    Write-Host "Incident bundle zip: $zipPath"
}
if ($warnings.Count -gt 0) {
    Write-Host "Completed with warnings. See SUMMARY.md for details."
}
