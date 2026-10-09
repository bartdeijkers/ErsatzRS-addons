# Synthetic Windows enrichment fixture; no provider or browser access.
param([string]$Package = (Join-Path $PSScriptRoot '../addons/org.ersatzrs.addon.yt-dlp'))
$ErrorActionPreference = 'Stop'
$stage = Join-Path $env:TEMP ('ersatzrs-authenticated-enrichment-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
try {
    $fake = Join-Path $stage 'fixture.exe'
    Add-Type -OutputAssembly $fake -OutputType ConsoleApplication -TypeDefinition @'
using System;
using System.IO;
public class EnrichmentFixture {
    public static int Main(string[] args) {
        Console.Write(File.ReadAllText(Environment.GetEnvironmentVariable("ENRICHMENT_FIXTURE_DATA")));
        return Environment.GetEnvironmentVariable("ENRICHMENT_FIXTURE_FAIL") == "1" ? 1 : 0;
    }
}
'@
    $env:ERSATZRS_ADDON_SETTING_YT_DLP_BIN = $fake
    $env:ERSATZRS_ADDON_CACHE_DIR = Join-Path $stage 'cache'
    $env:ENRICHMENT_FIXTURE_DATA = Join-Path $stage 'data.json'
    $env:ENRICHMENT_FIXTURE_FAIL = '0'
    $request = @{
        options = @{schema='media-list.options.v1';values=@{cookies_from_browser='firefox'}}
        request = @{
            source_url='https://www.youtube.com/watch?v=fixture';provider_id='fixture'
            record_capability='media-list.list.v6';overview_fingerprint=('a' * 64)
            item=@{source_url='https://www.youtube.com/watch?v=fixture';rank=4}
        }
    } | ConvertTo-Json -Depth 12 -Compress
    $cases = @(
        @{availability='needs_auth';formats=@(@{url='https://media.example.test/video';vcodec='avc1';acodec='none'});expected='available'},
        @{availability='needs_auth';formats=@(@{url='https://media.example.test/audio';vcodec='none';acodec='opus'});expected='available'},
        @{availability='needs_auth';formats=@();expected='unavailable'},
        @{availability='needs_auth';formats=@(@{vcodec='avc1'});expected='unavailable'},
        @{availability='needs_auth';formats=@(@{url='https://media.example.test/video';vcodec='avc1';has_drm=$true});expected='unavailable'},
        @{availability='needs_auth';formats=@(@{url='https://media.example.test/storyboard';vcodec='none';acodec='none'});expected='unavailable'},
        @{availability='private';formats=@(@{url='https://media.example.test/video';vcodec='avc1'});expected='unavailable'},
        @{availability='premium_only';formats=@(@{url='https://media.example.test/video';vcodec='avc1'});expected='unavailable'},
        @{availability='subscriber_only';formats=@(@{url='https://media.example.test/video';vcodec='avc1'});expected='unavailable'}
    )
    function Invoke-Fixture {
        $start = New-Object Diagnostics.ProcessStartInfo
        $start.FileName = $env:COMSPEC
        $start.Arguments = '/d /c ""' + (Join-Path $Package 'addon.bat') + '" enrich-options"'
        $start.UseShellExecute = $false
        $start.RedirectStandardInput = $true
        $start.RedirectStandardOutput = $true
        $start.RedirectStandardError = $true
        $process = [Diagnostics.Process]::Start($start)
        try {
            $process.StandardInput.Write($request)
            $process.StandardInput.Close()
            $output = $process.StandardOutput.ReadToEnd()
            $errorOutput = $process.StandardError.ReadToEnd()
            if (-not $process.WaitForExit(20000) -or $process.ExitCode -ne 0) { throw ('fixture invocation failed: ' + $errorOutput) }
            return @($output -split '\r?\n' | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
        } finally { $process.Dispose() }
    }
    foreach ($case in $cases) {
        $entry = @{id='fixture';title='Fixture';webpage_url='https://www.youtube.com/watch?v=fixture';duration=100;availability=$case.availability;formats=$case.formats}
        [IO.File]::WriteAllText($env:ENRICHMENT_FIXTURE_DATA, ($entry | ConvertTo-Json -Depth 12 -Compress))
        $rows = @(Invoke-Fixture)
        if ($rows.Count -ne 2 -or $rows[1].availability -ne $case.expected) { throw 'availability did not follow media evidence' }
        if ($case.expected -eq 'available') {
            if ($rows[0].outcome -ne 'complete' -or $rows[1].PSObject.Properties.Name -contains 'availability_reason_code') { throw 'authenticated availability retained a restriction' }
        } elseif ($rows[0].outcome -ne 'unavailable') { throw 'restriction was lost' }
    }
    $env:ENRICHMENT_FIXTURE_FAIL = '1'
    $rows = @(Invoke-Fixture)
    if ($rows.Count -ne 1 -or $rows[0].outcome -ne 'transient_failure') { throw 'failed extraction admitted media' }
    Write-Output 'PASS: 10 native Windows authenticated enrichment cases retain unavailable and failed-source behavior.'
} finally {
    Remove-Item -LiteralPath $stage -Recurse -Force
}
