@echo off
setlocal

rem Start the Futu Algo web console from this project's directory.
cd /d "%~dp0"
title Futu Algo Web Console

set "APP=%~dp0.venv\Scripts\futu-algo.exe"
set "CONFIG=%~dp0config.yaml"

if not exist "%CONFIG%" (
    echo [ERROR] Configuration file not found:
    echo         "%CONFIG%"
    goto :failed
)

if exist "%APP%" goto :start

rem Fallback for a virtual environment created with a different layout.
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m futu_algo web -c "%CONFIG%"
    goto :finished
)

echo [ERROR] futu-algo was not found in the project's .venv.
echo         Expected: "%APP%"
echo         Install the project with: .venv\Scripts\python.exe -m pip install -e .
goto :failed

:start
"%APP%" web -c "%CONFIG%"

:finished
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Futu Algo exited with code %EXIT_CODE%.
    goto :failed
)
exit /b 0

:failed
echo.
echo Press any key to close this window . . .
pause >nul
exit /b 1
