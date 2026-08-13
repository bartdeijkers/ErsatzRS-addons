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
if "%~2"=="" goto :usage
if not "%~3"=="" goto :usage
set "PLAYLIST_URL=%~2"
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

set "WORK_ID=%RANDOM%-%RANDOM%"
set "PAYLOAD_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-payload.json"
set "PAGE_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-page.html"
set "ACTION_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-action.txt"
set "COOKIE_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-cookies.txt"
set "CHUNK_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-chunk.js"
set "RSC_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-response.rsc"
set "STREAMS_FILE=%TEMP%\ersatzrs-beeldengeluid-%WORK_ID%-streams.txt"

"%CURL_BIN%" --fail --silent --show-error --location --cookie-jar "%COOKIE_FILE%" --output "%PAGE_FILE%" "%EPISODE_URL%"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: the Schatkamer episode page request failed
    goto :failed
)

if defined BEELDENGELUID_ACTION_ID goto :use_action_override

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
goto :action_ready

:use_action_override
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
    "[IO.File]::WriteAllText($env:ACTION_FILE, $env:BEELDENGELUID_ACTION_ID)"
if errorlevel 1 goto :failed

:action_ready

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
    "%EPISODE_URL%"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: the Schatkamer stream request failed
    goto :failed
)

rem Parse exact-length RSC T-chunks and convert the three signed query
rem parameters to a tab-separated base-URL/cookie record for each stream.
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$data = [IO.File]::ReadAllText($env:RSC_FILE);" ^
    "$records = @();" ^
    "foreach ($match in [regex]::Matches($data, '(\d+):T([0-9a-fA-F]+),')) {" ^
    "  $size = [Convert]::ToInt32($match.Groups[2].Value, 16);" ^
    "  $start = $match.Index + $match.Length;" ^
    "  if ($start + $size -gt $data.Length) { continue };" ^
    "  $raw = $data.Substring($start, $size).Trim().Replace('\u0026', '&');" ^
    "  if ($raw -notlike '*sk-video.cdn.beeldengeluid.nl*.m3u8*') { continue };" ^
    "  $uri = [Uri]$raw;" ^
    "  if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'sk-video.cdn.beeldengeluid.nl' -or -not $uri.AbsolutePath.EndsWith('.m3u8')) { throw 'Unexpected stream URL' };" ^
    "  $parameters = @{};" ^
    "  foreach ($pair in $uri.Query.TrimStart('?').Split('&')) {" ^
    "    $separator = $pair.IndexOf('=');" ^
    "    if ($separator -lt 0) { continue };" ^
    "    $name = [Uri]::UnescapeDataString($pair.Substring(0, $separator));" ^
    "    $value = [Uri]::UnescapeDataString($pair.Substring($separator + 1).Replace('+', ' '));" ^
    "    $parameters[$name] = $value" ^
    "  };" ^
    "  foreach ($name in @('CloudFront-Policy', 'CloudFront-Signature', 'CloudFront-Key-Pair-Id')) { if (-not $parameters.ContainsKey($name)) { throw ('Missing ' + $name) } };" ^
    "  $baseUrl = $uri.GetLeftPart([UriPartial]::Path);" ^
    "  $cookie = 'CloudFront-Policy=' + $parameters['CloudFront-Policy'] + '; CloudFront-Signature=' + $parameters['CloudFront-Signature'] + '; CloudFront-Key-Pair-Id=' + $parameters['CloudFront-Key-Pair-Id'];" ^
    "  $records += $baseUrl + [char]9 + $cookie" ^
    "};" ^
    "if ($records.Count -eq 0) { throw 'No signed HLS stream URL was found' };" ^
    "[IO.File]::WriteAllLines($env:STREAMS_FILE, [string[]]$records, [Text.Encoding]::ASCII)"
if errorlevel 1 (
    >&2 echo beeldengeluid.bat: no usable signed HLS stream was found
    goto :failed
)

set "STREAM_COUNT=0"
for /f "usebackq tokens=1,* delims=	" %%A in ("%STREAMS_FILE%") do (
    set /a STREAM_COUNT+=1 >nul
    "%FFMPEG_BIN%" -nostdin -hide_banner -loglevel error -ss "%SEEK_POSITION%" -headers "Cookie: %%B" -i "%%A" -map 0:v:0? -map 0:a:0? -c copy -f mpegts pipe:1
    if errorlevel 1 goto :ffmpeg_failed
)

if "%STREAM_COUNT%"=="0" (
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
if defined STREAMS_FILE del /q "%STREAMS_FILE%" >nul 2>&1
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
