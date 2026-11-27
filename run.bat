@echo off
rem Installs dependencies if needed, then starts the DR Runbook Agent. No prompts.
setlocal
cd /d "%~dp0"
set "PY=.venv\Scripts\python.exe"
if exist "%PY%" goto deps
echo Creating virtual environment...
py -3.13 -c "" >nul 2>&1
if errorlevel 1 (python -m venv .venv) else (py -3.13 -m venv .venv)
if errorlevel 1 goto failed
:deps
"%PY%" -c "import agent_framework, agent_framework_openai, agent_framework_foundry_hosting, starlette, uvicorn, dotenv, pydantic, pytest, httpx" >nul 2>&1
if not errorlevel 1 goto start
echo Installing dependencies. The first run can take a few minutes...
"%PY%" -m ensurepip --upgrade >nul 2>&1
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
:start
"%PY%" main.py %*
exit /b %errorlevel%
:failed
echo Setup failed. See the messages above.
exit /b 1
