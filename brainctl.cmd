@echo off
rem brainctl shim - sanitizes PYTHONHOME/PYTHONPATH (known to be polluted on
rem this machine: breaks python startup with "SRE module mismatch").
setlocal
set "PYTHONHOME="
set "PYTHONPATH="
set "UV_INTERNAL__PYTHONHOME="
"%~dp0.venv\Scripts\python.exe" -m second_brain %*
exit /b %errorlevel%
