# Native Windows entrypoint fixture; no provider access or Python required.
param([string]$Package = (Join-Path $PSScriptRoot '../addons/org.ersatzrs.addon.yt-dlp'))
$ErrorActionPreference = 'Stop'
$stage = Join-Path $env:TEMP ('ersatzrs-source-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
$originalDirectory = Get-Location
try {
    $candidate = Join-Path $stage 'candidate'
    Copy-Item -Recurse -LiteralPath $Package -Destination $candidate
    Set-Location $stage
    $fake = Join-Path $stage 'fixture.exe'
    Add-Type -OutputAssembly $fake -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
public class SourceCheckFixture {
    public static int Main(string[] args) {
        File.AppendAllText(Environment.GetEnvironmentVariable("SOURCE_CHECK_CALLS"), String.Join("|", args) + "\n");
        string mode = Environment.GetEnvironmentVariable("SOURCE_CHECK_MODE");
        if (mode == "failure") { Console.Error.Write("SYNTHETIC_PRIVATE_DIAGNOSTIC"); return 1; }
        if (mode == "limit") { Console.Write(new string('x', 1048577)); return 0; }
        if (mode == "sleep") { System.Threading.Thread.Sleep(60000); }
        Console.Write(File.ReadAllText(Environment.GetEnvironmentVariable("SOURCE_CHECK_DATA")));
        return 0;
    }
}
'@
    $env:ERSATZRS_ADDON_SETTING_YT_DLP_BIN = $fake
    $env:FFMPEG_BIN = $fake
    $env:ERSATZRS_ADDON_CACHE_DIR = Join-Path $stage 'cache'
    $env:ERSATZRS_ADDON_CAPABILITY = 'media-list.source-check.v1'
    $env:SOURCE_CHECK_CALLS = Join-Path $stage 'calls.txt'
    $env:SOURCE_CHECK_DATA = Join-Path $stage 'data.json'
    $env:SOURCE_CHECK_MODE = 'success'
    $entrypoint = Join-Path $candidate 'addon.bat'
    function Invoke-Probe($validator) {
        $request = @{source_url = 'https://media.example.test/list'}
        if ($validator) { $request.validator = $validator }
        $output = ($request | ConvertTo-Json -Compress) | & $entrypoint check
        if ($LASTEXITCODE -ne 0) { throw 'entrypoint failed' }
        $result = $output | ConvertFrom-Json
        if ($result -is [array]) { throw 'multiple source-check results' }
        return $result
    }
    [IO.File]::WriteAllText($env:SOURCE_CHECK_DATA, '{"_type":"playlist","id":"fixture","entries":[{"id":"one","ie_key":"Vimeo"}]}')
    $first = Invoke-Probe
    if ($first.outcome -ne 'changed') { throw 'first observation failed' }
    if ((Invoke-Probe $first.validator).outcome -ne 'unchanged') { throw 'unchanged observation failed' }
    [IO.File]::WriteAllText($env:SOURCE_CHECK_DATA, '{"_type":"playlist","id":"fixture","entries":[{"id":"two","ie_key":"Soundcloud"}]}')
    if ((Invoke-Probe $first.validator).outcome -ne 'changed') { throw 'changed observation failed' }
    foreach ($mode in @('failure', 'limit', 'sleep')) {
        $env:SOURCE_CHECK_MODE = $mode
        $watch = [Diagnostics.Stopwatch]::StartNew()
        $result = Invoke-Probe $first.validator
        if ($result.outcome -ne 'transient_failure' -or $result.validator) { throw 'failure handling failed' }
        if ($watch.Elapsed.TotalSeconds -gt 15) { throw 'deadline exceeded' }
    }
    $calls = [IO.File]::ReadAllLines($env:SOURCE_CHECK_CALLS)
    if ($calls.Count -ne 6) { throw 'unexpected extraction count' }
    foreach ($call in $calls) {
        if (!$call.Contains('--playlist-end|50') -or !$call.Contains('--abort-on-error') -or $call.Contains('--break-on-existing')) { throw 'unsafe extraction arguments' }
    }
    $env:ERSATZRS_ADDON_CAPABILITY = 'addon.check.v1'
    $ready = (& $entrypoint check) | ConvertFrom-Json
    if ($ready.status -ne 'ready') { throw 'readiness dispatch failed' }
    Write-Output 'PASS: native Windows first/unchanged/changed, failure, output cap, deadline, arguments, readiness (8 checks).'
} finally {
    # The production host owns a Job Object. Standalone fixtures also clean up
    # any native child left by the module-level overall deadline.
    Get-Process -Name fixture -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $fake } | Stop-Process -Force
    Set-Location $originalDirectory
    Remove-Item -LiteralPath $stage -Recurse -Force
}
