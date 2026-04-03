<#
.SYNOPSIS
  Build the app image, push to Azure Container Registry, roll a new Container App revision.
  Same flow as .github/workflows/deploy-azure-containerapps.yml (local machine instead of CI).

.DESCRIPTION
  Requires: Docker Desktop (or Docker Engine), Azure CLI, and `az login`.
  Needs permission to: AcrPush on the registry, and to update the Container App (e.g. Contributor on the RG).

.EXAMPLE
  .\scripts\deploy-acr-containerapp.ps1 -AcrName myregistry -ResourceGroup my-rg -ContainerAppName my-app

.EXAMPLE
  $env:AZURE_ACR_NAME = "myregistry"; $env:AZURE_RESOURCE_GROUP = "my-rg"; $env:AZURE_CONTAINERAPP_NAME = "my-app"
  .\scripts\deploy-acr-containerapp.ps1
#>
[CmdletBinding()]
param(
    [string] $AcrName = $env:AZURE_ACR_NAME,
    [string] $ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    [string] $ContainerAppName = $env:AZURE_CONTAINERAPP_NAME,
    [string] $ImageName = "voice-navigator",
    [string] $Tag = ""
)

$ErrorActionPreference = "Stop"

if (-not $AcrName -or -not $ResourceGroup -or -not $ContainerAppName) {
    Write-Error @"
Set Azure targets via parameters or environment variables (same names as GitHub repo Variables):

  -AcrName           or  `$env:AZURE_ACR_NAME
  -ResourceGroup     or  `$env:AZURE_RESOURCE_GROUP
  -ContainerAppName  or  `$env:AZURE_CONTAINERAPP_NAME
"@
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $Tag) {
    $Tag = (& git -C $repoRoot rev-parse --short HEAD 2>$null).Trim()
    if (-not $Tag) {
        $Tag = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    }
}
$registry = "$AcrName.azurecr.io"
$imageRef = "$registry/${ImageName}:$Tag"
$latestRef = "$registry/${ImageName}:latest"

& az account show 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Azure CLI not logged in. Run: az login"
}

Write-Host "Registry: $registry"
Write-Host "Image:    $imageRef (+ :latest)"
Write-Host ""

Write-Host "[1/4] ACR login..."
& az acr login --name $AcrName
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location $repoRoot
try {
    Write-Host "[2/4] docker build..."
    & docker build -t $imageRef -t $latestRef .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "[3/4] docker push..."
    & docker push $imageRef
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & docker push $latestRef
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host "[4/4] containerapp update..."
& az containerapp update `
    --name $ContainerAppName `
    --resource-group $ResourceGroup `
    --image $imageRef
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done. Container App should pull: $imageRef"
