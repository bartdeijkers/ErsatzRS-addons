@echo off
setlocal DisableDelayedExpansion

set "OPERATION=%~1"
set "YT_DLP_BIN=%ERSATZRS_ADDON_SETTING_YT_DLP_BIN%"
if not defined YT_DLP_BIN set "YT_DLP_BIN=yt-dlp.exe"
set "YT_DLP_CACHE_DIR=%ERSATZRS_ADDON_CACHE_DIR%"
if not defined YT_DLP_CACHE_DIR if defined TEMP set "YT_DLP_CACHE_DIR=%TEMP%\ersatzrs-yt-dlp-cache"
if not defined YT_DLP_CACHE_DIR if defined TMP set "YT_DLP_CACHE_DIR=%TMP%\ersatzrs-yt-dlp-cache"
if not defined YT_DLP_CACHE_DIR goto :missing_cache

if /i "%OPERATION%"=="check" goto :check
if /i "%OPERATION%"=="discover" goto :media_list_import
if /i "%OPERATION%"=="enrich" goto :media_list_import
if /i "%OPERATION%"=="enrich-options" goto :media_list_import
if /i "%OPERATION%"=="runtime-info" goto :item_operation
if /i "%OPERATION%"=="test-access" goto :item_operation
if /i "%OPERATION%"=="interval-metadata" goto :item_operation
if /i "%OPERATION%"=="play-intervals" goto :item_operation
if /i "%OPERATION%"=="prepare" goto :item_operation
if /i "%OPERATION%"=="subtitles" goto :item_operation
if /i "%OPERATION%"=="list" goto :list
if /i "%OPERATION%"=="item" goto :item
if /i "%OPERATION%"=="play" goto :play
call :fail operation-failed "Unsupported add-on operation." 64
exit /b 64

:check
call :require_program "%YT_DLP_BIN%"
if errorlevel 1 goto :missing
call :require_program "%FFMPEG_BIN%"
if errorlevel 1 goto :missing
call :require_program "powershell.exe"
if errorlevel 1 goto :missing
call :require_program "deno.exe"
if errorlevel 1 goto :missing_js_runtime
echo {"status":"ready","code":"ready","message":"yt-dlp Remote Streams is ready."}
exit /b 0

:media_list_import
call :require_program "%YT_DLP_BIN%"
if errorlevel 1 goto :missing
call :require_program "deno.exe"
if errorlevel 1 goto :missing_js_runtime
deno.exe run --quiet --allow-env=YT_DLP_BIN,YT_DLP_CACHE_DIR --allow-run "%~dp0libexec\media-list-import.ts" "%OPERATION%"
if errorlevel 1 goto :provider_failed
exit /b 0

:item_operation
deno.exe run --quiet --allow-env --allow-run --allow-read --allow-write "%~dp0libexec\item-operations.ts" "%OPERATION%"
exit /b %ERRORLEVEL%

:item
if not defined ERSATZRS_REMOTE_STREAM_ITEM_IDS goto :missing_item_ids
call :require_program "%YT_DLP_BIN%"
if errorlevel 1 goto :missing
call :require_program "powershell.exe"
if errorlevel 1 goto :missing
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0libexec\item-metadata.ps1"
if errorlevel 1 goto :provider_failed
exit /b 0

:missing
echo {"status":"unavailable","code":"missing-command","message":"yt-dlp or managed FFmpeg is unavailable."}
exit /b 0

rem yt-dlp enables only this runtime by default. Without it the provider hands
rem back a player response whose media URL is bound to a restricted client, and
rem the managed FFmpeg downloader is refused when it fetches that URL, so
rem playback cannot succeed. Reached only from :check; :missing stays the
rem shared answer for :list.
:missing_js_runtime
echo {"status":"unavailable","code":"missing-js-runtime","message":"A JavaScript runtime is required for playback and was not found."}
exit /b 0

:list
set "PLAYLIST_URL=%ERSATZRS_MEDIA_LIST_URL%"
if not defined PLAYLIST_URL set "PLAYLIST_URL=%ERSATZRS_REMOTE_STREAM_PLAYLIST_URL%"
if not defined PLAYLIST_URL goto :missing_playlist_url
set "MEDIA_LIST_MODE=0"
if defined ERSATZRS_MEDIA_LIST_URL set "MEDIA_LIST_MODE=1"
call :require_program "%YT_DLP_BIN%"
if errorlevel 1 goto :missing
call :require_program "powershell.exe"
if errorlevel 1 goto :missing
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0libexec\youtube-list.ps1"
if errorlevel 1 goto :provider_failed
exit /b 0

:play
if not defined ERSATZRS_REMOTE_STREAM_URL goto :missing_stream_url
if not defined ERSATZRS_REMOTE_STREAM_SEEK set "ERSATZRS_REMOTE_STREAM_SEEK=0"
deno.exe run --quiet --allow-env --allow-run "%~dp0libexec\fragment-playback.ts"
if errorlevel 1 goto :provider_failed
exit /b 0

:provider_failed
call :fail provider-unreachable "The video provider request failed." 69
exit /b 69

:missing_playlist_url
call :fail missing-setting "A playlist URL is required." 64
exit /b 64

:missing_stream_url
call :fail missing-setting "A remote stream URL is required." 64
exit /b 64

:missing_item_ids
call :fail missing-setting "At least one item identity is required." 64
exit /b 64

:missing_cache
call :fail operation-failed "The add-on cache directory is unavailable." 70
exit /b 70

:fail
>&2 echo {"code":"%~1","message":"%~2"}
exit /b %~3

:require_program
if "%~1"=="" exit /b 1
if exist "%~1" exit /b 0
where "%~1" >nul 2>&1
exit /b %ERRORLEVEL%
