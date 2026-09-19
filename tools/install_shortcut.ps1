# Put umbra in the Start menu, the way opencode gets there: a .lnk in
# %APPDATA%\Microsoft\Windows\Start Menu\Programs that opens a console
# running the installed `umbra` command.
#
#   powershell -ExecutionPolicy Bypass -File tools\install_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_shortcut.ps1 -StartIn "C:\code"
#
param(
    [string]$StartIn = (Join-Path $env:USERPROFILE "Downloads\Projects"),
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$repo     = Split-Path -Parent $PSScriptRoot
$appDir   = Join-Path $env:LOCALAPPDATA "Programs\umbra"
$iconPath = Join-Path $appDir "umbra.ico"
$startDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$lnkPath  = Join-Path $startDir "Umbra.lnk"

if ($Uninstall) {
    Remove-Item $lnkPath -ErrorAction SilentlyContinue
    Remove-Item $appDir -Recurse -ErrorAction SilentlyContinue
    Write-Host "removed $lnkPath"
    return
}

$exe = (Get-Command umbra -ErrorAction SilentlyContinue).Source
if (-not $exe) {
    throw "umbra is not on PATH - run 'pip install -e .' in $repo first"
}

# The icon lives outside the repo so moving the source folder doesn't break it.
if (-not (Test-Path $appDir)) { New-Item -ItemType Directory -Path $appDir | Out-Null }
$srcIcon = Join-Path $repo "assets\umbra.ico"
if (Test-Path $srcIcon) { Copy-Item $srcIcon $iconPath -Force }

if (-not (Test-Path $StartIn)) { $StartIn = $env:USERPROFILE }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath       = "$env:SystemRoot\System32\cmd.exe"
# `|| pause` keeps a crash on screen instead of closing the window instantly.
$lnk.Arguments        = '/c "' + $exe + ' || pause"'
$lnk.WorkingDirectory = $StartIn
$lnk.Description      = "umbra - local coding agent"
if (Test-Path $iconPath) { $lnk.IconLocation = "$iconPath,0" }
$lnk.WindowStyle      = 1
$lnk.Save()

Write-Host "installed $lnkPath"
Write-Host "  runs      : $exe"
Write-Host "  starts in : $StartIn"
Write-Host "  icon      : $iconPath"
