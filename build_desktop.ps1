$ErrorActionPreference = "Stop"

Write-Host "1. Running compileall..."
python -m compileall launcher.py desktop_app src
if ($LASTEXITCODE -ne 0) { throw "Compile check failed" }

Write-Host "2. Running unit tests..."
python -m unittest discover -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed" }

Write-Host "3. Running GUI smoke test..."
$env:QT_QPA_PLATFORM="offscreen"
python smoke_test.py
$smokeExit = $LASTEXITCODE
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
if ($smokeExit -ne 0) { throw "GUI smoke test failed" }

Write-Host "4. Cleaning up old builds..."
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

Write-Host "5. Running pyside6-deploy..."
# Running pyside6-deploy to generate the standalone build
pyside6-deploy -c pysidedeploy.spec -f
if ($LASTEXITCODE -ne 0) { throw "Deployment failed" }

Write-Host "6. Organizing release folder..."
$appName = "ATRIQQBot"
$version = "0.1.12"
$releaseDir = "release\${appName}-${version}-win-x64"

New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
Copy-Item -Recurse -Force "${appName}.dist\*" $releaseDir\

if (Test-Path "$releaseDir\launcher.exe") {
    if (Test-Path "$releaseDir\${appName}.exe") {
        Remove-Item "$releaseDir\${appName}.exe" -Force
    }
    Rename-Item "$releaseDir\launcher.exe" "${appName}.exe" -Force
}

Write-Host "7. Verifying EXEs..."
if (-not (Test-Path "$releaseDir\${appName}.exe")) {
    throw "Executable ${appName}.exe not found in $releaseDir"
}

Write-Host "Build complete: $releaseDir"
