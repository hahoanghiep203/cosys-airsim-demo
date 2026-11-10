param([ValidateSet("baseline","balanced")][string]$Profile="balanced",[switch]$Offscreen)
& (Join-Path $PSScriptRoot "launch_cosys.ps1") -Profile $Profile -Scene original -Offscreen:$Offscreen
