@echo off
setlocal EnableDelayedExpansion
title SmartRail AI - Control Room Launcher
cd /d "%~dp0"

rem ---- ANSI colours (Windows 10+) ----
for /F %%a in ('echo prompt $E^| cmd') do set "ESC=%%a"
set "R=%ESC%[0m"
set "RED=%ESC%[91m"
set "GRN=%ESC%[92m"
set "YEL=%ESC%[93m"
set "BLU=%ESC%[94m"
set "MAG=%ESC%[95m"
set "CYN=%ESC%[96m"
set "WHT=%ESC%[97m"
set "BOLD=%ESC%[1m"

cls
echo.
echo %CYN%%BOLD%   ============================================================%R%
echo %CYN%%BOLD%    ____                      _   ____       _ _      _    ___ %R%
echo %BLU%%BOLD%   / ___^| _ __ ___   __ _ _ __^| ^|_^|  _ \ __ _(_) ^|    / \  ^|_ _^|%R%
echo %MAG%%BOLD%   \___ \^| '_ ` _ \ / _` ^| '__^| __^| ^|_) / _` ^| ^| ^|   / _ \  ^| ^| %R%
echo %YEL%%BOLD%    ___) ^| ^| ^| ^| ^| ^| (_^| ^| ^|  ^| ^|_^|  _ ^< (_^| ^| ^| ^|  / ___ \ ^| ^| %R%
echo %GRN%%BOLD%   ^|____/^|_^| ^|_^| ^|_^|\__,_^|_^|   \__^|_^| \_\__,_^|_^|_^| /_/   \_\___^|%R%
echo %CYN%%BOLD%   ============================================================%R%
echo %WHT%        Intelligent Railway Traffic Control  -  ESP32 Rig%R%
echo.

rem ---- 1. find Python ----
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
  echo %RED%[X] Python 3 was not found. Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^).%R%
  pause & exit /b 1
)
echo %GRN%[OK]%R% Python found: %WHT%!PY!%R%

rem ---- 2. virtual environment ----
if not exist ".venv\Scripts\python.exe" (
  echo %YEL%[..]%R% Creating virtual environment ^(first run only^)...
  !PY! -m venv .venv
  if errorlevel 1 ( echo %RED%[X] Could not create the virtual environment.%R% & pause & exit /b 1 )
)
set "VPY=.venv\Scripts\python.exe"
echo %GRN%[OK]%R% Virtual environment ready

rem ---- 3. requirements ----
echo %YEL%[..]%R% Installing requirements ^(Flask, WebSocket, Streamlit...^)
"%VPY%" -m pip install --disable-pip-version-check -q -r web\requirements.txt -r streamlit_app\requirements.txt
if errorlevel 1 (
  echo %RED%[X] Installing requirements failed. Check your internet connection and try again.%R%
  pause & exit /b 1
)
echo %GRN%[OK]%R% Requirements installed

rem ---- 4. dataset for the analytics app ----
if not exist "data\railway_dataset.csv" (
  echo %YEL%[..]%R% Generating sample railway dataset...
  "%VPY%" data\generate_dataset.py
)

rem ---- 5. join the ESP32 Wi-Fi if it is in range ----
netsh wlan show networks 2>nul | findstr /C:"SmartRail-ESP32" >nul
if not errorlevel 1 (
  echo %YEL%[..]%R% ESP32 Wi-Fi found, connecting...
  netsh wlan connect name="SmartRail-ESP32" >nul 2>&1
  timeout /t 4 /nobreak >nul
  echo %GRN%[OK]%R% Requested connection to %WHT%SmartRail-ESP32%R%
) else (
  echo %YEL%[!!]%R% ESP32 Wi-Fi %WHT%SmartRail-ESP32%R% not visible. Power the board, or join it yourself.
)

rem ---- 6. choose what to start ----
set "MODE=%~1"
if "%MODE%"=="" (
  echo.
  echo %CYN%%BOLD%  What do you want to start?%R%
  echo   %GRN%[1]%R% Control-room dashboard        %WHT%http://localhost:5000%R%
  echo   %GRN%[2]%R% Streamlit analytics           %WHT%http://localhost:8501%R%
  echo   %GRN%[3]%R% Both
  echo.
  choice /C 123 /N /M "%YEL%  Your choice [1/2/3]: %R%"
  if errorlevel 3 ( set "MODE=both" ) else if errorlevel 2 ( set "MODE=analytics" ) else ( set "MODE=dashboard" )
)

if /I "%MODE%"=="analytics" goto :analytics
if /I "%MODE%"=="both" start "SmartRail Analytics" cmd /k "%VPY% -m streamlit run streamlit_app\app.py"

:dashboard
echo.
echo %GRN%%BOLD%  Starting the dashboard...%R%
echo %WHT%  Open:  %CYN%http://localhost:5000%R%
echo %WHT%  Login: %YEL%controller@smartrail.gov.in%WHT% / %YEL%controller123%R%
echo %WHT%  ESP32 Wi-Fi: %YEL%SmartRail-ESP32%WHT% / %YEL%smartrail123%R%
echo %MAG%  Press Ctrl+C to stop.%R%
echo.
start "" http://localhost:5000
cd web
"..\%VPY%" app.py
goto :end

:analytics
echo.
echo %GRN%%BOLD%  Starting Streamlit analytics...%R%
"%VPY%" -m streamlit run streamlit_app\app.py

:end
echo.
echo %RED%  Server stopped.%R%
pause
endlocal
