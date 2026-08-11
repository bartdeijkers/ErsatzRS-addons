@echo off
setlocal DisableDelayedExpansion

set "OPERATION=%~1"
set "YT_DLP_BIN=%ERSATZRS_ADDON_SETTING_YT_DLP_BIN%"
if not defined YT_DLP_BIN set "YT_DLP_BIN=yt-dlp.exe"

if /i "%OPERATION%"=="check" goto :check
if /i "%OPERATION%"=="play" goto :play
>&2 echo unsupported add-on operation
exit /b 64

:check
call :require_program "%YT_DLP_BIN%"
if errorlevel 1 goto :missing
call :require_program "%FFMPEG_BIN%"
if errorlevel 1 goto :missing
call :require_program "powershell.exe"
if errorlevel 1 goto :missing
echo {"status":"ready","code":"ready","message":"yt-dlp Remote Streams is ready."}
exit /b 0

:missing
echo {"status":"unavailable","code":"missing-command","message":"yt-dlp or managed FFmpeg is unavailable."}
exit /b 0

:play
if not defined ERSATZRS_REMOTE_STREAM_URL (
    >&2 echo remote stream URL is required
    exit /b 64
)
if not defined ERSATZRS_REMOTE_STREAM_SEEK set "ERSATZRS_REMOTE_STREAM_SEEK=0"
call "%~dp0libexec\youtube.bat" "%ERSATZRS_REMOTE_STREAM_URL%" "%ERSATZRS_REMOTE_STREAM_SEEK%"
exit /b %ERRORLEVEL%

:require_program
if "%~1"=="" exit /b 1
if exist "%~1" exit /b 0
where "%~1" >nul 2>&1
exit /b %ERRORLEVEL%
