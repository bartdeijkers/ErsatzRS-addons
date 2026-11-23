@echo off
setlocal DisableDelayedExpansion
rem Internet Archive add-on entrypoint (Deno).

set "OPERATION=%~1"
set "MAIN=%~dp0libexec\main.mts"
set "ENV_NAMES=ERSATZRS_MEDIA_LIST_URL,ERSATZRS_REMOTE_STREAM_PLAYLIST_URL,ERSATZRS_REMOTE_STREAM_URL,ERSATZRS_REMOTE_STREAM_SEEK,FFMPEG_BIN"

where deno.exe >nul 2>nul
if errorlevel 1 goto :missing_runtime
if /i "%OPERATION%"=="check" goto :check
if /i "%OPERATION%"=="list" goto :list
if /i "%OPERATION%"=="play" goto :play
call :fail operation-failed "Unsupported add-on operation." 64
exit /b 64

:check
if not defined FFMPEG_BIN goto :check_plain
deno.exe run --quiet --no-prompt "--allow-env=%ENV_NAMES%" "--allow-read=%FFMPEG_BIN%" "%MAIN%" check
exit /b %ERRORLEVEL%

:check_plain
deno.exe run --quiet --no-prompt "--allow-env=%ENV_NAMES%" "%MAIN%" check
exit /b %ERRORLEVEL%

:list
deno.exe run --quiet --no-prompt "--allow-env=%ENV_NAMES%" --allow-net=archive.org "%MAIN%" list
exit /b %ERRORLEVEL%

:play
if not defined FFMPEG_BIN goto :missing_ffmpeg
deno.exe run --quiet --no-prompt --allow-env --allow-net=archive.org "--allow-run=%FFMPEG_BIN%" "%MAIN%" play
exit /b %ERRORLEVEL%

:missing_ffmpeg
call :fail missing-command "The managed FFmpeg runtime is unavailable." 69
exit /b 69

:missing_runtime
if /i "%OPERATION%"=="check" (
    echo {"status":"unavailable","code":"missing-js-runtime","message":"Deno is required and was not found on PATH."}
    exit /b 0
)
call :fail missing-js-runtime "Deno is required and was not found on PATH." 69
exit /b 69

:fail
>&2 echo {"code":"%~1","message":"%~2"}
exit /b %~3
