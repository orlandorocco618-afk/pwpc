# Shows the lock screen right away (without waiting for the inactivity time),
# to check how it looks. The script exits as soon as the right password is typed.
# If pwpc has never been set up, the setup window opens first.

$scriptDir = $PSScriptRoot
python (Join-Path $scriptDir "lock_screen.py") --test
