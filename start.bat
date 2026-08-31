@echo off
title Steam Mush Dash Workshop Uploader
cd /d "%~dp0"

REM Install dependencies if not present yet
py -3 -c "import customtkinter, PIL" 2>nul || py -3 -m pip install -r requirements.txt

py -3 steam_uploader.py
if errorlevel 1 (
    echo.
    echo Failed to start. Is Python installed? ^(https://www.python.org^)
    pause
)
