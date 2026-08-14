@echo off
setlocal DisableDelayedExpansion

set "OPERATION=%~1"
if defined ERSATZRS_ADDON_SETTING_CURL_BIN set "CURL_BIN=%ERSATZRS_ADDON_SETTING_CURL_BIN%"
if defined ERSATZRS_ADDON_SETTING_ACTION_ID set "BEELDENGELUID_ACTION_ID=%ERSATZRS_ADDON_SETTING_ACTION_ID%"

if /i "%OPERATION%"=="check" goto :check
if /i "%OPERATION%"=="list" goto :list
if /i "%OPERATION%"=="play" goto :play
>&2 echo unsupported add-on operation
exit /b 64

:check
call :require_program "%FFMPEG_BIN%"
if errorlevel 1 goto :missing
if not defined CURL_BIN set "CURL_BIN=curl.exe"
call :require_program "%CURL_BIN%"
if errorlevel 1 goto :missing
call :require_program "powershell.exe"
if errorlevel 1 goto :missing
echo {"status":"ready","code":"ready","message":"Beeld ^& Geluid is ready."}
exit /b 0

:missing
echo {"status":"unavailable","code":"missing-command","message":"A required executable is unavailable."}
exit /b 0

:list
if defined ERSATZRS_MEDIA_LIST_URL (
    set "BEELDENGELUID_OUTPUT=media-list"
    call "%~dp0libexec\beeldengeluid.bat" list "%ERSATZRS_MEDIA_LIST_URL%"
    exit /b %ERRORLEVEL%
)
if not defined ERSATZRS_REMOTE_STREAM_PLAYLIST_URL (
    >&2 echo playlist URL is required
    exit /b 64
)
call "%~dp0libexec\beeldengeluid.bat" list "%ERSATZRS_REMOTE_STREAM_PLAYLIST_URL%"
exit /b %ERRORLEVEL%

:play
if not defined ERSATZRS_REMOTE_STREAM_URL (
    >&2 echo remote stream URL is required
    exit /b 64
)
if not defined ERSATZRS_REMOTE_STREAM_SEEK set "ERSATZRS_REMOTE_STREAM_SEEK=0"
call "%~dp0libexec\beeldengeluid.bat" play "%ERSATZRS_REMOTE_STREAM_URL%" "%ERSATZRS_REMOTE_STREAM_SEEK%"
exit /b %ERRORLEVEL%

:require_program
if "%~1"=="" exit /b 1
if exist "%~1" exit /b 0
where "%~1" >nul 2>&1
exit /b %ERRORLEVEL%
