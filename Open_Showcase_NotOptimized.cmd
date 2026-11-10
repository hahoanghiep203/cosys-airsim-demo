@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Scripts\ScenePerformance\launch_cosys.ps1" -Scene notoptimized -Profile baseline %*
