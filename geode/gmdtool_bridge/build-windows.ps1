# PowerShell, run in the directory containing mod.json.
# Requirements: Geode CLI, Geode SDK + prebuilt Win64 binaries,
# Visual Studio Build Tools / Windows SDK, LLVM Clang, Ninja, CMake.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command geode -ErrorAction SilentlyContinue)) {
    throw 'Geode CLI not found. See https://docs.geode-sdk.org/getting-started/geode-cli/'
}
if (-not $env:GEODE_SDK) {
    throw 'GEODE_SDK is missing. Run: geode sdk install; geode sdk install-binaries'
}
& geode build --ninja
if ($LASTEXITCODE -ne 0) { throw "Geode build failed with exit code $LASTEXITCODE" }
$mods = @(Get-ChildItem -Recurse -File -Filter '*.geode' | Sort-Object LastWriteTime -Descending)
if ($mods.Count -eq 0) { throw 'Build finished without .geode output; check build logs.' }
Write-Host "Built package: $($mods[0].FullName)"
