@echo off
setlocal
cd /d "%~dp0"
echo 1. Local agent (cli.json)
echo 2. Model API (api.json)
choice /C 12 /N /M "Select 1 or 2: "
if errorlevel 2 goto api
python office_connector.py --config cli.json
goto end
:api
python office_connector.py --config api.json
:end
pause
