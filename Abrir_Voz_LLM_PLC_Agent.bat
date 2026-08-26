@echo off
setlocal

cd /d "%~dp0"

set "PYTHONW_EXE=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=pythonw"

start "" "%PYTHONW_EXE%" "%~dp0Abrir_Voz_LLM_PLC_Agent.pyw"
