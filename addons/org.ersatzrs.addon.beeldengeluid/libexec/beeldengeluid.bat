@echo off
setlocal DisableDelayedExpansion

rem Enumerate or stream Beeld & Geluid "Schatkamer" media for ErsatzRS.

if "%~1"=="" goto :usage
if /i "%~1"=="list" goto :list_args
if /i "%~1"=="play" goto :play_args
if not "%~3"=="" goto :usage
set "EPISODE_URL=%~1"
set "SEEK_POSITION=%~2"
goto :play_args_ready

:list_args
if not "%~3"=="" goto :usage
if not "%~2"=="" set "PLAYLIST_URL=%~2"
if not defined PLAYLIST_URL goto :usage
goto :list_url_valid

:play_args
if "%~2"=="" goto :usage
if not "%~4"=="" goto :usage
set "EPISODE_URL=%~2"
set "SEEK_POSITION=%~3"

:play_args_ready

if not defined SEEK_POSITION set "SEEK_POSITION=0"
rem Keep definitions backward compatible with builds that do not substitute
rem the opt-in marker yet.
if "%SEEK_POSITION%"=="{seek}" set "SEEK_POSITION=0"
if /i "%EPISODE_URL:~0,42%"=="https://schatkamer.beeldengeluid.nl/serie/" goto :url_valid
if /i "%EPISODE_URL:~0,41%"=="http://schatkamer.beeldengeluid.nl/serie/" goto :url_valid
>&2 echo beeldengeluid.bat: unsupported Schatkamer episode URL
goto :usage

:list_url_valid
if not defined CURL_BIN set "CURL_BIN=curl.exe"
call :require_program "%CURL_BIN%" curl
if errorlevel 1 exit /b 69
call :require_program "powershell.exe" PowerShell
if errorlevel 1 exit /b 69
call :require_program "deno.exe" Deno
if errorlevel 1 exit /b 69
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass ^
    -File "%~dp0beeldengeluid-list.ps1"
if errorlevel 1 exit /b 1
exit /b 0

:url_valid
if not defined CURL_BIN set "CURL_BIN=curl.exe"
if not defined FFMPEG_BIN set "FFMPEG_BIN=ffmpeg.exe"

call :require_program "%CURL_BIN%" curl
if errorlevel 1 exit /b 69
call :require_program "%FFMPEG_BIN%" FFmpeg
if errorlevel 1 exit /b 69
call :require_program "powershell.exe" PowerShell
if errorlevel 1 exit /b 69
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "if ($env:SEEK_POSITION -notmatch '^(0|[0-9]+:[0-9]{2}:[0-9]{2}([.][0-9]+)?)$') { exit 1 }"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: the seek timestamp is invalid
    exit /b 64
)
call :require_program "deno.exe" Deno
if errorlevel 1 exit /b 69
rem Chapter bounds stay on the episode URL for the plan module; only the page
rem and Server Action requests need them removed.
for /f "usebackq delims=" %%A in (`powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "([Uri]$env:EPISODE_URL).GetLeftPart([UriPartial]::Path)"`) do set "EPISODE_PAGE_URL=%%A"
if not defined EPISODE_PAGE_URL (
    >&2 echo beeldengeluid.bat: the Schatkamer episode URL is invalid
    exit /b 64
)

set "WORK_ID=%RANDOM%-%RANDOM%"
set "PAYLOAD_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-payload.json"
set "PAGE_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-page.html"
set "ACTION_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-action.txt"
set "COOKIE_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-cookies.txt"
set "CHUNK_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-chunk.js"
set "RSC_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-response.rsc"
set "PLAN_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-plan.tsv"

"%CURL_BIN%" --fail --silent --show-error --location --max-redirs 5 --proto "=https" --proto-redir "=https" --retry 2 --connect-timeout 10 --max-time 45 --cookie-jar "%COOKIE_FILE%" --output "%PAGE_FILE%" "%EPISODE_PAGE_URL%"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: the Schatkamer episode page request failed
    goto :failed
)

powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$html = [IO.File]::ReadAllText($env:PAGE_FILE);" ^
    "$action = $null;" ^
    "foreach ($match in [regex]::Matches($html, 'src=\x22([^\x22]+[.]js[^\x22]*)\x22')) {" ^
    "  $path = $match.Groups[1].Value;" ^
    "  if (-not $path.StartsWith('/_next/static/chunks/')) { continue };" ^
    "  & $env:CURL_BIN --fail --silent --show-error --output $env:CHUNK_FILE ('https://schatkamer.beeldengeluid.nl' + $path);" ^
    "  if ($LASTEXITCODE -ne 0) { continue };" ^
    "  $script = [IO.File]::ReadAllText($env:CHUNK_FILE);" ^
    "  $reference = [regex]::Match($script, '\x22([0-9a-f]{32,64})\x22[^;]{0,300}\x22getProgramStreamById\x22');" ^
    "  if ($reference.Success) { $action = $reference.Groups[1].Value; break }" ^
    "};" ^
    "if (-not $action) { throw 'Unable to discover getProgramStreamById' };" ^
    "[IO.File]::WriteAllText($env:ACTION_FILE, $action)"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: unable to discover getProgramStreamById
    goto :failed
)

set /p "STREAM_ACTION_ID="<"%ACTION_FILE%"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
    "if ($env:STREAM_ACTION_ID -notmatch '^[0-9a-f]{32,64}$') { exit 1 }"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: the discovered Server Action ID is invalid
    goto :failed
)

rem Build the JSON request without exposing the URL to cmd.exe re-parsing.
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$uri = [Uri]$env:EPISODE_URL;" ^
    "$id = $uri.AbsolutePath.TrimEnd('/').Split('/')[-1];" ^
    "if ($id -notmatch '^\d+$') { throw 'The Schatkamer episode ID must be numeric' };" ^
    "$json = ConvertTo-Json -Compress -InputObject @($id, $false);" ^
    "[IO.File]::WriteAllText($env:PAYLOAD_FILE, $json)"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: unable to build the Schatkamer request
    goto :failed
)

"%CURL_BIN%" ^
    --fail ^
    --silent ^
    --show-error ^
    --request POST ^
    --cookie "%COOKIE_FILE%" ^
    --cookie-jar "%COOKIE_FILE%" ^
    --header "Content-Type: text/plain;charset=UTF-8" ^
    --header "Next-Action: %STREAM_ACTION_ID%" ^
    --header "Accept: text/x-component" ^
    --data-binary "@%PAYLOAD_FILE%" ^
    --output "%RSC_FILE%" ^
    "%EPISODE_PAGE_URL%"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: the Schatkamer stream request failed
    goto :failed
)

rem One Schatkamer episode can be archived across several carriers. The shared
rem plan module orders them, maps the seek position and any chapter bounds onto
rem the concatenated timeline, and reports what each part has to contribute.
deno.exe run --quiet --allow-read="%RSC_FILE%" --allow-env=EPISODE_URL,SEEK_POSITION,CURL_BIN,ERSATZRS_ADDON_SETTING_DUPLICATE_TOLERANCE_SECONDS --allow-run "%~dp0stream-plan.ts" "%RSC_FILE%" >"%PLAN_FILE%"
set "PLAN_STATUS=%ERRORLEVEL%"
if not "%PLAN_STATUS%"=="0" (
    rem Keep the plan module's own status; it separates a rejected definition
    rem from an unusable provider response.
    call :cleanup
    exit /b %PLAN_STATUS%
)

set "PART_COUNT=0"
for /f "usebackq tokens=1-5 delims=	" %%A in ("%PLAN_FILE%") do (
    set /a PART_COUNT+=1 >nul
    rem %%E offsets this part's output timeline. Each part is a separate
    rem FFmpeg run that restarts at zero, so without an offset the
    rem concatenated stdout timeline steps backwards at every boundary.
    if "%%D"=="-" (
        "%FFMPEG_BIN%" -nostdin -hide_banner -loglevel error -ss "%%C" -headers "Cookie: %%B" -i "%%A" -map 0:v:0? -map 0:a:0? -c copy -output_ts_offset "%%E" -f mpegts pipe:1
    ) else (
        "%FFMPEG_BIN%" -nostdin -hide_banner -loglevel error -ss "%%C" -headers "Cookie: %%B" -i "%%A" -t "%%D" -map 0:v:0? -map 0:a:0? -c copy -output_ts_offset "%%E" -f mpegts pipe:1
    )
    if errorlevel 1 goto :ffmpeg_failed
)

if "%PART_COUNT%"=="0" (
    >&2 echo beeldengeluid.bat: no signed HLS stream URL was found
    goto :failed
)

call :cleanup
exit /b 0

:ffmpeg_failed
>&2 echo beeldengeluid.bat: FFmpeg could not stream the signed HLS source

:failed
call :cleanup
exit /b 1

:cleanup
if defined PAYLOAD_FILE del /q "%PAYLOAD_FILE%" >nul 2>&1
if defined PAGE_FILE del /q "%PAGE_FILE%" >nul 2>&1
if defined ACTION_FILE del /q "%ACTION_FILE%" >nul 2>&1
if defined COOKIE_FILE del /q "%COOKIE_FILE%" >nul 2>&1
if defined CHUNK_FILE del /q "%CHUNK_FILE%" >nul 2>&1
if defined RSC_FILE del /q "%RSC_FILE%" >nul 2>&1
if defined PLAN_FILE del /q "%PLAN_FILE%" >nul 2>&1
exit /b 0

:require_program
if exist "%~1" exit /b 0
where "%~1" >nul 2>&1
if not errorlevel 1 exit /b 0
>&2 echo beeldengeluid.bat: %~2 was not found: %~1
exit /b 1

:usage
>&2 echo Usage: beeldengeluid.bat list ^<Schatkamer series or shared-list URL^>
>&2 echo        beeldengeluid.bat play ^<Schatkamer episode URL^> [seek timestamp]
>&2 echo        beeldengeluid.bat ^<Schatkamer episode URL^> [seek timestamp]
exit /b 64
