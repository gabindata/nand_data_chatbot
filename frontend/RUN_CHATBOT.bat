@echo off
chcp 65001 > nul
title SUNNY 9 Chatbot

cd /d "%~dp0"

echo.
echo ==========================================
echo   Starting SUNNY 9 Chatbot UI
echo ==========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py"
) else (
    set "PYTHON_CMD=python"
)

%PYTHON_CMD% --version
if errorlevel 1 (
    echo.
    echo Python was not found.
    echo Please install Python 3.10 or later, then run this file again.
    pause
    exit /b 1
)

echo.
echo Installing required packages...
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Package installation failed.
    pause
    exit /b 1
)

echo.
echo Opening the chatbot in your browser...
%PYTHON_CMD% -m streamlit run app.py

pause
