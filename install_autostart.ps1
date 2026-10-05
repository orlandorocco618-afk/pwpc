# Registers pwpc to start automatically at every Windows sign-in,
# by creating a shortcut in shell:startup that runs lock_screen.py with pythonw.exe
# (no console window).

$scriptDir = $PSScriptRoot
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($python) { $pythonw = Join-Path (Split-Path $python) "pythonw.exe" }
}
if (-not $pythonw -or -not (Test-Path $pythonw)) {
    Write-Error "pythonw.exe not found: install Python 3.10+ and add it to PATH."
    exit 1
}

$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "pwpc.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + (Join-Path $scriptDir "lock_screen.py") + '"'
$shortcut.WorkingDirectory = $scriptDir
$shortcut.Description = "pwpc - lock the PC after inactivity"
$shortcut.Save()

Write-Output "Shortcut created: $shortcutPath"
Write-Output "pwpc will start automatically at every Windows sign-in."
Write-Output "To remove it: Remove-Item '$shortcutPath'"
