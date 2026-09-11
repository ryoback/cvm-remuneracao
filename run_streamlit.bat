@echo off
rem Sobe o dashboard Streamlit de remuneracao e abre no navegador.
cd /d "%~dp0"
python -m streamlit run app.py %*
if errorlevel 1 pause
