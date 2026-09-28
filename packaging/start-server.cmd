@echo off
setlocal
set "RTPLOT_REPO=%~dp0.."
if not exist "%RTPLOT_REPO%\dist\rtplot-server.exe" (
  echo Build first with packaging\build-windows.ps1. See packaging\README.md.
  exit /b 1
)
set "TEMP=%RTPLOT_REPO%\.build\runtime-temp"
set "TMP=%TEMP%"
if not exist "%TEMP%" mkdir "%TEMP%"
start "" "%RTPLOT_REPO%\dist\rtplot-server.exe" %*
