# Windows PowerShell launcher for WiFi Agent.
# install.py installs the private runtime and opens the secure setup window.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 "$PSScriptRoot\install.py" @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot\install.py" @args
} else {
    Write-Error "Python 3.10 or newer is required. Install it from python.org and run this file again."
}
