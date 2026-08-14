@echo off
setlocal
cd /d "%~dp0"
title AI Council

echo.
echo   ===============================================
echo    A I   C O U N C I L   -   starting up
echo   ===============================================
echo.

rem --- virtual environment -------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   [1/3] Creating virtual environment...
    py -3 -m venv .venv 2>nul
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo   ERROR: could not create a virtual environment.
        echo   Install Python 3.10+ from https://python.org and try again.
        echo.
        pause
        exit /b 1
    )
)
set "PY=.venv\Scripts\python.exe"

rem --- dependencies --------------------------------------------------------
"%PY%" -c "import fastapi, uvicorn, openai, dotenv" >nul 2>&1
if errorlevel 1 (
    echo   [2/3] Installing dependencies ^(first run only^)...
    "%PY%" -m pip install --upgrade pip --quiet
    "%PY%" -m pip install -r requirements.txt --quiet
    if errorlevel 1 (
        echo.
        echo   ERROR: dependency install failed. See the output above.
        echo.
        pause
        exit /b 1
    )
)

rem --- config --------------------------------------------------------------
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo   Created .env - open it and paste your NVIDIA_API_KEY, then rerun.
    echo   Get a key at https://build.nvidia.com
    echo.
    notepad .env
    pause
    exit /b 1
)

rem --- go ------------------------------------------------------------------
echo   [3/3] Convening the council...
"%PY%" -m council --port 8000
if errorlevel 1 (
    echo.
    echo   The server stopped with an error.
    pause
)
endlocal
