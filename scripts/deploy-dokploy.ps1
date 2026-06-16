#!/usr/bin/env pwsh
# Deploy DayZ Map to Dokploy via API
# Usage: $env:DOKPLOY_API_KEY="your-key"; pwsh scripts/deploy-dokploy.ps1

$ErrorActionPreference = "Stop"
$BaseUrl = "https://panel.gto-team.uz/api"
$Headers = @{
    "x-api-key" = $env:DOKPLOY_API_KEY
    "Content-Type" = "application/json"
    "accept" = "application/json"
}

if (-not $env:DOKPLOY_API_KEY) {
    Write-Error "Set DOKPLOY_API_KEY environment variable"
}

$SecretKey = if ($env:SECRET_KEY) { $env:SECRET_KEY } else { [Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 })) }

$EnvBlock = @"
SECRET_KEY=$SecretKey
SERVER_PUBLIC_URL=https://dayz-map.gto-team.uz
MAP_MIN_X=0
MAP_MAX_X=15360
MAP_MIN_Y=0
MAP_MAX_Y=15360
CLIENT_DOWNLOAD_URL=https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/latest/download/DayZMapClient.exe
"@

function Invoke-Dokploy($Endpoint, $Body) {
    $json = if ($Body) { $Body | ConvertTo-Json -Depth 10 -Compress } else { $null }
    return Invoke-RestMethod -Uri "$BaseUrl/$Endpoint" -Headers $Headers -Method POST -Body $json
}

Write-Host "Creating project..."
$project = Invoke-Dokploy "project.create" @{ name = "DayZ Map"; description = "DayZ Pripyat live map" }
$envId = $project.environment.environmentId
Write-Host "Environment: $envId"

Write-Host "Creating compose service..."
$compose = Invoke-Dokploy "compose.create" @{
    name = "dayz-map"
    description = "DayZ Pripyat OCR map server"
    environmentId = $envId
    composeType = "docker-compose"
}
$composeId = $compose.composeId
Write-Host "Compose: $composeId"

Write-Host "Configuring GitHub source..."
Invoke-Dokploy "compose.update" @{
    composeId = $composeId
    sourceType = "github"
    githubId = "ut66ZuBeQJ8g5KWGsccbf"
    owner = "Ignor-GTO"
    repository = "dayz-map-and-client-soft"
    branch = "main"
    composePath = "./docker-compose.yml"
    env = $EnvBlock
    autoDeploy = $true
    isolatedDeployment = $true
} | Out-Null

Write-Host "Creating domain..."
Invoke-Dokploy "domain.create" @{
    host = "dayz-map.gto-team.uz"
    https = $true
    port = 8000
    composeId = $composeId
    serviceName = "dayz-map"
    certificateType = "letsencrypt"
} | Out-Null

Write-Host "Deploying..."
Invoke-Dokploy "compose.deploy" @{
    composeId = $composeId
    title = "Initial deploy"
    description = "DayZ map MVP"
} | Out-Null

Write-Host "Done. Check https://panel.gto-team.uz and https://dayz-map.gto-team.uz"
Write-Host "SECRET_KEY saved in Dokploy compose env (not shown again)"
