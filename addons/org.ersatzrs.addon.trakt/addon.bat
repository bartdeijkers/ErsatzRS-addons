@echo off
setlocal DisableDelayedExpansion

set "PYTHON_BIN=%ERSATZRS_ADDON_SETTING_PYTHON_BIN%"
if not defined PYTHON_BIN set "PYTHON_BIN=python"
if exist "%PYTHON_BIN%" goto :run
where "%PYTHON_BIN%" >nul 2>&1
if not errorlevel 1 goto :run
if /i "%~1"=="check" (
    echo {"status":"unavailable","code":"missing-command","message":"The configured Python executable is unavailable."}
    exit /b 0
)
>&2 echo configured Python executable is unavailable
exit /b 69

:run
"%PYTHON_BIN%" "%~dp0trakt.py" "%~1"
exit /b %ERRORLEVEL%
