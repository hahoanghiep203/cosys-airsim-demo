@echo off
set PYTHONDONTWRITEBYTECODE=1
"%~dp0.venv\Scripts\python.exe" "%~dp0Scripts\SceneDiversity\run_angle_capture.py" %*
if errorlevel 1 pause
