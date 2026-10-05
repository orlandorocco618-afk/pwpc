# Opens the pwpc setup window to change the password and the inactivity time.
# A pwpc instance already running picks up the new settings within a few seconds.

$scriptDir = $PSScriptRoot
python (Join-Path $scriptDir "lock_screen.py") --setup
