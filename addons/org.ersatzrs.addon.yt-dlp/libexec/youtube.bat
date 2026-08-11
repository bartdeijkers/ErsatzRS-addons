@echo off
setlocal DisableDelayedExpansion

rem Resolve a YouTube video with yt-dlp, seek the remote source with the
rem ErsatzRS-managed FFmpeg runtime, and stream MPEG-TS to stdout.

if "%~1"=="" goto :usage
if not "%~3"=="" goto :usage

set "VIDEO_URL=%~1"
set "SEEK_POSITION=%~2"
if not defined SEEK_POSITION set "SEEK_POSITION=0"
rem Keep definitions backward compatible with builds that do not substitute
rem the opt-in marker yet.
if "%SEEK_POSITION%"=="{seek}" set "SEEK_POSITION=0"

if not defined FFMPEG_BIN (
    >&2 echo youtube.bat: FFMPEG_BIN is required; run this wrapper through ErsatzRS or set it to the managed FFmpeg executable
    exit /b 69
)

if defined YT_DLP_BIN goto :yt_dlp_ready
if exist "%~dp0yt-dlp.exe" set "YT_DLP_BIN=%~dp0yt-dlp.exe"
if defined YT_DLP_BIN goto :yt_dlp_ready
if exist "%~dp0..\..\..\yt-dlp.exe" set "YT_DLP_BIN=%~dp0..\..\..\yt-dlp.exe"
if defined YT_DLP_BIN goto :yt_dlp_ready
set "YT_DLP_BIN=yt-dlp.exe"

:yt_dlp_ready
call :require_program "%YT_DLP_BIN%" yt-dlp
if errorlevel 1 exit /b 69
call :require_program "%FFMPEG_BIN%" FFmpeg
if errorlevel 1 exit /b 69
call :require_program "powershell.exe" PowerShell
if errorlevel 1 exit /b 69

powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "if ($env:SEEK_POSITION -notmatch '^(0|[0-9]+:[0-9]{2}:[0-9]{2}([.][0-9]+)?)$') { exit 1 }"
if errorlevel 1 (
    >&2 echo youtube.bat: the seek timestamp is invalid
    exit /b 64
)

rem A combined H.264/AAC rendition gives the pipe a stable video/audio pair
rem and remains compatible with MPEG-TS stream copy. yt-dlp carries the
rem extractor-specific request headers into the managed FFmpeg downloader;
rem ffmpeg_i places the seek before the remote input is opened.
"%YT_DLP_BIN%" ^
    --no-config ^
    --no-update ^
    --quiet ^
    --no-playlist ^
    --ffmpeg-location "%FFMPEG_BIN%" ^
    --downloader ffmpeg ^
    --downloader-args "ffmpeg_i:-ss %SEEK_POSITION%" ^
    --hls-use-mpegts ^
    --format "best[ext=mp4][vcodec*=avc1][acodec*=mp4a]/best[acodec!=none][vcodec!=none]" ^
    --output - ^
    "%VIDEO_URL%"
if errorlevel 1 (
    >&2 echo youtube.bat: yt-dlp and managed FFmpeg could not stream the YouTube video
    exit /b 1
)
exit /b 0

:require_program
if exist "%~1" exit /b 0
where "%~1" >nul 2>&1
if not errorlevel 1 exit /b 0
>&2 echo youtube.bat: %~2 was not found: %~1
exit /b 1

:usage
>&2 echo Usage: youtube.bat ^<YouTube video URL^> [seek timestamp]
exit /b 64
