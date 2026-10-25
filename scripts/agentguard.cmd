@echo off
setlocal
if not defined AGENTGUARD_HOME set "AGENTGUARD_HOME=%USERPROFILE%\.agentguard"
if not defined AGENTGUARD_CONFIG if exist "%AGENTGUARD_HOME%\agentguard.yaml" set "AGENTGUARD_CONFIG=%AGENTGUARD_HOME%\agentguard.yaml"
if not defined AGENTGUARD_REPO_ROOT if exist "%AGENTGUARD_HOME%\app" set "AGENTGUARD_REPO_ROOT=%AGENTGUARD_HOME%\app"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"

set "PY_EXE=%AGENTGUARD_HOME%\venv\Scripts\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

"%PY_EXE%" -m agentguard.cli %*
exit /b %ERRORLEVEL%
