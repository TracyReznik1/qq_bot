$ErrorActionPreference = "Stop"

$appName = "ATRIQQBot"
$version = "0.1.0"
$releaseDir = "release\${appName}-${version}-win-x64"

Write-Host "Generating QUICK_START.txt..."
$quickStart = @"
ATRI QQBot Manager - Quick Start Guide

1. Double click ATRIQQBot.exe to start the manager.
2. In the Settings page, configure your API keys (DeepSeek, Gemini, etc.).
3. In the NapCat & QQ page, select the path to your installed NapCat executable.
4. Click 'Open NapCat WebUI' to configure QQ login and OneBot API settings (default http://127.0.0.1:3000).
5. Go to the Dashboard page and click 'Start Bot' to launch the core process.
6. NapCat and QQ are NOT included in this distribution and must be installed independently.
7. API Keys are securely stored in the Windows Credential Manager.
8. User data (memories, backups, settings) is located at %LOCALAPPDATA%\ATRIQQBot.
9. This application is not digitally signed. Windows SmartScreen may show a warning upon first launch.
"@
Set-Content -Path "$releaseDir\QUICK_START.txt" -Value $quickStart -Encoding UTF8

Write-Host "Generating BUILD_INFO.json..."
$commitHash = git rev-parse --short HEAD
$buildDate = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$pyVersion = python -c "import sys; print(sys.version.split()[0])"
$psVersion = python -c "import PySide6; print(PySide6.__version__)"

$buildInfo = @"
{
    "app_name": "$appName",
    "version": "$version",
    "git_commit": "$commitHash",
    "build_date": "$buildDate",
    "python_version": "$pyVersion",
    "pyside6_version": "$psVersion",
    "build_tool": "pyside6-deploy (Nuitka standalone)",
    "target_platform": "Windows x64"
}
"@
Set-Content -Path "$releaseDir\BUILD_INFO.json" -Value $buildInfo -Encoding UTF8

Write-Host "Generating THIRD_PARTY_LICENSES.txt..."
$licenses = @"
ATRI QQBot Manager includes or depends on the following major third-party open source software:

- PySide6 (Qt for Python): LGPLv3
- Nuitka: Apache License 2.0
- Flask: BSD-3-Clause
- requests: Apache License 2.0
- keyring: MIT License
- python-dotenv: BSD-3-Clause

NapCat is NOT included in this distribution.
"@
Set-Content -Path "$releaseDir\THIRD_PARTY_LICENSES.txt" -Value $licenses -Encoding UTF8

Write-Host "Generating SHA256SUMS.txt..."
Set-Location -Path $releaseDir
$filesToHash = @("ATRIQQBot.exe", "BUILD_INFO.json", "QUICK_START.txt", "THIRD_PARTY_LICENSES.txt")
$hashList = @()
foreach ($file in $filesToHash) {
    if (Test-Path $file) {
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash
        $hashList += "$hash *$file"
    }
}
$hashList | Set-Content -Path "SHA256SUMS.txt" -Encoding ASCII
Set-Location -Path ..\..

Write-Host "Creating ZIP..."
$zipPath = "release\${appName}-${version}-win-x64.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath }
Compress-Archive -Path $releaseDir -DestinationPath $zipPath

Write-Host "Done!"
