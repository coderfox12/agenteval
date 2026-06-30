@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo Suche lauffaehiges Python ...

set "PYCMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
    echo Kein lauffaehiges Python gefunden ^(weder "py -3" noch "python"^).
    echo Bitte Python 3.11+ von https://python.org installieren.
    pause
    exit /b 1
)
echo Verwende: %PYCMD%

echo Pruefe Abhaengigkeiten ...

%PYCMD% -c "import streamlit" >nul 2>nul
if errorlevel 1 (
    echo Installiere Webapp-Abhaengigkeiten ...
    %PYCMD% -m pip install -r webapp\requirements.txt
    if errorlevel 1 goto :error
)

where agenteval-report >nul 2>nul
if errorlevel 1 (
    echo Installiere agenteval-ovb Paket ...
    %PYCMD% -m pip install -e .
    if errorlevel 1 goto :error
)

echo.
echo Starte Agent-Eval-Webapp unter http://localhost:8501 ...
echo (Fenster offen lassen, mit Strg+C beenden)
echo.
%PYCMD% -m streamlit run webapp\app.py
goto :eof

:error
echo.
echo Installation fehlgeschlagen. Bitte Python/pip-Installation pruefen.
pause
