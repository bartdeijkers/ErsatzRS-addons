@echo off
setlocal DisableDelayedExpansion

set "OPERATION=%~1"
if defined ERSATZRS_ADDON_SETTING_CURL_BIN set "CURL_BIN=%ERSATZRS_ADDON_SETTING_CURL_BIN%"

if /i "%OPERATION%"=="check" goto :check
if /i "%OPERATION%"=="list" goto :list
if /i "%OPERATION%"=="play" goto :play
call :fail operation-failed "Unsupported add-on operation." 64
exit /b 64

:check
call :require_program "%FFMPEG_BIN%"
if errorlevel 1 goto :missing
if not defined CURL_BIN set "CURL_BIN=curl.exe"
call :require_program "%CURL_BIN%"
if errorlevel 1 goto :missing
call :require_program "powershell.exe"
if errorlevel 1 goto :missing
call :require_program "deno.exe"
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
    if errorlevel 1 goto :provider_failed
    exit /b 0
)
if not defined ERSATZRS_REMOTE_STREAM_PLAYLIST_URL goto :missing_playlist_url
call "%~dp0libexec\beeldengeluid.bat" list "%ERSATZRS_REMOTE_STREAM_PLAYLIST_URL%"
if errorlevel 1 goto :provider_failed
exit /b 0

:play
if not defined ERSATZRS_REMOTE_STREAM_URL goto :missing_stream_url
if not defined ERSATZRS_REMOTE_STREAM_SEEK set "ERSATZRS_REMOTE_STREAM_SEEK=0"
call "%~dp0libexec\beeldengeluid.bat" play "%ERSATZRS_REMOTE_STREAM_URL%" "%ERSATZRS_REMOTE_STREAM_SEEK%"
if errorlevel 1 goto :provider_failed
exit /b 0

:provider_failed
call :fail provider-unreachable "The media provider request failed." 69
exit /b 69

:missing_playlist_url
call :fail missing-setting "A playlist URL is required." 64
exit /b 64

:missing_stream_url
call :fail missing-setting "A remote stream URL is required." 64
exit /b 64

:fail
>&2 echo {"code":"%~1","message":"%~2"}
exit /b %~3

:require_program
if "%~1"=="" exit /b 1
if exist "%~1" exit /b 0
where "%~1" >nul 2>&1
exit /b %ERRORLEVEL%
