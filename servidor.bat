@echo off
rem Sobe o dashboard de remuneracao em http://127.0.0.1:8000 e abre o navegador.
cd /d "%~dp0"
python servidor.py --abrir %*
if errorlevel 1 pause
