$ErrorActionPreference = "Stop"
python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
python (Join-Path $PSScriptRoot "bridge.py")
